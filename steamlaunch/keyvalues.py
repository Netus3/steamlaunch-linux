"""Small text KeyValues reader with surgical string edits, not a VDF serializer.

Unknown fields, comments, whitespace and key casing are preserved when editing
LaunchOptions. Binary appinfo.vdf is intentionally not supported.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence


class KeyValuesError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    value: str
    start: int
    end: int
    kind: str = "string"


@dataclass
class Node:
    key: Token
    value: Token | None = None
    children: list[Node] | None = None
    close: Token | None = None

    def child(self, key: str) -> Node | None:
        return find_child(self.children or [], key)

    def string(self, key: str, default: str = "") -> str:
        child = self.child(key)
        if child is None:
            return default
        if child.value is None:
            raise KeyValuesError(f"Ожидалось строковое поле: {key}")
        return child.value.value


def find_child(nodes: list[Node], key: str) -> Node | None:
    matches = [node for node in nodes if node.key.value.casefold() == key.casefold()]
    if len(matches) > 1:
        raise KeyValuesError(f"Неоднозначное поле VDF (дубликат): {key}")
    return matches[0] if matches else None


def quote(value: str) -> str:
    if "\0" in value:
        raise KeyValuesError("Нулевой байт в строке VDF")
    return '"' + (value.replace("\\", "\\\\").replace('"', '\\"')
                  .replace("\n", "\\n").replace("\r", "\\r")
                  .replace("\t", "\\t")) + '"'


def tokenize(text: str) -> list[Token]:
    if "\0" in text:
        raise KeyValuesError("Ожидался текстовый VDF, а не бинарный файл")
    tokens: list[Token] = []
    i = 0
    while i < len(text):
        if text[i].isspace() or (i == 0 and text[i] == "\ufeff"):
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise KeyValuesError("Незакрытый комментарий VDF")
            i = end + 2
            continue
        start = i
        if text[i] in "{}":
            tokens.append(Token(text[i], i, i + 1, text[i]))
            i += 1
        elif text[i] == '"':
            i += 1
            chars: list[str] = []
            while i < len(text) and text[i] != '"':
                if text[i] == "\\" and i + 1 < len(text):
                    escaped = text[i + 1]
                    chars.append({"n": "\n", "r": "\r", "t": "\t",
                                  '"': '"', "\\": "\\"}.get(escaped, "\\" + escaped))
                    i += 2
                else:
                    chars.append(text[i])
                    i += 1
            if i >= len(text):
                raise KeyValuesError("Незакрытая строка VDF")
            i += 1
            tokens.append(Token("".join(chars), start, i))
        else:
            while i < len(text) and not text[i].isspace() and text[i] not in '{}"':
                i += 1
            tokens.append(Token(text[start:i], start, i))
    return tokens


class Document:
    def __init__(self, text: str):
        self.text = text
        self._tokens = tokenize(text)
        self._cursor = 0
        self.nodes, _ = self._parse(False, 0)

    def _parse(self, nested: bool, depth: int) -> tuple[list[Node], Token | None]:
        if depth > 100:
            raise KeyValuesError("Слишком глубокая вложенность VDF")
        nodes: list[Node] = []
        while self._cursor < len(self._tokens):
            key = self._tokens[self._cursor]
            self._cursor += 1
            if key.kind == "}":
                if nested:
                    return nodes, key
                raise KeyValuesError("Лишняя закрывающая скобка VDF")
            if key.kind != "string" or self._cursor >= len(self._tokens):
                raise KeyValuesError("Отсутствует значение VDF")
            value = self._tokens[self._cursor]
            self._cursor += 1
            if value.kind == "{":
                children, close = self._parse(True, depth + 1)
                nodes.append(Node(key, children=children, close=close))
            elif value.kind == "string":
                nodes.append(Node(key, value=value))
            else:
                raise KeyValuesError("Некорректное значение VDF")
        if nested:
            raise KeyValuesError("Незакрытая скобка VDF")
        return nodes, None

    def get(self, path: Sequence[str]) -> Node | None:
        nodes = self.nodes
        result = None
        for key in path:
            result = find_child(nodes, key)
            if result is None:
                return None
            nodes = result.children or []
        return result

    def string(self, path: Sequence[str]) -> str | None:
        node = self.get(path)
        if node is None:
            return None
        if node.value is None:
            raise KeyValuesError(f"Ожидалось строковое поле: {'/'.join(path)}")
        return node.value.value

    def set_string(self, path: Sequence[str], value: str | None) -> str:
        if not path:
            raise KeyValuesError("Пустой путь VDF")
        node = self.get(path)
        if node is not None:
            if node.value is None:
                raise KeyValuesError("Нельзя заменить объект VDF строкой")
            if value is None:
                return self.text[:node.key.start] + self.text[node.value.end:]
            return (self.text[:node.value.start] + quote(value)
                    + self.text[node.value.end:])
        if value is None:
            return self.text

        parent: Node | None = None
        nodes = self.nodes
        depth = 0
        for key in path[:-1]:
            child = find_child(nodes, key)
            if child is None:
                break
            if child.children is None:
                raise KeyValuesError(f"Ожидался объект VDF: {key}")
            parent, nodes = child, child.children
            depth += 1

        nl = "\r\n" if "\r\n" in self.text else "\n"

        def render(keys: Sequence[str], level: int) -> str:
            indent = "\t" * level
            if len(keys) == 1:
                return f"{indent}{quote(keys[0])}\t\t{quote(value)}{nl}"
            return (f"{indent}{quote(keys[0])}{nl}{indent}{{{nl}"
                    + render(keys[1:], level + 1) + f"{indent}}}{nl}")

        offset = parent.close.start if parent and parent.close else len(self.text)
        line_start = self.text.rfind("\n", 0, offset) + 1
        closing_indent = self.text[line_start:offset]
        if closing_indent.strip() == "":
            offset = line_start
            suffix_indent = ""
        else:
            suffix_indent = "\t" * max(0, depth - 1) if parent else ""
        prefix = "" if offset == 0 or self.text[offset - 1] == "\n" else nl
        return (self.text[:offset] + prefix + render(path[depth:], depth)
                + suffix_indent + self.text[offset:])
