# One-directory bundle: dynamic LGPL Qt libraries stay replaceable. No onefile
# extraction paths may be persisted in Steam's LaunchOptions.
from pathlib import Path
import json
from PyInstaller.config import CONF
from PySide6.QtCore import QLibraryInfo

root = Path(SPECPATH).parent
plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
binaries = []
for category in ("platforms", "wayland-shell-integration", "wayland-decoration-client",
                 "wayland-graphics-integration-client", "imageformats"):
    for library in (plugins / category).glob("*.so"):
        binaries.append((str(library), f"PySide6/Qt/plugins/{category}"))

a = Analysis(
    [str(root / "packaging/entrypoint.py")],
    pathex=[str(root)], binaries=binaries,
    datas=[(str(root / "steamlaunch/assets"), "steamlaunch/assets")],
    hiddenimports=["steamlaunch.gui"],
    runtime_hooks=[str(root / "packaging/runtime_hook.py")],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter"], noarchive=False,
)
# Qt hooks collect plugins present in the wheel, including optional GPL-only
# VirtualKeyboard and the separately packaged PDF viewer. Neither is used here.
unneeded = ("VirtualKeyboard", "virtualkeyboard", "libqpdf", "libQt6Pdf")
def wanted(entry):
    return not any(part in entry[0] or part in entry[1] for part in unneeded)

a.binaries = [entry for entry in a.binaries if wanted(entry)]
a.datas = [entry for entry in a.datas if wanted(entry)]
Path(CONF["workpath"], "native-origins.json").write_text(json.dumps(
    [{"name": name, "source": source} for name, source, kind in a.binaries
     if kind in {"BINARY", "EXTENSION"}]))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SteamLaunch", console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SteamLaunch")
