from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterator
import uuid


class LaunchError(Exception):
    """An actionable error that is safe to display in the GUI."""


def private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    private_dir(path.parent)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (ValueError, UnicodeError) as error:
        raise LaunchError(f"Повреждён файл {path}. Не перезаписываю его.") from error
    if not isinstance(data, dict) or data.get("version") != 1:
        raise LaunchError(f"Неподдерживаемый формат: {path}")
    return data


def write_json(path: Path, data: dict) -> None:
    atomic_write(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    private_dir(path.parent)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def xdg_path(variable: str, fallback: str) -> Path:
    value = Path(os.environ.get(variable, fallback)).expanduser()
    return value if value.is_absolute() else Path(fallback).expanduser()


@dataclass(frozen=True)
class Paths:
    config: Path
    state: Path

    @classmethod
    def default(cls) -> Paths:
        return cls(xdg_path("XDG_CONFIG_HOME", "~/.config") / "steamlaunch",
                   xdg_path("XDG_STATE_HOME", "~/.local/state") / "steamlaunch")

    def log_file(self, profile_id: str) -> Path:
        check_id(profile_id)
        return self.state / "logs" / f"{profile_id}.log"


def check_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise LaunchError("Некорректный ID профиля")


@dataclass
class Profile:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    appid: int = 0
    steam_root: str = ""
    account_id: str = ""
    executable: str = ""
    workdir: str = ""
    arguments: list[str] = field(default_factory=list)
    inherit_arguments: bool = False
    proton_log: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        try:
            result = cls(**data)
            result.validate(check_files=False)
        except (TypeError, ValueError) as error:
            raise LaunchError("Некорректный профиль в profiles.json") from error
        return result

    @property
    def directory(self) -> Path:
        return Path(self.workdir) if self.workdir else Path(self.executable).parent

    @property
    def config_file(self) -> Path:
        return Path(self.steam_root) / "userdata" / self.account_id / "config/localconfig.vdf"

    def validate(self, check_files: bool = True) -> None:
        check_id(self.id)
        for value in (self.name, self.steam_root, self.account_id, self.executable, self.workdir):
            if not isinstance(value, str) or "\0" in value or "\n" in value or "\r" in value:
                raise LaunchError("Некорректная строка в профиле")
        if not self.name.strip():
            raise LaunchError("Укажи название профиля")
        if type(self.appid) is not int or not 0 < self.appid < 2**32:
            raise LaunchError("Выбери игру Steam")
        if not re.fullmatch(r"[0-9]{1,20}", self.account_id):
            raise LaunchError("Выбери аккаунт Steam")
        for value in (self.steam_root, self.executable):
            if not Path(value).is_absolute():
                raise LaunchError("Пути Steam и EXE должны быть абсолютными")
        if self.workdir and not Path(self.workdir).is_absolute():
            raise LaunchError("Рабочая папка должна иметь абсолютный путь")
        if Path(self.executable).suffix.casefold() != ".exe":
            raise LaunchError("Для этой версии выбери Windows-файл .exe")
        if not isinstance(self.arguments, list) or any(
                not isinstance(arg, str) or "\0" in arg for arg in self.arguments):
            raise LaunchError("Некорректные аргументы запуска")
        if type(self.inherit_arguments) is not bool or type(self.proton_log) is not bool:
            raise LaunchError("Некорректные переключатели профиля")
        if check_files:
            if not Path(self.executable).is_file():
                raise LaunchError(f"EXE не найден: {self.executable}")
            if not self.directory.is_dir():
                raise LaunchError(f"Рабочая папка не найдена: {self.directory}")
            if not self.config_file.is_file():
                raise LaunchError(f"Конфигурация аккаунта не найдена: {self.config_file}")


class ProfileStore:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.file = paths.config / "profiles.json"

    def all(self) -> list[Profile]:
        data = read_json(self.file, {"version": 1, "profiles": []})
        if not isinstance(data.get("profiles"), list):
            raise LaunchError(f"Некорректный список профилей: {self.file}")
        profiles = [Profile.from_dict(item) for item in data["profiles"]]
        if len({p.id for p in profiles}) != len(profiles):
            raise LaunchError("Повторяющиеся ID в profiles.json")
        return profiles

    def get(self, profile_id: str) -> Profile:
        check_id(profile_id)
        for profile in self.all():
            if profile.id == profile_id:
                return profile
        raise LaunchError("Профиль не найден. Открой SteamLaunch и восстанови привязку.")

    def save(self, profile: Profile) -> None:
        profile.validate()
        with file_lock(self.paths.config / "profiles.lock"):
            profiles = self.all()
            profiles = [p for p in profiles if p.id != profile.id] + [profile]
            write_json(self.file, {"version": 1, "profiles": [asdict(p) for p in profiles]})

    def delete(self, profile_id: str) -> None:
        check_id(profile_id)
        with file_lock(self.paths.config / "profiles.lock"):
            profiles = [p for p in self.all() if p.id != profile_id]
            write_json(self.file, {"version": 1, "profiles": [asdict(p) for p in profiles]})
