from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .keyvalues import Document, KeyValuesError
from .storage import LaunchError


def read_vdf(path: Path) -> Document:
    try:
        return Document(path.read_bytes().decode("utf-8"))
    except (UnicodeError, KeyValuesError) as error:
        raise LaunchError(f"Не удалось прочитать VDF: {path}: {error}") from error


def detect_steam() -> Path | None:
    candidates = [Path.home() / ".steam/root", Path.home() / ".steam/steam",
                  Path.home() / ".local/share/Steam"]
    if os.environ.get("XDG_DATA_HOME"):
        candidates.insert(0, Path(os.environ["XDG_DATA_HOME"]) / "Steam")
    for path in candidates:
        if (path / "steamapps/libraryfolders.vdf").is_file():
            return path.resolve()
    return None


@dataclass(frozen=True)
class Game:
    appid: int
    name: str
    directory: Path


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    recent: bool = False


def accounts(root: Path) -> list[Account]:
    metadata: dict[str, tuple[str, bool]] = {}
    login = root / "config/loginusers.vdf"
    if login.is_file():
        users = read_vdf(login).get(["users"])
        for node in (users.children or []) if users else []:
            if node.key.value.isdecimal():
                account_id = int(node.key.value) - 76561197960265728
                metadata[str(account_id)] = (node.string("PersonaName", str(account_id)),
                                             node.string("MostRecent") == "1")
    result = []
    userdata = root / "userdata"
    if userdata.is_dir():
        for path in userdata.iterdir():
            if path.name.isdecimal() and (path / "config/localconfig.vdf").is_file():
                name, recent = metadata.get(path.name, (f"Аккаунт {path.name}", False))
                result.append(Account(path.name, name, recent))
    return sorted(result, key=lambda account: (not account.recent, account.name.casefold()))


def installed_games(root: Path) -> tuple[list[Game], list[str]]:
    libraries = [root.resolve()]
    data = read_vdf(root / "steamapps/libraryfolders.vdf").get(["libraryfolders"])
    for node in (data.children or []) if data else []:
        if node.children is not None:
            value = node.string("path")
        else:
            value = node.value.value if node.value and node.key.value.isdecimal() else ""
        if value and Path(value).is_absolute():
            path = Path(value).resolve()
            if path not in libraries:
                libraries.append(path)
    result: dict[int, Game] = {}
    warnings: list[str] = []
    for library in libraries:
        steamapps = library / "steamapps"
        if not steamapps.is_dir():
            warnings.append(f"Библиотека недоступна: {library}")
            continue
        for manifest in sorted(steamapps.glob("appmanifest_*.acf")):
            try:
                app = read_vdf(manifest).get(["AppState"])
                if not app:
                    raise ValueError("Отсутствует AppState")
                appid = int(app.string("appid"))
                if not int(app.string("StateFlags", "0")) & 4:
                    continue
                name = app.string("name", str(appid))
                directory = (steamapps / "common" / app.string("installdir")).resolve()
                if not directory.is_relative_to((steamapps / "common").resolve()):
                    raise ValueError("Некорректный installdir")
                if not directory.is_dir():
                    continue
                if (name.startswith(("Steam Linux Runtime", "Steamworks Common",
                                     "Proton ", "Proton-", "Legacy Steam Runtime"))
                        or name in {"Proton Experimental", "Steam Controller Configs"}):
                    continue
                result[appid] = Game(appid, name, directory)
            except (OSError, ValueError, LaunchError) as error:
                warnings.append(f"{manifest.name}: {error}")
    return sorted(result.values(), key=lambda game: game.name.casefold()), warnings


def steam_running(proc: Path = Path("/proc")) -> bool:
    try:
        entries = list(proc.iterdir())
    except OSError as error:
        raise LaunchError("Не удалось проверить процессы Steam. Запись запрещена.") from error
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            if entry.stat().st_uid == os.getuid():
                if (entry / "comm").read_text().strip().casefold() in {"steam", "steam.exe"}:
                    return True
        except FileNotFoundError:
            continue
        except PermissionError as error:
            # A process owned by another user cannot be our Steam client.
            try:
                if entry.stat().st_uid != os.getuid():
                    continue
            except FileNotFoundError:
                continue
            raise LaunchError("Недостаточно прав для проверки процессов Steam") from error
    return False


def require_steam_stopped() -> None:
    if steam_running():
        raise LaunchError("Полностью закрой Steam через «Steam → Выход» и повтори. "
                          "Закрыть только окно недостаточно. SteamLaunch не завершает Steam сам.")
