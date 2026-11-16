"""Test the distributed archive, not the source interpreter. No real games."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from steamlaunch.storage import Paths, ProfileStore  # noqa: E402 - standalone source checkout
from tests.helpers import Fixture  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--platform", choices=["offscreen", "xcb", "wayland"], default="offscreen")
    args = parser.parse_args()
    fixture = Fixture()
    fixture.setUp()
    try:
        unpacked = fixture.base / "распакованная сборка $ test"
        with tarfile.open(args.archive) as tar:
            tar.extractall(unpacked, filter="data")
        bundle = unpacked / "SteamLaunch"
        binary = bundle / "SteamLaunch"
        assert (bundle / "licenses/LGPL-3.0-only.txt").is_file()
        assert (bundle / "licenses/CPython-LICENSE.txt").is_file()
        assert not list((bundle / "_internal").rglob("*VirtualKeyboard*"))
        assert not list((bundle / "_internal").rglob("*virtualkeyboard*"))
        plugins = bundle / "_internal/PySide6/Qt/plugins/platforms"
        assert (plugins / "libqxcb.so").is_file(), "Missing Qt X11 plugin"
        assert any(plugins.glob("libqwayland*.so")), "Missing Qt Wayland plugin"
        env = dict(os.environ, HOME=str(fixture.base / "home"),
                   XDG_DATA_HOME=str(fixture.base / "user data $ name"),
                   XDG_CONFIG_HOME=str(fixture.base / "xdg-config"),
                   XDG_STATE_HOME=str(fixture.base / "xdg-state"),
                   QT_QPA_PLATFORM=args.platform)
        Path(env["HOME"]).mkdir()
        fixture.paths = Paths(Path(env["XDG_CONFIG_HOME"]) / "steamlaunch",
                              Path(env["XDG_STATE_HOME"]) / "steamlaunch")
        subprocess.run([str(binary), "--version"], env=env, check=True, timeout=30)
        subprocess.run([str(binary), "gui", "--smoke-test"], env=env, check=True, timeout=40)
        doctor = subprocess.run([str(binary), "doctor"], env=env, capture_output=True, text=True, timeout=30)
        assert doctor.returncode in {0, 1} and "SteamLaunch" in doctor.stdout, doctor.stderr
        # Installing twice exercises immutable version directories + atomic current
        # symlink updates. Only the temporary HOME/XDG tree is ever touched.
        for _ in range(2):
            subprocess.run([str(binary), "install"], env=env, check=True, timeout=90)
        installed = Path(env["XDG_DATA_HOME"]) / "steamlaunch/SteamLaunch"
        desktop = Path(env["XDG_DATA_HOME"]) / "applications/steamlaunch.desktop"
        assert desktop.is_file()
        if shutil.which("desktop-file-validate"):
            subprocess.run(["desktop-file-validate", str(desktop)], check=True, timeout=10)
        subprocess.run([str(installed), "--version"], env=env, check=True, timeout=30)
        ProfileStore(fixture.paths).save(fixture.profile)
        fake_proton = fixture.base / "proton"
        capture = fixture.base / "capture.json"
        fake_proton.write_text(
            "import os,sys,json\nfrom pathlib import Path\n"
            "Path(os.environ['CAPTURE']).write_text(json.dumps({'pid':os.getpid(),"
            "'argv':sys.argv,'cwd':os.getcwd(),'ld':os.environ.get('LD_LIBRARY_PATH'),"
            "'qt':os.environ.get('QT_PLUGIN_PATH')}))\nsys.exit(23)\n")
        original_ld = str(fixture.base / "original-system-libraries")
        original_qt = "/original/user/qt-plugins"
        wrapenv = env | {"SteamAppId": "42", "SteamGameId": "42", "CAPTURE": str(capture),
                         "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(fixture.root),
                         "STEAM_COMPAT_DATA_PATH": str(fixture.base / "prefix"),
                         "LD_LIBRARY_PATH": original_ld, "QT_PLUGIN_PATH": original_qt}
        command = [str(installed), "wrap", "--config-dir", str(fixture.paths.config),
                   "--state-dir", str(fixture.paths.state), "--profile", fixture.profile.id,
                   "--", sys.executable, str(fake_proton), "run", "old.exe"]
        proc = subprocess.Popen(command, env=wrapenv, cwd=fixture.base)
        assert proc.wait(timeout=30) == 23
        result = json.loads(capture.read_text())
        assert result["pid"] == proc.pid, result
        assert result["cwd"] == str(fixture.exe.parent), result
        assert result["argv"][2:] == [str(fixture.exe)] + fixture.profile.arguments, result
        assert result["ld"] == original_ld and result["qt"] == original_qt, result
        subprocess.run([str(installed), "uninstall", "--yes"], env=env, check=True, timeout=60)
        assert not installed.exists()
        assert ProfileStore(fixture.paths).get(fixture.profile.id) == fixture.profile
        print(f"Archive check passed: GUI={args.platform}, install/update/uninstall, frozen wrapper + environment")
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
