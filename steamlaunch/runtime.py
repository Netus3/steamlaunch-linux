"""Source/frozen entry points and the boundary between bundled Qt and Steam."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

QT_ENV_KEYS = ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH",
               "QML_IMPORT_PATH", "QT_QPA_PLATFORM")
QT_SNAPSHOT = "_STEAMLAUNCH_QT_ENV"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def external_environment(environment: dict[str, str] | None = None) -> dict[str, str]:
    """Undo PyInstaller's library search paths, not Steam's overlay/session env."""
    env = dict(os.environ if environment is None else environment)
    if frozen():
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
    if frozen() or QT_SNAPSHOT in env:
        snapshot = json.loads(env.pop(QT_SNAPSHOT, "{}"))
        for key in QT_ENV_KEYS:
            value = snapshot.get(key)
            if isinstance(value, str):
                env[key] = value
            else:
                env.pop(key, None)
    return env


def launcher_command() -> list[str]:
    if not frozen():
        # Resolving this symlink would discard a source install's virtualenv.
        return [str(Path(sys.executable).absolute()), "-I", "-m", "steamlaunch"]
    from .installation import install_root, is_managed
    bundle = Path(sys.executable).parent.resolve()
    root = install_root()
    if is_managed(root) and bundle.is_relative_to((root / "versions").resolve()):
        return [str(root / "SteamLaunch")]
    return [str(Path(sys.executable).absolute())]


def configure_display(backend: str = "auto") -> None:
    if QT_SNAPSHOT not in os.environ:
        os.environ[QT_SNAPSHOT] = json.dumps({key: os.environ[key] for key in QT_ENV_KEYS
                                             if key in os.environ})
    if backend == "x11":
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    elif backend == "wayland":
        os.environ["QT_QPA_PLATFORM"] = "wayland"
    elif not os.environ.get("QT_QPA_PLATFORM"):
        if os.environ.get("WAYLAND_DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"
        elif os.environ.get("DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "xcb"


def asset(name: str) -> Path:
    return Path(__file__).parent / "assets" / name
