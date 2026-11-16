from pathlib import Path
import tempfile
import unittest

from steamlaunch.storage import Paths, Profile


CONFIG = '''// Preserve this comment and every unrelated field.
"UserLocalConfigStore"
{
    "Software" { "Valve" { "Steam" {
        "apps" { "42" { "LastPlayed" "100" } }
        "Unrelated" "do not change \\"quoted\\" data"
    } } }
    "OtherSection" { "Key" "value" }
}
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        preferred = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None
        self.temporary = tempfile.TemporaryDirectory(prefix="steamlaunch-test-", dir=preferred)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.paths = Paths(self.base / "config", self.base / "state")
        self.root = self.base / "Steam"
        self.config = self.root / "userdata/123/config/localconfig.vdf"
        self.config.parent.mkdir(parents=True)
        self.config.write_text(CONFIG, encoding="utf-8")
        steamapps = self.root / "steamapps"
        (steamapps / "common/Test Game").mkdir(parents=True)
        (steamapps / "libraryfolders.vdf").write_text('"libraryfolders" {}')
        (steamapps / "appmanifest_42.acf").write_text(
            '"AppState" { "appid" "42" "name" "Test Game" '
            '"StateFlags" "4" "installdir" "Test Game" }')
        self.exe = self.base / "внешняя игра with spaces/Игра.exe"
        self.exe.parent.mkdir()
        self.exe.write_bytes(b"MZ dummy test executable; never executed")
        self.profile = Profile(name="Тестовый профиль", appid=42, steam_root=str(self.root),
                               account_id="123", executable=str(self.exe),
                               arguments=["--name", "one argument", "$(not-a-shell)"])
