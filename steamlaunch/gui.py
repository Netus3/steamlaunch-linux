from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from . import __version__
from .bindings import Bindings, launch_options, options_path
from .steam import accounts, detect_steam, installed_games, read_vdf, require_steam_stopped
from .storage import LaunchError, Paths, Profile, ProfileStore
from .runtime import external_environment, asset


class MainWindow(QMainWindow):
    def __init__(self, paths: Paths):
        super().__init__()
        self.paths = paths
        self.store = ProfileStore(paths)
        self.bindings = Bindings(paths)
        self.current = Profile()
        self.saved = False
        self.dirty = False
        self.loading = True
        self.startup_errors: list[str] = []
        self.setWindowTitle(f"SteamLaunch {__version__}")
        self.resize(1060, 770)
        self.setMinimumSize(820, 650)
        self._build()
        try:
            profiles = self.store.all()
            self._populate(profiles)
            self._load(profiles[0] if profiles else None)
        except (OSError, ValueError, LaunchError) as error:
            self.startup_errors.append(str(error))
            self._load(None)
            self.banner.setText(f"Ошибка загрузки: {error}")
        self.loading = False

    def _button(self, text: str, action: Callable) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(lambda: self.perform(action))
        return button

    def _build(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("SteamLaunch  ·  Linux / Proton")
        title.setStyleSheet("font-size: 23px; font-weight: 600;")
        layout.addWidget(title)
        subtitle = QLabel("Другой EXE — в контексте установленной игры Steam")
        layout.addWidget(subtitle)
        self.banner = QLabel("Выбери Proton в свойствах игры Steam. Автопривязка — только при закрытом Steam.")
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.TextFormat.PlainText)
        self.banner.setStyleSheet("padding: 10px; background: palette(alternate-base); border-radius: 5px;")
        layout.addWidget(self.banner)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.addWidget(QLabel("ПРОФИЛИ"))
        self.profiles = QListWidget()
        self.profiles.currentItemChanged.connect(self._selection_changed)
        left_layout.addWidget(self.profiles)
        left_buttons = QHBoxLayout()
        left_buttons.addWidget(self._button("Новый", self.new_profile))
        left_buttons.addWidget(self._button("Удалить", self.delete_profile))
        left_layout.addLayout(left_buttons)
        splitter.addWidget(left)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        right = QWidget()
        form_layout = QVBoxLayout(right)
        form_layout.setContentsMargins(10, 0, 0, 0)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(12)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Например, Fallout — альтернативная сборка")
        form.addRow("Название", self.name)
        self.root = QLineEdit()
        form.addRow("Папка Steam", self._path_row(self.root, self.choose_root, "Обзор…"))
        self.account = QComboBox()
        form.addRow("Аккаунт", self.account)
        self.game = QComboBox()
        self.game.setMinimumContentsLength(24)
        form.addRow("Игра Steam", self.game)
        form.addRow("", self._button("Обновить список игр и аккаунтов", self.rescan))
        self.exe = QLineEdit()
        self.exe.setPlaceholderText("/путь/к/игре/Game.exe")
        form.addRow("Windows EXE", self._path_row(self.exe, self.choose_exe, "Выбрать…"))
        self.workdir = QLineEdit()
        self.workdir.setPlaceholderText("По умолчанию — папка EXE")
        form.addRow("Рабочая папка", self._path_row(self.workdir, self.choose_workdir, "Обзор…"))
        self.arguments = QLineEdit()
        self.arguments.setPlaceholderText('-windowed --language "Russian"')
        form.addRow("Аргументы", self.arguments)
        self.inherit = QCheckBox("Сохранить игровые аргументы исходной команды Steam")
        self.inherit.setToolTip("По умолчанию исходные аргументы EXE отбрасываются. "
                                "Параметры самого Proton/runtime сохраняются всегда.")
        form.addRow("", self.inherit)
        self.proton_log = QCheckBox("Подробный Proton log (может занимать много места)")
        form.addRow("", self.proton_log)
        form_layout.addLayout(form)

        notice = QLabel("Используется существующий Proton-префикс выбранной игры: "
                        "EXE может изменить его зависимости и сохранения. "
                        "Overlay и учёт часов требуют проверки в игре; достижения автоматически не добавляются.")
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #bc8b32; padding-top: 8px; padding-bottom: 8px;")
        form_layout.addWidget(notice)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form_layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Сохранить профиль", self.save_profile))
        actions.addWidget(self._button("Привязать к Steam", self.apply_binding))
        actions.addWidget(self._button("Восстановить", self.restore_binding))
        form_layout.addLayout(actions)
        launch = self._button("▶  Запустить через Steam", self.launch)
        launch.setMinimumHeight(42)
        form_layout.addWidget(launch)
        tools = QHBoxLayout()
        tools.addWidget(self._button("Инструкция / строка запуска", self.instructions))
        tools.addWidget(self._button("Журнал запуска", self.show_log))
        form_layout.addWidget(self._button("Установить / обновить для текущего пользователя", self.install_menu))
        form_layout.addLayout(tools)
        form_layout.addStretch()
        scroll.setWidget(right)
        splitter.addWidget(scroll)
        splitter.setSizes([240, 760])
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        footer = QLabel("Ничего не меняется в Steam до подтверждения привязки. "
                        "Не перемещай приложение, пока есть активные привязки.")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        self.setCentralWidget(central)
        for edit in (self.name, self.root, self.exe, self.workdir, self.arguments):
            edit.textChanged.connect(self._changed)
        for combo in (self.account, self.game):
            combo.currentIndexChanged.connect(self._changed)
        self.game.currentIndexChanged.connect(self._game_changed)
        self.inherit.toggled.connect(self._changed)
        self.proton_log.toggled.connect(self._changed)

    def _path_row(self, edit: QLineEdit, action: Callable, label: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(self._button(label, action))
        return row

    def perform(self, action: Callable) -> None:
        try:
            action()
        except (LaunchError, OSError, ValueError) as error:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle("SteamLaunch")
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(str(error))
            dialog.exec()

    def _changed(self, *_args) -> None:
        if not self.loading:
            self.dirty = True
            self.status.setText("Есть несохранённые изменения. Запуск использует сохранённый профиль.")

    def _game_changed(self, *_args) -> None:
        if not self.loading and not self.name.text().strip() and self.game.currentData():
            self.name.setText(self.game.currentText().rsplit("  [", 1)[0])

    def _populate(self, profiles: list[Profile], selected: str | None = None) -> None:
        self.profiles.blockSignals(True)
        self.profiles.clear()
        for profile in sorted(profiles, key=lambda p: p.name.casefold()):
            item = QListWidgetItem(profile.name)
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            item.setToolTip(f"AppID {profile.appid}\n{profile.executable}")
            self.profiles.addItem(item)
            if profile.id == selected:
                self.profiles.setCurrentItem(item)
        self.profiles.blockSignals(False)

    def _load(self, profile: Profile | None) -> None:
        self.loading = True
        self.current = profile or Profile(steam_root=str(detect_steam() or ""))
        self.saved = profile is not None
        self.name.setText(self.current.name)
        self.root.setText(self.current.steam_root)
        self.exe.setText(self.current.executable)
        self.workdir.setText(self.current.workdir)
        self.arguments.setText(shlex.join(self.current.arguments))
        self.inherit.setChecked(self.current.inherit_arguments)
        self.proton_log.setChecked(self.current.proton_log)
        try:
            self._scan(self.current.account_id, self.current.appid)
        except (OSError, ValueError, LaunchError) as error:
            self.account.clear()
            self.game.clear()
            self.banner.setText(str(error))
        try:
            self._populate(self.store.all(), self.current.id if self.saved else None)
        except (OSError, ValueError, LaunchError) as error:
            self._populate([])
            self.banner.setText(f"Не удалось прочитать профили: {error}")
        self.loading = False
        self.dirty = False
        self._status()

    def _scan(self, account_id: str | None = None, appid: int | None = None) -> None:
        if not self.root.text().strip():
            raise LaunchError("Steam не найден. Выбери его папку: в ней должны быть steamapps и userdata.")
        root = Path(self.root.text().strip()).expanduser().resolve()
        found_accounts = accounts(root)
        games, warnings = installed_games(root)
        self.account.blockSignals(True)
        self.game.blockSignals(True)
        self.account.clear()
        self.game.clear()
        for account in found_accounts:
            self.account.addItem(f"{account.name}  [{account.id}]", account.id)
        for game in games:
            self.game.addItem(f"{game.name}  [{game.appid}]", game.appid)
        for combo, value in ((self.account, account_id), (self.game, appid)):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        if account_id and self.account.findData(account_id) < 0:
            self.account.addItem(f"Аккаунт недоступен [{account_id}]", account_id)
            self.account.setCurrentIndex(self.account.count() - 1)
        if appid and self.game.findData(appid) < 0:
            self.game.addItem(f"Игра недоступна [{appid}]", appid)
            self.game.setCurrentIndex(self.game.count() - 1)
        self.account.blockSignals(False)
        self.game.blockSignals(False)
        message = f"Найдено игр: {len(games)}, аккаунтов: {len(found_accounts)}. "
        message += "Принудительно выбери Proton в свойствах игры Steam."
        if warnings:
            message += "\n" + "\n".join(warnings[:3])
        self.banner.setText(message)

    def rescan(self) -> None:
        self._scan(self.account.currentData(), self.game.currentData())
        self._changed()

    def _status(self) -> None:
        if not self.saved:
            self.status.setText("Новый профиль. Сохрани его перед настройкой запуска.")
            return
        try:
            self.status.setText(self.bindings.status(self.current))
        except (OSError, ValueError, LaunchError) as error:
            self.status.setText(f"Не удалось проверить привязку: {error}")

    def _ask_unsaved(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, "Несохранённый профиль", "Сохранить изменения профиля?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            self.save_profile()
        return True

    def _selection_changed(self, item: QListWidgetItem | None, _previous) -> None:
        if self.loading or item is None:
            return
        requested = item.data(Qt.ItemDataRole.UserRole)
        if self.saved and requested == self.current.id:
            return
        try:
            if self._ask_unsaved():
                self._load(self.store.get(requested))
                return
        except (LaunchError, OSError, ValueError) as error:
            self.perform(lambda error=error: self._raise(error))
        self.profiles.blockSignals(True)
        row = -1
        if self.saved:
            for index in range(self.profiles.count()):
                if self.profiles.item(index).data(Qt.ItemDataRole.UserRole) == self.current.id:
                    row = index
                    break
        self.profiles.setCurrentRow(row)
        self.profiles.blockSignals(False)

    @staticmethod
    def _raise(error: Exception) -> None:
        raise error

    def new_profile(self) -> None:
        if self._ask_unsaved():
            self._load(None)

    def _form_profile(self) -> Profile:
        try:
            arguments = shlex.split(self.arguments.text())
        except ValueError as error:
            raise LaunchError(f"Проверь кавычки аргументов: {error}") from error
        if not self.root.text().strip() or not self.exe.text().strip():
            raise LaunchError("Укажи папку Steam и Windows EXE")
        return Profile(id=self.current.id, name=self.name.text().strip(),
                       appid=self.game.currentData() or 0,
                       steam_root=str(Path(self.root.text().strip()).expanduser().resolve()),
                       account_id=self.account.currentData() or "",
                       executable=str(Path(self.exe.text().strip()).expanduser().absolute()),
                       workdir=str(Path(self.workdir.text().strip()).expanduser().absolute())
                       if self.workdir.text().strip() else "",
                       arguments=arguments, inherit_arguments=self.inherit.isChecked(),
                       proton_log=self.proton_log.isChecked())

    def save_profile(self) -> Profile:
        profile = self._form_profile()
        profile.validate()
        self.bindings.check_identity(profile)
        self.store.save(profile)
        self.current, self.saved, self.dirty = profile, True, False
        self._populate(self.store.all(), profile.id)
        self._status()
        return profile

    def _ensure_saved(self) -> Profile:
        return self.save_profile() if self.dirty or not self.saved else self.store.get(self.current.id)

    def delete_profile(self) -> None:
        if not self.saved:
            self.new_profile()
            return
        if self.bindings.for_profile(self.current.id):
            raise LaunchError("Сначала восстанови исходный запуск. "
                              "Нельзя удалять профиль с автоматической привязкой.")
        profile = self.store.get(self.current.id)
        actual = read_vdf(profile.config_file).string(options_path(profile.appid))
        if actual and profile.id in actual:
            raise LaunchError("В Steam осталась ручная привязка к этому профилю. Сначала убери её.")
        if QMessageBox.question(self, "Удалить профиль", f"Удалить «{profile.name}»?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(profile.id)
        self._load(None)

    def choose_root(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Папка Steam", self.root.text())
        if value:
            self.root.setText(value)
            self.rescan()

    def choose_exe(self) -> None:
        value, _ = QFileDialog.getOpenFileName(self, "Windows EXE", self.exe.text(),
                                               "Windows EXE (*.exe *.EXE);;Все файлы (*)")
        if value:
            self.exe.setText(value)
            if not self.name.text().strip():
                self.name.setText(Path(value).stem)

    def choose_workdir(self) -> None:
        start = self.workdir.text() or str(Path(self.exe.text()).parent)
        value = QFileDialog.getExistingDirectory(self, "Рабочая папка игры", start)
        if value:
            self.workdir.setText(value)

    def apply_binding(self) -> None:
        profile = self._ensure_saved()
        require_steam_stopped()
        old = read_vdf(profile.config_file).string(options_path(profile.appid))
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Привязать профиль к Steam")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"Изменить параметры запуска AppID {profile.appid}?\n\n"
                       "Старая строка будет сохранена, но не будет исполняться вместе с новой. "
                       "EXE будет использовать существующий Proton-префикс этой игры "
                       "и может изменить его сохранения/зависимости.\n\n"
                       "Откат привязки возвращает только параметры запуска.")
        dialog.setDetailedText("Текущие параметры:\n" + (old if old is not None else "(отсутствуют)")
                               + "\n\nНовые параметры:\n" + launch_options(profile, self.paths))
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec() == QMessageBox.StandardButton.Yes:
            self.bindings.apply(profile)
            self._status()
            self.banner.setText("Привязка сохранена. Запусти Steam и проверь запуск, Shift+Tab и учёт времени.")

    def restore_binding(self) -> None:
        if not self.saved:
            raise LaunchError("Выбери сохранённый профиль")
        require_steam_stopped()
        if not self.bindings.for_profile(self.current.id):
            raise LaunchError("Нет автоматической привязки. Ручные параметры меняются в Steam.")
        answer = QMessageBox.question(
            self, "Восстановить запуск", "Вернуть прежние параметры запуска Steam?\n"
            "Файлы префикса и сохранения не откатываются.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.bindings.restore(self.current.id)
            self._status()
            self.banner.setText("Исходные параметры запуска восстановлены.")

    def launch(self) -> None:
        profile = self._ensure_saved()
        profile.validate()
        current = read_vdf(profile.config_file).string(options_path(profile.appid))
        if current != launch_options(profile, self.paths):
            raise LaunchError("Сначала привяжи профиль к Steam или вставь сгенерированную строку "
                              "в параметры запуска игры вручную.")
        executable = shutil.which("steam")
        if not executable:
            raise LaunchError("Команда steam не найдена в PATH")
        subprocess.Popen([executable, f"steam://rungameid/{profile.appid}"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, env=external_environment())
        self.banner.setText("Запрос запуска отправлен Steam. При ошибке открой «Журнал запуска».")

    def instructions(self) -> None:
        profile = self._ensure_saved()
        options = launch_options(profile, self.paths)
        entry = self.bindings.for_profile(profile.id)
        previous = (entry["previous"] if entry else
                    read_vdf(profile.config_file).string(options_path(profile.appid)))
        text = (f"AppID: {profile.appid}\nПрофиль: {profile.name}\n\n"
                "В свойствах игры Steam включи принудительное использование Proton и Overlay.\n"
                "Для автопривязки полностью выйди из Steam и нажми «Привязать к Steam».\n"
                "Для ручного способа вставь следующую строку в «Параметры запуска»:\n\n"
                f"{options}\n\n"
                + ("Сохранённые исходные параметры:\n" if entry else
                   "Текущие параметры (сохрани перед ручной заменой):\n")
                + (previous if previous is not None else "(поле отсутствует — для отмены очисти его)")
                + "\n\nПри ручной привязке журнал восстановления не создаётся. "
                "Отмена — вернуть старую строку через свойства игры Steam.\n\n"
                "Используется существующий префикс игры; его файлы не откатываются. "
                "Не удаляй и не перемещай приложение до отмены привязки.\n\n"
                f"Профили: {self.paths.config}\nЖурналы и копии: {self.paths.state}")
        self._text_dialog("Инструкция и параметры запуска", text, options)

    def show_log(self) -> None:
        path = self.paths.log_file(self.current.id)
        if not path.is_file():
            self._text_dialog("Журнал запуска", "Журнал ещё не создан.\n"
                              "Он появится после запуска обёртки через Steam.\n\n" + str(path))
            return
        with path.open("rb") as stream:
            stream.seek(0, 2)
            truncated = stream.tell() > 128 * 1024
            stream.seek(max(0, stream.tell() - 128 * 1024))
            text = stream.read().decode("utf-8", errors="replace")
        prefix = f"{path}\nНе публикуй лог без проверки: в нём есть пути и аргументы.\n\n"
        if truncated:
            prefix += "[Показаны последние 128 КиБ]\n"
        self._text_dialog("Журнал запуска", prefix + text)

    def install_menu(self) -> None:
        from .installation import install_bundle
        answer = QMessageBox.question(self, "Установка SteamLaunch",
                                      "Установить эту сборку в постоянную пользовательскую папку "
                                      "и добавить ярлык? Steam и профили не изменятся.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            root = install_bundle()
            self.banner.setText(f"Установлено в {root}. Перезапусти программу из меню приложений. "
                                "Существующие привязки при необходимости обнови кнопкой «Привязать к Steam».")

    def _text_dialog(self, title: str, text: str, copy: str | None = None) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(820, 540)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        if copy is not None:
            button = buttons.addButton("Копировать строку запуска", QDialogButtonBox.ButtonRole.ActionRole)
            button.clicked.connect(lambda: QApplication.clipboard().setText(copy))
        layout.addWidget(buttons)
        dialog.exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        try:
            if self._ask_unsaved():
                event.accept()
            else:
                event.ignore()
        except (LaunchError, OSError, ValueError) as error:
            self.perform(lambda error=error: self._raise(error))
            event.ignore()


def run_gui(paths: Paths, smoke_test: bool = False) -> int:
    app = QApplication([sys.argv[0]])
    app.setApplicationName("SteamLaunch")
    app.setOrganizationName("SteamLaunch")
    app.setWindowIcon(QIcon(str(asset("steamlaunch.svg"))))
    if QStandardPaths.locate(QStandardPaths.StandardLocation.ApplicationsLocation,
                             "steamlaunch.desktop"):
        app.setDesktopFileName("steamlaunch")
    window = MainWindow(paths)
    window.show()
    if smoke_test:
        for message in window.startup_errors:
            print(message, file=sys.stderr)
        QTimer.singleShot(200, app.quit)
    result = app.exec()
    return 1 if smoke_test and window.startup_errors else result
