"""Explicit, per-user installation. Never edits Steam or deletes user profiles."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import uuid
from pathlib import Path

from .storage import LaunchError, Paths, atomic_write, file_lock, write_json, xdg_path

APP_ID = "steamlaunch-linux"


def install_root() -> Path:
    return xdg_path("XDG_DATA_HOME", "~/.local/share") / "steamlaunch"


def is_managed(root: Path) -> bool:
    try:
        value = json.loads((root / "installation.json").read_text())
        return isinstance(value, dict) and value.get("app") == APP_ID
    except (OSError, ValueError):
        return False


def desktop_argument(value: str) -> str:
    # Desktop Entry escaping is NOT shell quoting: %, $, ` and backslashes have
    # their own rules, including the general string-unescape pass before Exec.
    escaped = value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("$", "\\$").replace("`", "\\`")
    return '"' + escaped.replace("\\", "\\\\") + '"'


def desktop_file(root: Path) -> bytes:
    icon = root / "current/_internal/steamlaunch/assets/steamlaunch.svg"
    return ("[Desktop Entry]\nType=Application\nVersion=1.0\nName=SteamLaunch\n"
            "Comment=Custom Steam and Proton launch profiles\n"
            f"Exec={desktop_argument(str(root / 'SteamLaunch'))} gui\n"
            f"Icon={str(icon).replace(chr(92), chr(92) * 2)}\n"
            "Terminal=false\nCategories=Game;\nStartupNotify=true\n"
            "X-SteamLaunch-Managed=true\n").encode()


def _locations() -> tuple[Path, Path, Path]:
    data = xdg_path("XDG_DATA_HOME", "~/.local/share")
    return install_root(), data / "applications/steamlaunch.desktop", Path.home() / ".local/bin/steamlaunch"


def install_bundle(source: Path | None = None) -> Path:
    from .runtime import frozen
    if source is None and not frozen():
        raise LaunchError("Установка в меню доступна в готовой сборке. Скачай архив из Releases.")
    source = (source or Path(sys.executable).parent).resolve()
    try:
        manifest = json.loads((source / "bundle.json").read_text())
    except (OSError, ValueError) as error:
        raise LaunchError("Не найден манифест готовой сборки bundle.json") from error
    if (not isinstance(manifest, dict) or manifest.get("app") != APP_ID
            or not (source / "SteamLaunch").is_file() or not (source / "_internal").is_dir()):
        raise LaunchError("Это не готовая сборка SteamLaunch")
    root, desktop, link = _locations()
    if root.is_symlink() or root.is_relative_to(source):
        raise LaunchError("Небезопасное расположение папки установки")
    if root.exists() and any(root.iterdir()) and not is_managed(root):
        raise LaunchError(f"Папка занята неизвестными файлами: {root}. Не перезаписываю их.")
    if desktop.exists() and "X-SteamLaunch-Managed=true" not in desktop.read_text():
        raise LaunchError(f"Ярлык уже существует и создан не SteamLaunch: {desktop}")
    if (link.exists() or link.is_symlink()) and not (
            link.is_symlink() and link.readlink() == root / "SteamLaunch"):
        raise LaunchError(f"Не перезаписываю существующую команду {link}")
    with file_lock(root / "install.lock"):
        version = uuid.uuid4().hex  # Never replace libraries used by a running app.
        destination = root / "versions" / version
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, symlinks=True)
        write_json(root / "installation.json", {"version": 1, "app": APP_ID,
                                                "release": manifest.get("version", "unknown")})
        launcher = f"#!/bin/sh\nexec {shlex.quote(str(root / 'current/SteamLaunch'))} \"$@\"\n"
        atomic_write(root / "SteamLaunch", launcher.encode(), 0o755)
        temporary = root / f".current-{version}"
        temporary.symlink_to(Path("versions") / version, target_is_directory=True)
        os.replace(temporary, root / "current")
        atomic_write(desktop, desktop_file(root), 0o644)
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to(root / "SteamLaunch")
    return root


def uninstall_bundle(paths: Paths) -> None:
    from .bindings import Bindings, options_path
    from .steam import read_vdf
    from .storage import ProfileStore
    root, desktop, link = _locations()
    if root.is_symlink() or not is_managed(root):
        raise LaunchError("Управляемая установка SteamLaunch не найдена")
    if Bindings(paths).all():
        raise LaunchError("Сначала восстанови все автоматические привязки в GUI. Профили сохраняются.")
    for profile in ProfileStore(paths).all():
        if profile.config_file.is_file():
            options = read_vdf(profile.config_file).string(options_path(profile.appid)) or ""
            if profile.id in options:
                raise LaunchError("Сначала удали ручные привязки из параметров запуска Steam")
    # Only a positively identified app install is removable; config/state are
    # deliberately outside this tree and are always retained.
    if desktop.is_file() and "X-SteamLaunch-Managed=true" in desktop.read_text():
        desktop.unlink()
    if link.is_symlink() and link.readlink() == root / "SteamLaunch":
        link.unlink()
    shutil.rmtree(root)
