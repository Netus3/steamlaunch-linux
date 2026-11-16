import unittest

from steamlaunch.keyvalues import Document, KeyValuesError, quote


class KeyValuesTests(unittest.TestCase):
    def test_quotes_and_escapes_roundtrip(self):
        for value in ['', 'кириллица', 'a"b\\c', '\t\n\r', r'C:\Games\dir', '$(touch /no)']:
            with self.subTest(value=value):
                self.assertEqual(Document('"key" ' + quote(value)).string(["key"]), value)

    def test_surgical_replacement(self):
        text = '// comment\r\n"ROOT" { "a" "old" /* unknown */ "b" "untouched" }\r\n'
        updated = Document(text).set_string(["root", "A"], 'new "value"')
        self.assertEqual(updated, text.replace('"old"', quote('new "value"')))

    def test_add_nested_to_inline_and_multiline_objects(self):
        for text in ['"root" {}', '"root" { "existing" "yes" }',
                     '\ufeff"root"\r\n{\r\n}\r\n', '']:
            with self.subTest(text=text):
                updated = Document(text).set_string(["root", "nested", "key"], "value")
                self.assertEqual(Document(updated).string(["root", "nested", "key"]), "value")
                if '"existing"' in text:
                    self.assertEqual(Document(updated).string(["root", "existing"]), "yes")

    def test_remove_missing_is_noop_and_existing_preserves_other_text(self):
        text = '"root" { "a" "value" // retain\n "b" "other" }'
        doc = Document(text)
        self.assertEqual(doc.set_string(["root", "none"], None), text)
        updated = doc.set_string(["root", "a"], None)
        self.assertIn('// retain', updated)
        self.assertIsNone(Document(updated).string(["root", "a"]))
        self.assertEqual(Document(updated).string(["root", "b"]), "other")

    def test_duplicate_target_and_ancestor_are_rejected(self):
        for text, path in [('"a" "1" "A" "2"', ["a"]),
                           ('"root" {} "ROOT" {}', ["root", "new"])]:
            with self.subTest(text=text), self.assertRaises(KeyValuesError):
                Document(text).set_string(path, "no")

    def test_scalar_cannot_become_object(self):
        with self.assertRaises(KeyValuesError):
            Document('"root" "scalar"').set_string(["root", "child"], "no")

    def test_malformed_documents_are_rejected(self):
        for text in ['"key"', '"key" {', '}', '{ "x" "y" }', '"key" "unterminated',
                     '/* unterminated', '\0binary', '"root" }']:
            with self.subTest(text=text), self.assertRaises(KeyValuesError):
                Document(text)

    def test_unquoted_tokens_and_unknown_backslash(self):
        self.assertEqual(Document(r'root { path "C:\unknown" }').string(["root", "path"]),
                         r'C:\unknown')

    def test_deep_input_is_bounded(self):
        with self.assertRaises(KeyValuesError):
            Document('"a" {' * 102 + '}' * 102)
