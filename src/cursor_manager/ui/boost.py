"""
boost.py — вкладки «FPS буст» и «Лучший сервер».

fps: галочки разрешённых FastFlags, лимит кадров и уровень графики из меню
игры. Запись — только через core.fps, выбор запоминается в core.config, и
LibraryPage.restore_config() ставит флаги заново после обновления Roblox.

сервера: список публичных серверов игры с пингом из core.servers и вход на
выбранный. Это единственное место UI с сетью; запросы идут в фоновом
потоке, а сюда приходят только готовые данные через сигналы.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from cursor_manager.core import cursor_core as core
from cursor_manager.core import fps, pcboost, servers
from cursor_manager.ui.library import LibraryPage


def _label(text: str, obj: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if obj:
        lab.setObjectName(obj)
    lab.setWordWrap(wrap)
    return lab


def _head(lay: QVBoxLayout, title: str, sub: str) -> None:
    lay.addWidget(_label(title, "h1"))
    sub_label = _label(sub, "body", wrap=True)
    sub_label.setMaximumWidth(620)
    lay.addWidget(sub_label)


# ─────────────────────────────────────────────────────────────────────────────
# fps
# ─────────────────────────────────────────────────────────────────────────────
class _State(QObject):
    """Мост из фонового потока: готовый текст состояния fps."""
    ready = Signal(str)


class FpsPage(QWidget):
    def __init__(self, library: LibraryPage, parent=None):
        super().__init__(parent)
        self.library = library
        self.checks: dict[str, QCheckBox] = {}
        # tasklist и чтение настроек — это subprocess и диск; на вкладке они
        # идут в фоне, иначе переключение на неё подвисает на сотни мс
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._bridge = _State(self)
        self._bridge.ready.connect(lambda text: self.state.setText(text))

        # блоков больше, чем влезает в окно 760 px — без прокрутки Qt
        # сплющивал кнопки
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        root = QVBoxLayout(inner)
        root.setContentsMargins(20, 18, 28, 14)
        root.setSpacing(26)
        _head(root, "FPS буст",
              "Только штатные настройки Roblox: разрешённые им FastFlags и "
              "лимит кадров из меню игры. Без инжектов и без риска бана. "
              "Выбор запоминается и возвращается после обновления Roblox.")

        body = QHBoxLayout()
        body.setSpacing(40)

        flags_box = QWidget()
        fl = QVBoxLayout(flags_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(4)
        fl.addWidget(_label("Графика", "rowtitle"))
        for key, opt in fps.FLAG_OPTIONS.items():
            cb = QCheckBox(opt["title"])
            cb.setCursor(Qt.PointingHandCursor)
            self.checks[key] = cb
            fl.addWidget(cb)
            hint = _label(opt["hint"], "faint", wrap=True)
            hint.setContentsMargins(24, 0, 0, 6)
            fl.addWidget(hint)
        fl.addStretch(1)
        body.addWidget(flags_box, 3)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        sl.addWidget(_label("Лимит кадров", "rowtitle"))
        self.cap = QComboBox()
        self.cap.addItem("Не трогать", None)
        for value in fps.FPS_CAPS:
            text = f"{value} fps"
            if value == 5000:
                text = "Без лимита (без гарантий)"
            elif value > 240:
                text += " (без гарантий)"
            self.cap.addItem(text, value)
        sl.addWidget(self.cap)
        sl.addWidget(_label("Официально меню игры даёт до 240; выше Roblox "
                            "не обещает, но обычно слушается", "faint", wrap=True))
        sl.addSpacing(10)
        sl.addWidget(_label("Качество графики", "rowtitle"))
        self.quality = QComboBox()
        self.quality.addItem("Не трогать", None)
        self.quality.addItem("Авто", 0)
        for level in range(1, 11):
            self.quality.addItem(f"{level}" + (" — минимум" if level == 1 else ""), level)
        sl.addWidget(self.quality)
        sl.addWidget(_label("Лимит и качество меняются только при закрытом "
                            "Roblox: он перезаписывает настройки при выходе",
                            "faint", wrap=True))

        sl.addSpacing(10)
        sl.addWidget(_label("Пресеты", "rowtitle"))
        presets = QHBoxLayout()
        presets.setSpacing(8)
        for title, preset, cap, quality in (
                ("Максимум FPS", fps.PRESET_MAX, 5000, 1),
                ("Сбалансировано", fps.PRESET_BALANCED, 240, 5),
                ("Снять отметки", (), None, None)):
            b = QPushButton(title)
            b.setObjectName("pill")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, p=preset, c=cap, q=quality:
                              self._preset(p, c, q))
            presets.addWidget(b)
        presets.addStretch(1)
        sl.addLayout(presets)
        sl.addStretch(1)
        self.state = _label("", "faint", wrap=True)
        sl.addWidget(self.state)
        go = QPushButton("Применить")
        go.setObjectName("go")
        go.setCursor(Qt.PointingHandCursor)
        go.clicked.connect(self._apply)
        undo = QPushButton("Вернуть как было")
        undo.setObjectName("textbtn")
        undo.setCursor(Qt.PointingHandCursor)
        undo.clicked.connect(self._revert)
        go.setFixedHeight(40)
        go.setFixedWidth(max(170, go.sizeHint().width() + 8))
        undo.setFixedHeight(40)
        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.addWidget(go)
        buttons.addWidget(undo)
        buttons.addStretch(1)
        sl.addLayout(buttons)
        body.addWidget(side, 2)
        root.addLayout(body, 1)

        # Windows: применяется сразу по клику, отдельно от флагов Roblox
        win = QWidget()
        wl = QVBoxLayout(win)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(4)
        wl.addWidget(_label("Windows", "rowtitle"))
        self.gpu = QCheckBox("Мощная видеокарта для Roblox")
        self.power = QCheckBox("Высокая производительность и игровой режим")
        for cb, hint, slot in (
                (self.gpu, "На ноутбуках с двумя видеокартами Windows часто запускает "
                           "Roblox на встроенной, это главная причина низкого fps",
                 self._toggle_gpu),
                (self.power, "Схема питания «Высокая производительность» и игровой "
                             "режим Windows. На ноутбуке лучше играть от зарядки",
                 self._toggle_power)):
            cb.setCursor(Qt.PointingHandCursor)
            cb.clicked.connect(slot)
            wl.addWidget(cb)
            h = _label(hint, "faint", wrap=True)
            h.setContentsMargins(24, 0, 0, 6)
            wl.addWidget(h)
        root.addWidget(win)

        self._load_from_config()

    def _load_from_config(self) -> None:
        config = self.library.config
        for key, cb in self.checks.items():
            cb.setChecked(key in config.fps_options)
        self.cap.setCurrentIndex(max(0, self.cap.findData(config.fps_cap)))
        self.quality.setCurrentIndex(max(0, self.quality.findData(config.fps_quality)))
        state = pcboost.load_state()
        self.gpu.setChecked(pcboost.gpu_enabled(state))
        self.power.setChecked(pcboost.power_enabled(state))

    def _toggle_gpu(self, on: bool) -> None:
        try:
            if on:
                done = pcboost.enable_gpu()
                text = (f"Видеокарта: Roblox ({len(done)} верс.) пойдёт на мощной, "
                        "перезапусти Roblox")
            else:
                pcboost.disable_gpu()
                text = "Видеокарта: как было"
        except (pcboost.BoostError, OSError) as exc:
            self.gpu.setChecked(not on)
            QMessageBox.critical(self, "Видеокарта", str(exc))
            return
        self.library.message.emit(text, True)

    def _toggle_power(self, on: bool) -> None:
        try:
            if on:
                pcboost.enable_power()
                text = "Питание: высокая производительность, игровой режим включён"
            else:
                pcboost.disable_power()
                text = "Питание: прежняя схема"
        except (pcboost.BoostError, OSError) as exc:
            self.power.setChecked(not on)
            QMessageBox.critical(self, "Питание", str(exc))
            return
        self.library.message.emit(text, True)

    def _preset(self, options, cap, quality) -> None:
        for key, cb in self.checks.items():
            cb.setChecked(key in options)
        self.cap.setCurrentIndex(max(0, self.cap.findData(cap)))
        self.quality.setCurrentIndex(max(0, self.quality.findData(quality)))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_state()

    def refresh_state(self) -> None:
        backend = self.library._backend_key()
        bridge = self._bridge

        def work() -> None:
            try:
                version_dir = core.resolve_roblox_dir()
            except OSError:
                version_dir = None
            lines = []
            if version_dir is not None:
                active = fps.active_options(version_dir, backend)
                lines.append("Сейчас стоит: " + (", ".join(
                    fps.FLAG_OPTIONS[k]["title"] for k in active) if active else "ничего"))
            basic = fps.read_basic()
            if basic:
                q = basic.get("quality")
                lines.append(f"Лимит {basic.get('cap', '?')} fps, графика "
                             + ("авто" if q == 0 else str(q)))
            if fps.roblox_running():
                lines.append("Roblox запущен: лимит и качество применятся после его закрытия")
            bridge.ready.emit("\n".join(lines))

        self._pool.submit(work)

    def _apply(self) -> None:
        try:
            version_dir = core.resolve_roblox_dir()
        except OSError:
            version_dir = None
        if version_dir is None:
            QMessageBox.warning(self, "Roblox не найден",
                                "Запусти Roblox один раз и открой программу снова.")
            return
        config = self.library.config
        backend = self.library._backend_key()
        options = [k for k, cb in self.checks.items() if cb.isChecked()]
        cap, quality = self.cap.currentData(), self.quality.currentData()
        notes = []
        try:
            if options:
                fps.apply_flags(version_dir, options, backend)
            else:
                fps.revert_flags(version_dir, backend)
            if cap is not None or quality is not None:
                if fps.roblox_running():
                    notes.append("закрой Roblox и нажми ещё раз: лимит и качество не записаны")
                else:
                    fps.apply_basic(cap, quality)
        except (fps.FpsError, OSError) as exc:
            QMessageBox.critical(self, "Не удалось применить", str(exc))
            return
        config.fps_options, config.fps_cap, config.fps_quality = options, cap, quality
        config.backend = backend
        config.version = version_dir.name
        config.save()
        self.library.configChanged.emit()
        self.refresh_state()
        self.library.message.emit(
            f"FPS: опций {len(options)}"
            + (f", лимит {cap}" if cap else "")
            + (". " + notes[0].capitalize() if notes else ". Перезапусти Roblox"), True)

    def _revert(self) -> None:
        try:
            version_dir = core.resolve_roblox_dir()
        except OSError:
            version_dir = None
        if version_dir is not None:
            try:
                fps.revert_flags(version_dir, self.library._backend_key())
            except (fps.FpsError, OSError) as exc:
                QMessageBox.critical(self, "Не удалось вернуть", str(exc))
                return
        basic_note = ""
        if fps.roblox_running():
            basic_note = ". Закрой Roblox, чтобы вернуть лимит и качество"
        else:
            fps.revert_basic()
        config = self.library.config
        config.fps_options, config.fps_cap, config.fps_quality = [], None, None
        config.save()
        self._load_from_config()
        self.refresh_state()
        self.library.configChanged.emit()
        self.library.message.emit("FPS: всё как было" + basic_note, True)


# ─────────────────────────────────────────────────────────────────────────────
# сервера
# ─────────────────────────────────────────────────────────────────────────────
class _Net(QObject):
    """Мост из фонового потока: сигналы доставляются в главный поток очередью."""
    # place, имя игры, серверы, курсор следующей страницы, дописать к списку
    done = Signal(int, str, list, str, bool)
    failed = Signal(str)
    waiting = Signal(int)


class ServersPage(QWidget):
    def __init__(self, library: LibraryPage, parent=None):
        super().__init__(parent)
        self.library = library
        self.place: int | None = None
        self.servers: list[servers.Server] = []
        self._cursor = ""
        self._busy = False
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._net = _Net(self)
        self._net.done.connect(self._on_done)
        self._net.failed.connect(self._on_failed)
        self._net.waiting.connect(
            lambda sec: self.state.setText(
                f"Roblox даёт список серверов 3 раза в минуту, жду {sec} сек…"))

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 28, 14)
        root.setSpacing(18)
        _head(root, "Лучший сервер",
              "Вставь ссылку на игру, и я покажу её серверы, лучший сверху. Пинг "
              "средний у тех, кто уже играет: чем ниже, тем сервер обычно ближе. "
              "Сам пинг программа не меняет, только выбирает сервер.")

        row = QHBoxLayout()
        row.setSpacing(0)
        self.input = QLineEdit()
        self.input.setObjectName("search")
        self.input.setPlaceholderText("Ссылка на игру или её номер")
        self.input.returnPressed.connect(self._search)
        row.addWidget(self.input, 1)
        find = QPushButton("Найти")
        find.setObjectName("pill")
        find.setCursor(Qt.PointingHandCursor)
        find.clicked.connect(self._search)
        row.addSpacing(8)
        row.addWidget(find)
        root.addLayout(row)

        self.recent_host = QWidget()
        self.recent = QGridLayout(self.recent_host)
        self.recent.setContentsMargins(0, 0, 0, 0)
        self.recent.setSpacing(4)
        root.addWidget(self.recent_host)

        top = QHBoxLayout()
        self.game = _label("", "rowtitle")
        top.addWidget(self.game, 1)
        self.best_btn = QPushButton("Зайти на лучший")
        self.best_btn.setObjectName("go")
        self.best_btn.setCursor(Qt.PointingHandCursor)
        self.best_btn.setFixedHeight(40)
        self.best_btn.setFixedWidth(max(170, self.best_btn.sizeHint().width() + 8))
        self.best_btn.clicked.connect(self._join_best)
        self.best_btn.setEnabled(False)
        top.addWidget(self.best_btn)
        root.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Пинг", "FPS сервера", "Игроки", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        for col in range(3):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 110)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.state = _label("", "faint", wrap=True)
        bottom.addWidget(self.state, 1)
        self.more = QPushButton("Ещё 100 серверов")
        self.more.setObjectName("textbtn")
        self.more.clicked.connect(self._load_more)
        self.more.setEnabled(False)
        bottom.addWidget(self.more)
        root.addLayout(bottom)
        self._fill_recent()

    def _fill_recent(self) -> None:
        while self.recent.count():
            w = self.recent.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        for i, item in enumerate(self.library.config.recent_places[:6]):
            b = QPushButton(item.get("name") or str(item["place"]))
            b.setObjectName("pill")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, p=item["place"]: self._search(str(p)))
            self.recent.addWidget(b, 0, i)
        self.recent.setColumnStretch(self.recent.columnCount(), 1)
        self.recent_host.setVisible(bool(self.library.config.recent_places))

    def _search(self, text: str | None = None) -> None:
        if self._busy:
            return
        text = text if isinstance(text, str) else self.input.text()
        try:
            place = servers.parse_place(text)
        except servers.ServerError as exc:
            self.state.setText(str(exc))
            return
        self.input.setText(str(place))
        self._fetch(place, "", append=False)

    def _load_more(self) -> None:
        if self.place is not None and self._cursor and not self._busy:
            self._fetch(self.place, self._cursor, append=True)

    def _fetch(self, place: int, cursor: str, append: bool) -> None:
        self._busy = True
        self.best_btn.setEnabled(False)
        self.more.setEnabled(False)
        self.state.setText("Спрашиваю Roblox…")
        net = self._net

        def work():
            try:
                name = "" if append else servers.game_name(place)
                found, nxt = servers.list_servers(
                    place, cursor, waiting=lambda sec: net.waiting.emit(sec))
            except servers.ServerError as exc:
                net.failed.emit(str(exc))
            except Exception as exc:  # фон не должен уронить окно
                net.failed.emit(f"ошибка: {exc}")
            else:
                net.done.emit(place, name, found, nxt, append)

        self._pool.submit(work)

    def _on_failed(self, error: str) -> None:
        self._busy = False
        self.more.setEnabled(bool(self._cursor))
        self.best_btn.setEnabled(servers.best(self.servers) is not None)
        self.state.setText(error)

    def _on_done(self, place: int, name: str, found: list, nxt: str,
                 append: bool) -> None:
        self._busy = False
        self.place = place
        self._cursor = nxt
        if append:
            known = {s.id for s in self.servers}
            self.servers += [s for s in found if s.id not in known]
        else:
            self.servers = found
            self.game.setText(name or f"Игра {place}")
            config = self.library.config
            config.remember_place(place, name or str(place))
            config.save()
            self._fill_recent()
        self._fill()
        self.more.setEnabled(bool(nxt))

    def _fill(self) -> None:
        rows = servers.ranked(self.servers)
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            ping = QTableWidgetItem("—" if s.ping is None else f"{s.ping} мс")
            if s.ping is not None:
                ping.setForeground(QColor(
                    "#ffffff" if s.ping < 120 else "#9a9a9a" if s.ping < 220 else "#5c5c5c"))
            self.table.setItem(r, 0, ping)
            self.table.setItem(r, 1, QTableWidgetItem(f"{s.fps:.0f}"))
            self.table.setItem(r, 2, QTableWidgetItem(f"{s.playing} / {s.max_players}"))
            join = QPushButton("Зайти")
            join.setObjectName("textbtn")
            join.clicked.connect(lambda _=False, sid=s.id: self._join(sid))
            self.table.setCellWidget(r, 3, join)
        best = servers.best(self.servers)
        self.best_btn.setEnabled(best is not None)
        total = len(self.servers)
        self.state.setText(
            f"Серверов: {total}, показано: {len(rows)}"
            + (f". Лучший: {best.ping} мс, {best.playing}/{best.max_players}"
               if best else ". С пингом нет ни одного, зайди в любой"))

    def _join(self, server_id: str | None) -> None:
        if self.place is None:
            return
        try:
            servers.join(self.place, server_id)
        except OSError as exc:
            QMessageBox.critical(self, "Roblox не открылся",
                                 f"Не удалось открыть ссылку roblox://: {exc}")
            return
        self.library.message.emit("Открываю Roblox на выбранном сервере…", True)

    def _join_best(self) -> None:
        best = servers.best(self.servers)
        if best is not None:
            self._join(best.id)
