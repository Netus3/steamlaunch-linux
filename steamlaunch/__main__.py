from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .storage import LaunchError, Paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SteamLaunch — профили запуска Steam/Proton")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    gui = commands.add_parser("gui", help="Открыть интерфейс (по умолчанию)")
    gui.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    gui.add_argument("--display-backend", choices=["auto", "x11", "wayland"], default="auto")
    commands.add_parser("doctor", help="Проверить установку без изменения настроек")
    commands.add_parser("install", help="Установить готовую сборку и ярлык без sudo")
    uninstall = commands.add_parser("uninstall", help="Удалить программу, сохранив профили и журналы")
    uninstall.add_argument("--yes", action="store_true", help="Подтвердить удаление программы")
    wrapper = commands.add_parser("wrap", help="Внутренняя обёртка для параметров запуска Steam")
    defaults = Paths.default()
    wrapper.add_argument("--config-dir", type=Path, default=defaults.config)
    wrapper.add_argument("--state-dir", type=Path, default=defaults.state)
    wrapper.add_argument("--profile", required=True)
    wrapper.add_argument("--dry-run", action="store_true")
    wrapper.add_argument("steam_command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "wrap":
        from .wrapper import run_wrapper
        command = args.steam_command
        if command[:1] == ["--"]:
            command = command[1:]
        return run_wrapper(Paths(args.config_dir.absolute(), args.state_dir.absolute()),
                           args.profile, command, args.dry_run)
    try:
        if args.command == "install":
            from .installation import install_bundle
            print(f"Установлено: {install_bundle()}")
            return 0
        if args.command == "uninstall":
            if not args.yes:
                raise LaunchError("Для удаления программы укажи uninstall --yes. Профили останутся.")
            from .installation import uninstall_bundle
            uninstall_bundle(defaults)
            print("Программа удалена. Профили, журналы и резервные копии сохранены.")
            return 0
        if args.command == "doctor":
            from .steam import accounts, detect_steam, installed_games, steam_running
            root = detect_steam()
            print(f"SteamLaunch {__version__}; Python {sys.version.split()[0]}")
            print(f"Steam: {root or 'не найден'}")
            print(f"Клиент работает: {'да' if steam_running() else 'нет'}")
            print(f"Профили: {defaults.config}")
            print(f"Журналы/резервные копии: {defaults.state}")
            if root:
                games, warnings = installed_games(root)
                print(f"Аккаунтов: {len(accounts(root))}; установленных игр: {len(games)}")
                for warning in warnings:
                    print(f"Предупреждение: {warning}")
            return 0 if root else 1
        try:
            from .runtime import configure_display
            configure_display(getattr(args, "display_backend", "auto"))
            from .gui import run_gui
        except ImportError as error:
            print("Не удалось загрузить GUI. Установи зависимости: "
                  ".venv/bin/python -m pip install -e .", file=sys.stderr)
            print(str(error), file=sys.stderr)
            return 1
        return run_gui(defaults, getattr(args, "smoke_test", False))
    except (LaunchError, OSError, ValueError) as error:
        print(f"SteamLaunch: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
