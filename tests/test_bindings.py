from dataclasses import replace
from unittest.mock import patch

from steamlaunch.bindings import Bindings, binding_key, launch_options, options_path
from steamlaunch.keyvalues import Document
from steamlaunch.storage import LaunchError
from tests.helpers import CONFIG, Fixture


class BindingTests(Fixture):
    def setUp(self):
        super().setUp()
        # All writes are to temporary fixtures; never touch the real Steam client.
        self.stopped = patch("steamlaunch.bindings.require_steam_stopped").start()
        self.addCleanup(patch.stopall)
        self.bindings = Bindings(self.paths)

    def current(self):
        return Document(self.config.read_text()).string(options_path(42))

    def set_options(self, value):
        self.config.write_text(Document(self.config.read_text()).set_string(options_path(42), value))

    def test_apply_restore_missing_field_and_preserve_unrelated_content(self):
        self.bindings.apply(self.profile)
        self.assertEqual(self.current(), launch_options(self.profile, self.paths))
        entry = self.bindings.for_profile(self.profile.id)
        self.assertIsNone(entry["previous"])
        self.assertEqual(entry["phase"], "applied")
        backup = self.paths.state / "backups"
        self.assertEqual(len(list(backup.iterdir())), 1)
        copy = next(backup.iterdir())
        self.assertEqual(copy.read_text(), CONFIG)
        self.assertEqual(copy.stat().st_mode & 0o777, 0o600)
        self.bindings.restore(self.profile.id)
        self.assertIsNone(self.current())
        self.assertIn('"Unrelated" "do not change', self.config.read_text())
        self.assertIn('// Preserve this comment', self.config.read_text())
        self.assertIsNone(self.bindings.for_profile(self.profile.id))

    def test_restore_exact_existing_options_and_empty_string(self):
        for original in ["", 'MANGOHUD=1 %command% --foo "a b"', "'complex shell' | cat"]:
            with self.subTest(original=original):
                self.set_options(original)
                self.bindings.apply(self.profile)
                self.assertEqual(self.bindings.for_profile(self.profile.id)["previous"], original)
                self.bindings.restore(self.profile.id)
                self.assertEqual(self.current(), original)

    def test_repeated_apply_keeps_original(self):
        self.set_options("original")
        self.bindings.apply(self.profile)
        self.bindings.apply(self.profile)
        self.assertEqual(self.bindings.for_profile(self.profile.id)["previous"], "original")
        self.bindings.restore(self.profile.id)
        self.assertEqual(self.current(), "original")

    def test_migration_to_binary_keeps_original_restoration_record(self):
        self.set_options("old user options")
        self.bindings.apply(self.profile)
        with patch("steamlaunch.bindings.launcher_command", return_value=["/stable/SteamLaunch"]):
            self.assertIn("обновить путь", self.bindings.status(self.profile))
            self.bindings.apply(self.profile)
            self.assertTrue(self.current().startswith("/stable/SteamLaunch wrap "))
            self.assertEqual(self.bindings.for_profile(self.profile.id)["previous"], "old user options")
        self.bindings.restore(self.profile.id)
        self.assertEqual(self.current(), "old user options")

    def test_refuses_when_steam_is_running(self):
        self.stopped.side_effect = LaunchError("Steam is running")
        with self.assertRaises(LaunchError):
            self.bindings.apply(self.profile)
        self.assertEqual(self.config.read_text(), CONFIG)
        self.assertFalse(self.bindings.file.exists())

    def test_conflicting_external_edit_is_never_overwritten(self):
        self.bindings.apply(self.profile)
        self.set_options("new external change")
        before = self.config.read_bytes()
        for operation in [lambda: self.bindings.apply(self.profile),
                          lambda: self.bindings.restore(self.profile.id)]:
            with self.assertRaises(LaunchError):
                operation()
            self.assertEqual(self.config.read_bytes(), before)

    def test_external_unrelated_changes_survive_restore(self):
        self.bindings.apply(self.profile)
        document = Document(self.config.read_text())
        self.config.write_text(document.set_string(["UserLocalConfigStore", "OtherSection", "Key"], "new"))
        self.bindings.restore(self.profile.id)
        self.assertEqual(Document(self.config.read_text()).string(
            ["UserLocalConfigStore", "OtherSection", "Key"]), "new")

    def test_interrupted_before_config_write_can_be_retried(self):
        with patch.object(self.bindings, "_write_config", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                self.bindings.apply(self.profile)
        self.assertIsNone(self.current())
        self.assertEqual(self.bindings.for_profile(self.profile.id)["phase"], "pending")
        self.bindings.apply(self.profile)
        self.bindings.restore(self.profile.id)
        self.assertIsNone(self.current())

    def test_interrupted_before_config_write_can_be_cancelled(self):
        with patch.object(self.bindings, "_write_config", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                self.bindings.apply(self.profile)
        self.bindings.restore(self.profile.id)
        self.assertEqual(self.config.read_text(), CONFIG)
        self.assertEqual(self.bindings.all(), {})

    def test_interrupted_after_config_write_remains_reversible(self):
        real_save = self.bindings._save
        count = 0

        def crashing_save(entries):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("simulated crash after config write")
            real_save(entries)

        with patch.object(self.bindings, "_save", side_effect=crashing_save):
            with self.assertRaises(OSError):
                self.bindings.apply(self.profile)
        self.assertEqual(self.current(), launch_options(self.profile, self.paths))
        self.assertEqual(self.bindings.for_profile(self.profile.id)["phase"], "pending")
        self.bindings.restore(self.profile.id)
        self.assertIsNone(self.current())

    def test_interrupted_restore_can_be_completed(self):
        self.set_options("original")
        self.bindings.apply(self.profile)
        with patch.object(self.bindings, "_write_config", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                self.bindings.restore(self.profile.id)
        self.assertEqual(self.bindings.for_profile(self.profile.id)["phase"], "restoring")
        with self.assertRaises(LaunchError):
            self.bindings.apply(self.profile)
        self.bindings.restore(self.profile.id)
        self.assertEqual(self.current(), "original")

    def test_interrupted_update_remembers_old_applied_string(self):
        self.set_options("original")
        self.bindings.apply(self.profile)
        old_applied = self.current()
        with patch("steamlaunch.bindings.launch_options", return_value="new wrapper command"):
            with patch.object(self.bindings, "_write_config", side_effect=OSError("simulated crash")):
                with self.assertRaises(OSError):
                    self.bindings.apply(self.profile)
        self.assertEqual(self.current(), old_applied)
        self.bindings.restore(self.profile.id)
        self.assertEqual(self.current(), "original")

    def test_interrupted_after_restore_write_can_clear_journal(self):
        self.set_options("original")
        self.bindings.apply(self.profile)
        real_save = self.bindings._save
        count = 0

        def crashing_save(entries):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("simulated crash after restoring config")
            real_save(entries)

        with patch.object(self.bindings, "_save", side_effect=crashing_save):
            with self.assertRaises(OSError):
                self.bindings.restore(self.profile.id)
        self.assertEqual(self.current(), "original")
        self.assertEqual(self.bindings.for_profile(self.profile.id)["phase"], "restoring")
        self.bindings.restore(self.profile.id)
        self.assertEqual(self.bindings.all(), {})

    def test_duplicate_launch_options_refused_before_backup_or_write(self):
        self.set_options("first")
        text = self.config.read_text()
        value = '"LaunchOptions"\t\t"first"'
        self.assertIn(value, text)
        self.config.write_text(text.replace(value, value + '\n"launchoptions" "second"'))
        before = self.config.read_bytes()
        with self.assertRaises(ValueError):
            self.bindings.apply(self.profile)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.paths.state / "backups").exists())

    def test_manual_restoration_can_clear_journal(self):
        self.set_options("original")
        self.bindings.apply(self.profile)
        self.set_options("original")
        self.bindings.restore(self.profile.id)
        self.assertEqual(self.bindings.all(), {})

    def test_another_profile_cannot_steal_binding_or_change_target(self):
        self.bindings.apply(self.profile)
        with self.assertRaises(LaunchError):
            self.bindings.apply(replace(self.profile, id="a" * 32))
        with self.assertRaises(LaunchError):
            self.bindings.check_identity(replace(self.profile, appid=43))

    def test_optimistic_write_check_and_symlink_refusal(self):
        before = self.config.read_bytes()
        self.config.write_text(CONFIG + "// external write\n")
        with self.assertRaises(LaunchError):
            self.bindings._write_config(self.config, before, CONFIG, 0o600)
        self.config.unlink()
        target = self.base / "real.vdf"
        target.write_text(CONFIG)
        self.config.symlink_to(target)
        with self.assertRaises(LaunchError):
            self.bindings.apply(self.profile)
        self.assertEqual(target.read_text(), CONFIG)

    def test_invalid_journal_does_not_change_config(self):
        self.bindings.apply(self.profile)
        data = self.bindings.all()
        data[binding_key(self.profile)]["account_id"] = "../../outside"
        self.bindings._save(data)
        before = self.config.read_bytes()
        with self.assertRaises(LaunchError):
            self.bindings.restore(self.profile.id)
        self.assertEqual(self.config.read_bytes(), before)

    def test_malformed_journal_values_fail_with_actionable_error(self):
        self.bindings.apply(self.profile)
        for changes in [{"phase": []}, {"appid": "42"}, {"steam_root": None},
                        {"profile_id": "bad"}, {"pending_from": []}]:
            with self.subTest(changes=changes):
                data = self.bindings.all()
                key = binding_key(self.profile)
                original = data[key].copy()
                data[key].update(changes)
                self.bindings._save(data)
                with self.assertRaises(LaunchError):
                    self.bindings.all()
                data[key] = original
                self.bindings._save(data)
