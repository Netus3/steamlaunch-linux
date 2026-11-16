from dataclasses import replace
import os
from pathlib import Path
from unittest.mock import patch

from steamlaunch.steam import accounts, installed_games, steam_running
from steamlaunch.storage import LaunchError, Paths, ProfileStore, atomic_write
from tests.helpers import Fixture


class StorageTests(Fixture):
    def test_store_read_does_not_create_directories(self):
        self.assertEqual(ProfileStore(self.paths).all(), [])
        self.assertFalse(self.paths.config.exists())
        self.assertFalse(self.paths.state.exists())

    def test_save_update_delete_and_private_permissions(self):
        store = ProfileStore(self.paths)
        store.save(self.profile)
        self.assertEqual(store.get(self.profile.id), self.profile)
        store.save(replace(self.profile, name="Новое имя"))
        self.assertEqual(len(store.all()), 1)
        self.assertEqual(store.get(self.profile.id).name, "Новое имя")
        self.assertEqual(store.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.paths.config.stat().st_mode & 0o777, 0o700)
        store.delete(self.profile.id)
        self.assertEqual(store.all(), [])

    def test_corrupted_store_is_not_overwritten(self):
        self.paths.config.mkdir()
        path = self.paths.config / "profiles.json"
        for data in ['not json', '{"version": 99}', '{"version": 1, "profiles": [null]}']:
            path.write_text(data)
            with self.subTest(data=data), self.assertRaises(LaunchError):
                ProfileStore(self.paths).save(self.profile)
            self.assertEqual(path.read_text(), data)

    def test_invalid_profiles(self):
        for changes in [{"id": "../../other"}, {"appid": True}, {"account_id": "../x"},
                        {"executable": "relative.exe"}, {"arguments": "string"},
                        {"arguments": ["a\0b"]}, {"name": ""}, {"proton_log": 1},
                        {"executable": str(self.exe.with_suffix('.sh'))}]:
            with self.subTest(changes=changes), self.assertRaises(LaunchError):
                replace(self.profile, **changes).validate()

    def test_paths_honor_absolute_xdg_only(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.base / "cfg"),
                                     "XDG_STATE_HOME": str(self.base / "st")}):
            self.assertEqual(Paths.default(), Paths(self.base / "cfg/steamlaunch",
                                                   self.base / "st/steamlaunch"))
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}):
            self.assertEqual(Paths.default().config, Path.home() / ".config/steamlaunch")

    def test_atomic_write_preserves_requested_permissions(self):
        target = self.base / "new/target"
        atomic_write(target, b"old", 0o640)
        atomic_write(target, b"new", 0o640)
        self.assertEqual(target.read_bytes(), b"new")
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertEqual([p.name for p in target.parent.iterdir()], ["target"])


class SteamDiscoveryTests(Fixture):
    def test_installed_game(self):
        games, warnings = installed_games(self.root)
        self.assertEqual([game.appid for game in games], [42])
        self.assertEqual(warnings, [])

    def test_external_library_and_runtime_filter(self):
        library = self.base / "external library"
        common = library / "steamapps/common"
        for directory in ["Other Game", "Proton 10.0", "Incomplete"]:
            (common / directory).mkdir(parents=True)
        for appid, name, state in [(43, "Other Game", 4), (44, "Proton 10.0", 4), (45, "Incomplete", 2)]:
            (library / f"steamapps/appmanifest_{appid}.acf").write_text(
                f'"AppState" {{ "appid" "{appid}" "name" "{name}" '
                f'"StateFlags" "{state}" "installdir" "{name}" }}')
        (self.root / "steamapps/libraryfolders.vdf").write_text(
            f'"libraryfolders" {{ "1" {{ "path" "{library}" }} }}')
        games, warnings = installed_games(self.root)
        self.assertEqual({game.appid for game in games}, {42, 43})
        self.assertEqual(warnings, [])

    def test_corrupt_manifest_does_not_hide_good_games(self):
        (self.root / "steamapps/appmanifest_99.acf").write_text('"broken" {')
        games, warnings = installed_games(self.root)
        self.assertEqual([game.appid for game in games], [42])
        self.assertEqual(len(warnings), 1)

    def test_accounts_without_login_metadata(self):
        found = accounts(self.root)
        self.assertEqual([a.id for a in found], ["123"])

    def test_account_persona_and_most_recent(self):
        (self.root / "config").mkdir()
        (self.root / "config/loginusers.vdf").write_text(
            '"users" { "76561197960265851" { "PersonaName" "Tester" "MostRecent" "1" } }')
        account = accounts(self.root)[0]
        self.assertEqual((account.id, account.name, account.recent), ("123", "Tester", True))

    def test_process_check_uses_test_proc_not_real_steam(self):
        proc = self.base / "proc"
        (proc / "123").mkdir(parents=True)
        (proc / "123/comm").write_text("not-steam\n")
        self.assertFalse(steam_running(proc))
        (proc / "123/comm").write_text("steam\n")
        self.assertTrue(steam_running(proc))

    def test_process_check_fails_closed(self):
        with self.assertRaises(LaunchError):
            steam_running(self.base / "missing-proc")
