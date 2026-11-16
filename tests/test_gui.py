from dataclasses import replace
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from steamlaunch.gui import MainWindow
from steamlaunch.storage import LaunchError, ProfileStore
from tests.helpers import CONFIG, Fixture


class GuiTests(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.detection = patch("steamlaunch.gui.detect_steam", return_value=self.root)
        self.detection.start()
        self.addCleanup(self.detection.stop)
        self.window = MainWindow(self.paths)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def fill(self):
        self.window.name.setText(self.profile.name)
        self.window.exe.setText(self.profile.executable)
        self.window.arguments.setText('--name "one argument"')

    def test_opening_window_does_not_create_state_or_change_steam(self):
        self.assertEqual(self.window.game.currentData(), 42)
        self.assertEqual(self.window.account.currentData(), "123")
        self.assertFalse(self.paths.config.exists())
        self.assertFalse(self.paths.state.exists())
        self.assertEqual(self.config.read_text(), CONFIG)

    def test_save_and_reload_profile(self):
        self.fill()
        profile = self.window.save_profile()
        self.assertFalse(self.window.dirty)
        self.assertTrue(self.window.saved)
        self.assertEqual(profile.arguments, ["--name", "one argument"])
        self.assertEqual(ProfileStore(self.paths).get(profile.id), profile)
        self.window.new_profile()
        self.window._load(profile)
        self.assertEqual(self.window.exe.text(), str(self.exe))
        self.assertFalse(self.window.dirty)

    def test_invalid_arguments_do_not_save(self):
        self.fill()
        self.window.arguments.setText('"unterminated')
        with self.assertRaises(LaunchError):
            self.window.save_profile()
        self.assertFalse(self.paths.config.exists())

    def test_cancel_selection_keeps_original_profile_and_edits(self):
        self.fill()
        first = self.window.save_profile()
        other = replace(first, id="b" * 32, name="Other profile")
        ProfileStore(self.paths).save(other)
        self.window._populate(self.window.store.all(), first.id)
        self.window.name.setText("unsaved edit")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            for index in range(self.window.profiles.count()):
                item = self.window.profiles.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == other.id:
                    self.window.profiles.setCurrentItem(item)
                    break
        self.assertEqual(self.window.current.id, first.id)
        self.assertEqual(self.window.name.text(), "unsaved edit")
        self.assertEqual(self.window.profiles.currentItem().data(Qt.ItemDataRole.UserRole), first.id)

    def test_instruction_and_missing_log_do_not_change_steam(self):
        self.fill()
        self.window.save_profile()
        with patch.object(self.window, "_text_dialog") as display:
            self.window.instructions()
            self.assertIn("%command%", display.call_args.args[2])
            self.window.show_log()
            self.assertIn("ещё не создан", display.call_args.args[1])
        self.assertEqual(self.config.read_text(), CONFIG)
        self.assertFalse(self.paths.state.exists())

    def test_launch_unbound_profile_is_refused(self):
        self.fill()
        with patch("steamlaunch.gui.subprocess.Popen") as process:
            with self.assertRaises(LaunchError):
                self.window.launch()
            process.assert_not_called()

    def test_apply_restore_and_bound_delete_guard(self):
        self.fill()
        with patch("steamlaunch.gui.require_steam_stopped"), \
             patch("steamlaunch.bindings.require_steam_stopped"), \
             patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
            self.window.apply_binding()
        self.assertIn("Привязка активна", self.window.status.text())
        with self.assertRaises(LaunchError):
            self.window.delete_profile()
        with patch("steamlaunch.gui.require_steam_stopped"), \
             patch("steamlaunch.bindings.require_steam_stopped"), \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.restore_binding()
        self.assertIsNone(self.window.bindings.for_profile(self.window.current.id))

    def test_corrupted_profile_file_is_reported_without_overwrite(self):
        self.paths.config.mkdir()
        file = self.paths.config / "profiles.json"
        file.write_text("corrupted")
        window = MainWindow(self.paths)
        try:
            self.assertTrue(window.startup_errors)
            self.assertEqual(file.read_text(), "corrupted")
        finally:
            window.dirty = False
            window.close()
