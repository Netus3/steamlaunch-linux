from pathlib import Path
import json
import os
import sys
from unittest.mock import patch

from steamlaunch.installation import (desktop_argument, install_bundle, install_root,
                                     is_managed, uninstall_bundle)
from steamlaunch.runtime import configure_display, external_environment, launcher_command
from steamlaunch.storage import LaunchError, ProfileStore
from tests.helpers import Fixture


class RuntimeTests(Fixture):
    def test_source_launcher_keeps_venv_path(self):
        with patch.object(sys, "executable", "/venv/bin/python"), patch.object(sys, "frozen", False, create=True):
            self.assertEqual(launcher_command(), ["/venv/bin/python", "-I", "-m", "steamlaunch"])

    def test_frozen_launcher_is_not_invoked_as_python(self):
        with patch.object(sys, "executable", str(self.base / "SteamLaunch")), \
             patch.object(sys, "frozen", True, create=True), \
             patch.dict(os.environ, {"XDG_DATA_HOME": str(self.base / "data")}):
            self.assertEqual(launcher_command(), [str(self.base / "SteamLaunch")])

    def test_environment_boundary_preserves_overlay_and_session(self):
        env = {"LD_LIBRARY_PATH": "/bundle:/system", "LD_LIBRARY_PATH_ORIG": "/system",
               "LD_PRELOAD": "steam-overlay.so", "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-1",
               "QT_PLUGIN_PATH": "/bundle/plugins", "_STEAMLAUNCH_QT_ENV":
               json.dumps({"QT_PLUGIN_PATH": "/original/plugins"})}
        with patch.object(sys, "frozen", True, create=True):
            clean = external_environment(env)
        self.assertEqual(clean["LD_LIBRARY_PATH"], "/system")
        self.assertEqual(clean["QT_PLUGIN_PATH"], "/original/plugins")
        self.assertEqual(clean["LD_PRELOAD"], "steam-overlay.so")
        self.assertEqual(clean["WAYLAND_DISPLAY"], "wayland-1")
        self.assertNotIn("_STEAMLAUNCH_QT_ENV", clean)
        self.assertNotIn("LD_LIBRARY_PATH_ORIG", clean)
        self.assertEqual(env["LD_LIBRARY_PATH"], "/bundle:/system")

    def test_no_original_ld_path_is_removed_only_in_frozen_process(self):
        env = {"LD_LIBRARY_PATH": "/bundle", "QT_PLUGIN_PATH": "/bundle/plugins"}
        with patch.object(sys, "frozen", True, create=True):
            self.assertNotIn("LD_LIBRARY_PATH", external_environment(env))
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(external_environment(env), env)

    def test_display_selection_and_user_override(self):
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0"}, clear=True):
            configure_display()
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "wayland;xcb")
            configure_display("x11")
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "xcb")
            configure_display("wayland")
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "wayland")
        with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True):
            configure_display()
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "xcb")
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen", "WAYLAND_DISPLAY": "wayland-1"}, clear=True):
            configure_display()
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "offscreen")

    def test_gui_backend_does_not_leak_into_game_launchers(self):
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}, clear=True), \
             patch.object(sys, "frozen", False, create=True):
            configure_display("wayland")
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "wayland")
            self.assertNotIn("QT_QPA_PLATFORM", external_environment())
            self.assertEqual(external_environment()["WAYLAND_DISPLAY"], "wayland-1")


class InstallationTests(Fixture):
    def setUp(self):
        super().setUp()
        home = self.base / "home"
        home.mkdir()
        env = patch.dict(os.environ, {"HOME": str(home), "XDG_DATA_HOME": str(self.base / "user data $ name")})
        env.start()
        self.addCleanup(env.stop)
        self.source = self.base / "bundle"
        (self.source / "_internal/steamlaunch/assets").mkdir(parents=True)
        (self.source / "SteamLaunch").write_text("#!/bin/sh\nexit 0\n")
        (self.source / "SteamLaunch").chmod(0o755)
        (self.source / "bundle.json").write_text(json.dumps({"app": "steamlaunch-linux", "version": "test"}))

    def test_install_update_stable_launcher_and_uninstall_keep_data(self):
        ProfileStore(self.paths).save(self.profile)
        root = install_bundle(self.source)
        self.assertTrue(is_managed(root))
        old = (root / "current").resolve()
        script = (root / "SteamLaunch").read_text()
        install_bundle(self.source)
        self.assertNotEqual(old, (root / "current").resolve())
        self.assertTrue(old.is_dir(), "Never remove libraries of a running version")
        self.assertEqual(script, (root / "SteamLaunch").read_text())
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", str(root / "current/SteamLaunch")):
            self.assertEqual(launcher_command(), [str(root / "SteamLaunch")])
        uninstall_bundle(self.paths)
        self.assertFalse(root.exists())
        self.assertEqual(ProfileStore(self.paths).get(self.profile.id), self.profile)

    def test_foreign_install_directory_is_not_overwritten(self):
        root = install_root()
        root.mkdir(parents=True)
        (root / "user-file").write_text("keep")
        with self.assertRaises(LaunchError):
            install_bundle(self.source)
        self.assertEqual((root / "user-file").read_text(), "keep")
        with self.assertRaises(LaunchError):
            uninstall_bundle(self.paths)

    def test_foreign_launcher_is_not_overwritten(self):
        link = Path.home() / ".local/bin/steamlaunch"
        link.parent.mkdir(parents=True)
        link.write_text("keep")
        with self.assertRaises(LaunchError):
            install_bundle(self.source)
        self.assertEqual(link.read_text(), "keep")

    def test_uninstall_refuses_active_binding(self):
        install_bundle(self.source)
        with patch("steamlaunch.bindings.Bindings.all", return_value={"binding": {}}):
            with self.assertRaises(LaunchError):
                uninstall_bundle(self.paths)
        self.assertTrue(is_managed(install_root()))

    def test_desktop_exec_escaping_not_shell_quoting(self):
        self.assertEqual(desktop_argument("/simple path/app"), '"/simple path/app"')
        self.assertIn("%%", desktop_argument("/a%/app"))
        self.assertIn("\\\\$", desktop_argument("/a$/app"))

    def test_source_install_without_bundle_is_refused(self):
        with patch.object(sys, "frozen", False, create=True), self.assertRaises(LaunchError):
            install_bundle()
