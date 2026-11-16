"""Reversible LaunchOptions edits with an on-disk recovery journal."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shlex
import stat
import uuid

from .keyvalues import Document, KeyValuesError
from .runtime import launcher_command
from .steam import require_steam_stopped
from .storage import (LaunchError, Paths, Profile, atomic_write, file_lock,
                      check_id, read_json, write_json)


def options_path(appid: int) -> list[str]:
    return ["UserLocalConfigStore", "Software", "Valve", "Steam", "apps",
            str(appid), "LaunchOptions"]


def launch_options(profile: Profile, paths: Paths) -> str:
    command = launcher_command() + ["wrap",
                                          "--config-dir", str(paths.config.absolute()),
                                          "--state-dir", str(paths.state.absolute()),
                                          "--profile", profile.id, "--"]
    if any("%command%" in arg or "\n" in arg or "\r" in arg for arg in command):
        raise LaunchError("Путь установки содержит неподдерживаемый символ")
    return shlex.join(command) + " %command%"


def binding_key(profile: Profile) -> str:
    value = f"{Path(profile.steam_root).resolve()}\0{profile.account_id}\0{profile.appid}"
    return hashlib.sha256(value.encode()).hexdigest()


def _read_config(path: Path) -> tuple[bytes, Document, int]:
    if path.is_symlink():
        raise LaunchError("localconfig.vdf — символическая ссылка. "
                          "Используй ручную вставку параметров запуска.")
    data = path.read_bytes()
    try:
        document = Document(data.decode("utf-8"))
        if document.get(["UserLocalConfigStore"]) is None:
            raise KeyValuesError("Отсутствует UserLocalConfigStore")
    except (UnicodeError, KeyValuesError) as error:
        raise LaunchError(f"Нельзя безопасно изменить {path}: {error}") from error
    return data, document, stat.S_IMODE(path.stat().st_mode)


class Bindings:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.file = paths.state / "bindings.json"

    def all(self) -> dict[str, dict]:
        data = read_json(self.file, {"version": 1, "bindings": {}})
        entries = data.get("bindings")
        if not isinstance(entries, dict):
            raise LaunchError("Некорректный журнал привязок. Не изменяю Steam.")
        required = {"profile_id", "appid", "account_id", "steam_root", "previous",
                    "applied", "phase", "backup"}
        for key, entry in entries.items():
            if (not isinstance(entry, dict) or not required.issubset(entry)
                    or not isinstance(entry["applied"], str)
                    or (entry["previous"] is not None and not isinstance(entry["previous"], str))
                    or not isinstance(entry["phase"], str)
                    or entry["phase"] not in {"pending", "applied", "restoring"}
                    or any(entry.get(field) is not None and not isinstance(entry[field], str)
                           for field in ("pending_from", "restore_from"))):
                raise LaunchError("Повреждён журнал привязок. Не изменяю Steam.")
            check_id(entry["profile_id"])
            if (type(entry["appid"]) is not int or not 0 < entry["appid"] < 2**32
                    or not isinstance(entry["account_id"], str)
                    or not re.fullmatch(r"[0-9]{1,20}", entry["account_id"])
                    or not isinstance(entry["steam_root"], str)
                    or not Path(entry["steam_root"]).is_absolute()
                    or not isinstance(entry["backup"], str)):
                raise LaunchError("Некорректная цель в журнале привязок. Не изменяю Steam.")
            identity = Profile(appid=entry["appid"], account_id=entry["account_id"],
                               steam_root=entry["steam_root"])
            if key != binding_key(identity):
                raise LaunchError("Некорректный ключ журнала привязок. Не изменяю Steam.")
        return entries

    def _save(self, entries: dict[str, dict]) -> None:
        write_json(self.file, {"version": 1, "bindings": entries})

    def for_profile(self, profile_id: str) -> dict | None:
        entries = [entry for entry in self.all().values() if entry["profile_id"] == profile_id]
        if len(entries) > 1:
            raise LaunchError("Несколько привязок одного профиля. Требуется восстановление журнала.")
        return entries[0] if entries else None

    def check_identity(self, profile: Profile) -> None:
        entry = self.for_profile(profile.id)
        if entry and (entry["appid"] != profile.appid
                      or entry["account_id"] != profile.account_id
                      or Path(entry["steam_root"]).resolve() != Path(profile.steam_root).resolve()):
            raise LaunchError("Сначала восстанови исходный запуск старой игры. "
                              "Нельзя менять игру/аккаунт у действующей привязки.")

    def status(self, profile: Profile) -> str:
        entry = self.for_profile(profile.id)
        if not entry:
            return "Не настроен автоматически"
        path = (Path(entry["steam_root"]) / "userdata" / entry["account_id"]
                / "config/localconfig.vdf")
        _, document, _ = _read_config(path)
        current = document.string(options_path(entry["appid"]))
        if current == entry["applied"]:
            if current != launch_options(profile, self.paths):
                return "Нужно обновить путь запуска: закрой Steam и нажми «Привязать к Steam»"
            return "Привязка активна" if entry["phase"] == "applied" else "Привязка требует завершения"
        if current == entry["previous"]:
            return "Исходный запуск восстановлен; очисти запись кнопкой восстановления"
        return "Параметры изменены вне SteamLaunch — автоматическая перезапись запрещена"

    def _backup(self, data: bytes) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.paths.state / "backups" / f"{stamp}-{uuid.uuid4().hex}.vdf"
        atomic_write(path, data)
        return path

    def _write_config(self, path: Path, before: bytes, after: str, mode: int) -> None:
        require_steam_stopped()
        if path.is_symlink() or path.read_bytes() != before:
            raise LaunchError("Конфигурация Steam изменилась во время операции. Запись отменена.")
        # Validate the full edited document before touching Steam's file.
        Document(after)
        atomic_write(path, after.encode("utf-8"), mode)

    def apply(self, profile: Profile) -> None:
        profile.validate()
        options = launch_options(profile, self.paths)
        with file_lock(self.paths.state / "bindings.lock"):
            require_steam_stopped()
            self.check_identity(profile)
            entries = self.all()
            key = binding_key(profile)
            before, document, mode = _read_config(profile.config_file)
            current = document.string(options_path(profile.appid))
            entry = entries.get(key)
            if entry:
                if entry["profile_id"] != profile.id:
                    raise LaunchError("Эта игра уже привязана к другому профилю. Сначала восстанови его.")
                if entry["phase"] == "restoring":
                    raise LaunchError("Предыдущее восстановление прервано. Сначала нажми «Восстановить».")
                allowed = [entry["applied"]]
                if entry["phase"] == "pending":
                    allowed.extend([entry["previous"], entry.get("pending_from")])
                if current not in allowed:
                    raise LaunchError("Параметры запуска изменены вне SteamLaunch. "
                                      "Не перезаписываю их. Проверь настройки Steam.")
                if current == options:
                    entry["phase"] = "applied"
                    self._save(entries)
                    return
            else:
                if current and ("-m steamlaunch wrap" in current
                                or ("SteamLaunch" in current and "--profile" in current)):
                    raise LaunchError("Обнаружена ручная/неизвестная привязка SteamLaunch. "
                                      "Сначала убери её в свойствах игры Steam.")
                entry = {"profile_id": profile.id, "appid": profile.appid,
                         "account_id": profile.account_id, "steam_root": profile.steam_root,
                         "previous": current, "applied": options,
                         "phase": "pending", "backup": str(self._backup(before))}
                entries[key] = entry
            after = document.set_string(options_path(profile.appid), options)
            entry["phase"], entry["applied"] = "pending", options
            entry["pending_from"] = current
            # Journal first: a crash at any following step remains reversible.
            self._save(entries)
            self._write_config(profile.config_file, before, after, mode)
            entry["phase"] = "applied"
            self._save(entries)

    def restore(self, profile_id: str) -> None:
        with file_lock(self.paths.state / "bindings.lock"):
            require_steam_stopped()
            entries = self.all()
            keys = [key for key, entry in entries.items() if entry["profile_id"] == profile_id]
            if not keys:
                raise LaunchError("Нет автоматической привязки. Ручные параметры меняются в Steam.")
            if len(keys) != 1:
                raise LaunchError("Несколько записей привязки. Автоматическое восстановление запрещено.")
            key = keys[0]
            entry = entries[key]
            path = (Path(entry["steam_root"]) / "userdata" / entry["account_id"]
                    / "config/localconfig.vdf")
            before, document, mode = _read_config(path)
            current = document.string(options_path(entry["appid"]))
            if current != entry["previous"]:
                allowed = [entry["applied"]]
                if entry["phase"] == "pending":
                    allowed.append(entry.get("pending_from"))
                elif entry["phase"] == "restoring":
                    allowed.append(entry.get("restore_from", entry["applied"]))
                if current not in allowed:
                    raise LaunchError("Параметры изменены вне SteamLaunch. Не затираю изменения. "
                                      "Верни сохранённую строку вручную в Steam (см. «Инструкция»).")
                after = document.set_string(options_path(entry["appid"]), entry["previous"])
                self._backup(before)
                entry["phase"] = "restoring"
                entry["restore_from"] = current
                self._save(entries)
                self._write_config(path, before, after, mode)
            del entries[key]
            self._save(entries)
