from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .storage import LaunchError, Paths, Profile, ProfileStore, private_dir
from .runtime import external_environment


@dataclass(frozen=True)
class LaunchPlan:
    argv: list[str]
    cwd: Path
    env: dict[str, str]


def replace_executable(command: list[str], profile: Profile) -> list[str]:
    if not command or any("\0" in arg for arg in command):
        raise LaunchError("Steam не передал корректную команду после -- %command%")
    # Do not search for a random .exe: launchers and runtime helpers can also
    # have that extension. Only the documented Proton verb identifies the slot.
    for index in range(len(command) - 1):
        if Path(command[index]).name == "proton" and command[index + 1] in {
                "run", "waitforexitandrun"}:
            target = index + 2
            if target >= len(command) or not command[target]:
                raise LaunchError("В команде Proton отсутствует исходный EXE")
            prefix = command[:target]
            for slot in {0, index}:
                if "/" in prefix[slot] and not Path(prefix[slot]).is_absolute():
                    prefix[slot] = str(Path(prefix[slot]).absolute())
            inherited = command[target + 1:] if profile.inherit_arguments else []
            return prefix + [profile.executable] + inherited + profile.arguments
    raise LaunchError("В команде Steam не найден Proton run/waitforexitandrun. "
                      "В свойствах игры включи «Совместимость → Принудительно использовать…» "
                      "и выбери установленный Proton. Исходная игра не запущена.")


def prepare_launch(profile: Profile, command: list[str], environment: dict[str, str],
                   paths: Paths) -> LaunchPlan:
    profile.validate()
    ids = [environment[key] for key in ("SteamAppId", "SteamGameId") if environment.get(key)]
    if not ids or any(value != str(profile.appid) for value in ids):
        raise LaunchError("AppID окружения Steam не совпадает с профилем. "
                          "Запускай профиль через выбранную игру Steam, а не EXE напрямую.")
    if not environment.get("STEAM_COMPAT_DATA_PATH"):
        raise LaunchError("Steam не передал Proton-префикс (STEAM_COMPAT_DATA_PATH). "
                          "Проверь выбранный инструмент совместимости.")
    client = environment.get("STEAM_COMPAT_CLIENT_INSTALL_PATH")
    if client and Path(client).resolve() != Path(profile.steam_root).resolve():
        raise LaunchError("Профиль настроен для другой установки Steam")
    argv = replace_executable(command, profile)
    env = external_environment(environment)
    mounts = [value for value in env.get("STEAM_COMPAT_MOUNTS", "").split(":") if value]
    directories = [Path(profile.executable).parent, Path(profile.executable).resolve().parent,
                   profile.directory]
    if profile.proton_log:
        log_dir = paths.state / "proton"
        env["PROTON_LOG"] = "1"
        env["PROTON_LOG_DIR"] = str(log_dir)
        directories.append(log_dir)
    for directory in directories:
        # Include lexical and resolved paths so symlinks on external disks work.
        for path in (directory, directory.resolve()):
            value = str(path)
            if ":" in value:
                raise LaunchError("Папка содержит двоеточие: её нельзя безопасно передать "
                                  "в STEAM_COMPAT_MOUNTS. Перемести игру в другой путь.")
            if value not in mounts:
                mounts.append(value)
    env["STEAM_COMPAT_MOUNTS"] = ":".join(mounts)
    env["PWD"] = str(profile.directory)
    return LaunchPlan(argv, profile.directory, env)


def safe_environment(env: dict[str, str]) -> dict[str, str]:
    keys = ("SteamAppId", "SteamGameId", "STEAM_COMPAT_DATA_PATH",
            "STEAM_COMPAT_CLIENT_INSTALL_PATH", "STEAM_COMPAT_INSTALL_PATH",
            "STEAM_COMPAT_MOUNTS", "PROTON_LOG", "PROTON_LOG_DIR",
            "DISPLAY", "WAYLAND_DISPLAY")
    return {key: env[key] for key in keys if key in env}


def notify_error(message: str) -> None:
    executable = shutil.which("notify-send")
    if not executable:
        return
    env = external_environment()
    env.pop("LD_PRELOAD", None)
    try:
        subprocess.run([executable, "--app-name=SteamLaunch", "--icon=dialog-error",
                        "SteamLaunch: запуск отменён", message[:1500]],
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=4, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_wrapper(paths: Paths, profile_id: str, command: list[str], dry_run: bool = False) -> int:
    try:
        log_path = paths.log_file(profile_id)
        if not dry_run:
            private_dir(paths.state)
            private_dir(log_path.parent)
            if log_path.exists() and log_path.stat().st_size > 8 * 1024 * 1024:
                os.replace(log_path, log_path.with_suffix(".previous.log"))
            fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.dup2(fd, 1)
                os.dup2(fd, 2)
            finally:
                if fd not in (1, 2):
                    os.close(fd)
        profile = ProfileStore(paths).get(profile_id)
        plan = prepare_launch(profile, command, dict(os.environ), paths)
        diagnostic = {"time": datetime.now().astimezone().isoformat(), "profile": profile.name,
                      "argv": plan.argv, "cwd": str(plan.cwd),
                      "environment": safe_environment(plan.env)}
        print(json.dumps(diagnostic, ensure_ascii=False, indent=2), flush=True)
        if dry_run:
            return 0
        if profile.proton_log:
            private_dir(Path(plan.env["PROTON_LOG_DIR"]))
        os.chdir(plan.cwd)
        # Keep Steam's process tracking and signal handling; do not daemonize or
        # launch a second, unrelated Proton instance.
        os.execvpe(plan.argv[0], plan.argv, plan.env)
    except (OSError, ValueError, LaunchError) as error:
        message = str(error)
        print(f"SteamLaunch: {message}", file=sys.stderr, flush=True)
        if not dry_run:
            notify_error(message)
        return 1
    return 1
