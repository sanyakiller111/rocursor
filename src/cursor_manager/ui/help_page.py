"""
help_page.py — вкладка «Фиксы»: фикс картинок, чистка, починка, обновления.

Вся работа — в core.netfix / core.maintenance / core.updates. Долгие вызовы
(проверка сети, окно UAC для DNS, проверка обновлений) идут в фоновом
потоке, а сюда приходит результат через сигнал _Done.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from cursor_manager.core import cursor_core as core
from cursor_manager.core import maintenance, netfix, updates
from cursor_manager.ui.library import LibraryPage
from cursor_manager.version import VERSION

PROVIDER_TITLE = {"cloudflare": "Cloudflare 1.1.1.1", "google": "Google 8.8.8.8",
                  "quad9": "Quad9 9.9.9.9"}


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} МБ" if n >= 1024 * 1024 else f"{n // 1024} КБ"


class _Done(QObject):
    """Мост из фонового потока: (что делали, результат или Exception)."""
    done = Signal(str, object)


class HelpPage(QWidget):
    # нашлась новая версия программы: (версия, ссылка)
    updateFound = Signal(str, str)

    def __init__(self, library: LibraryPage, parent=None):
        super().__init__(parent)
        self.library = library
        self.junk: list[tuple[dict, QCheckBox]] = []
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._bridge = _Done(self)
        self._bridge.done.connect(self._on_done)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 48, 0)
        root.setSpacing(0)
        title = QLabel("Фиксы")
        title.setObjectName("h1")
        root.addWidget(title)
        root.addSpacing(18)
        # строки без рамок: разделяет их только воздух
        for row in (self._net_row(), self._clean_row(),
                    self._repair_row(), self._update_row()):
            root.addWidget(row)
        root.addStretch(1)

    # ── каркас ──────────────────────────────────────────────────────────
    @staticmethod
    def _row(title: str, text: str) -> tuple[QWidget, QVBoxLayout, QHBoxLayout]:
        """Строка: слева заголовок и пояснение (сюда же статус), справа кнопки."""
        row = QWidget()
        outer = QHBoxLayout(row)
        outer.setContentsMargins(0, 20, 0, 20)
        outer.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(6)
        head = QLabel(title)
        head.setObjectName("rowtitle")
        left.addWidget(head)
        sub = QLabel(text)
        sub.setObjectName("body")
        sub.setWordWrap(True)
        sub.setMaximumWidth(520)
        left.addWidget(sub)
        outer.addLayout(left, 1)
        # без растяжки строка не шире своего текста, и Qt центрирует её —
        # нижние строки «съезжали» вправо
        outer.addStretch(0)
        right = QHBoxLayout()
        right.setSpacing(12)
        outer.addLayout(right)
        return row, left, right

    @staticmethod
    def _status() -> QLabel:
        lab = QLabel("")
        lab.setObjectName("faint")
        lab.setWordWrap(True)
        lab.setMaximumWidth(520)
        return lab

    @staticmethod
    def _btn(text: str, obj: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        if obj == "go":
            b.setFixedHeight(40)
            b.setFixedWidth(max(170, b.sizeHint().width() + 8))
        return b

    def _run(self, task: str, fn) -> None:
        bridge = self._bridge

        def work():
            try:
                result = fn()
            except Exception as exc:  # фон не должен уронить окно
                result = exc
            bridge.done.emit(task, result)

        self._pool.submit(work)

    # ── фикс картинок ───────────────────────────────────────────────────
    def _net_row(self) -> QWidget:
        row, left, right = self._row(
            "Не грузятся картинки",
            "Плейсы, аватарки и иконки пустые? Чаще всего виноват DNS провайдера. "
            "Проверь, и если плохо, поставь публичный DNS. Windows спросит "
            "разрешение (UAC), вернуть можно одной кнопкой.")
        self.net_state = self._status()
        left.addWidget(self.net_state)
        right.addWidget(self._btn("Проверить", "textbtn", self._diagnose))
        right.addWidget(self._btn("Вернуть DNS", "textbtn", self._restore_dns))
        self.provider = QComboBox()
        for key in netfix.PROVIDERS:
            self.provider.addItem(PROVIDER_TITLE.get(key, key), key)
        right.addWidget(self.provider)
        right.addWidget(self._btn("Починить картинки", "go", self._fix_dns))
        return row

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # current_dns зовёт PowerShell (секунды) — в фоне и один раз: иначе
        # вкладка висла бы на этом вызове в потоке интерфейса
        if not getattr(self, "_dns_shown", False):
            self._dns_shown = True
            self.net_state.setText("Читаю текущий DNS…")
            self._run("dns_now", netfix.current_dns)

    def _show_dns(self, result) -> None:
        if isinstance(result, Exception):
            self.net_state.setText(f"DNS не прочитался: {result}")
            return
        adapters = [a for a in result if a.get("servers") or a.get("dhcp")]
        lines = [f"{a['adapter']}: " + (", ".join(a["servers"]) if a["servers"] and not a["dhcp"]
                                         else "от провайдера (авто)")
                 for a in adapters[:3]]
        self.net_state.setText("Сейчас DNS: " + ("; ".join(lines) or "не найден"))
        self._set_state(self.net_state, self.net_state.text(), None)

    def _set_state(self, label: QLabel, text: str, ok: bool | None) -> None:
        label.setText(text)
        label.setObjectName({True: "ok", False: "bad"}.get(ok, "faint"))
        label.style().unpolish(label)
        label.style().polish(label)

    def _diagnose(self) -> None:
        self._set_state(self.net_state, "Проверяю, грузятся ли картинки Roblox…", None)
        self._run("diagnose", netfix.diagnose)

    def _fix_dns(self) -> None:
        provider = self.provider.currentData()
        if QMessageBox.question(
                self, "Фикс картинок",
                f"Поставить DNS {PROVIDER_TITLE.get(provider, provider)} на активный "
                "сетевой адаптер?\nwindows попросит разрешение. старый DNS сохранится — "
                "вернуть можно кнопкой «вернуть DNS»."
        ) != QMessageBox.Yes:
            return
        self._set_state(self.net_state, "Жду разрешение Windows…", None)
        self._run("dns", lambda: netfix.apply(provider))

    def _restore_dns(self) -> None:
        self._set_state(self.net_state, "Возвращаю старый DNS…", None)
        self._run("restore", netfix.restore)

    # ── чистка ─────────────────────────────────────────────────────────
    def _clean_row(self) -> QWidget:
        row, left, right = self._row(
            "Почистить Roblox",
            "Логи, временные файлы, скачанные установщики и старые версии. "
            "Вход в аккаунт и настройки игры не трогаются.")
        self.junk_host = QVBoxLayout()
        left.addLayout(self.junk_host)
        self.clean_state = self._status()
        left.addWidget(self.clean_state)
        right.addWidget(self._btn("Найти мусор", "textbtn", self._scan))
        right.addWidget(self._btn("Почистить", "go", self._clean))
        return row

    def _scan(self) -> None:
        while self.junk_host.count():
            w = self.junk_host.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.junk = []
        try:
            found = maintenance.scan_junk()
        except Exception as exc:
            self._set_state(self.clean_state, f"Не получилось: {exc}", False)
            return
        for item in found:
            cb = QCheckBox(f"{item['title']} — {_mb(item['bytes'])}")
            cb.setChecked(True)
            cb.setToolTip(item["path"])
            self.junk_host.addWidget(cb)
            self.junk.append((item, cb))
        total = sum(it["bytes"] for it in found)
        self._set_state(self.clean_state,
                        f"Можно освободить {_mb(total)}" if found else "Мусора нет", None)

    def _clean(self) -> None:
        if not self.junk:
            self._scan()
        picked = [item for item, cb in self.junk if cb.isChecked()]
        if not picked:
            return
        total = sum(it["bytes"] for it in picked)
        if QMessageBox.question(self, "Почистить", f"Удалить {_mb(total)}?\n"
                                "Это нельзя отменить, но Roblox ничего важного не потеряет."
                                ) != QMessageBox.Yes:
            return
        res = maintenance.clean(picked)
        skipped = len(res.get("skipped", []))
        self._set_state(self.clean_state,
                        f"Освобождено {_mb(res['removed_bytes'])}"
                        + (f". Пропущено {skipped}: занято, закрой Roblox" if skipped else ""),
                        True)
        self._scan()

    # ── починка ─────────────────────────────────────────────────────────
    def _repair_row(self) -> QWidget:
        row, left, right = self._row(
            "Что-то сломалось после модов",
            "Вернёт оригинальные курсоры, shiftlock, skybox, звуки, шрифты, "
            "флаги fps и настройки графики.")
        self.repair_state = self._status()
        left.addWidget(self.repair_state)
        right.addWidget(self._btn("Вернуть всё как было", "go", self._repair))
        return row

    def _repair(self) -> None:
        try:
            version_dir = core.resolve_roblox_dir()
        except OSError:
            version_dir = None
        if version_dir is None:
            self._set_state(self.repair_state, "Roblox не найден", False)
            return
        self.library.revert_all()           # сам спросит подтверждение
        res = maintenance.repair(version_dir)
        config = self.library.config
        config.fps_options, config.fps_cap, config.fps_quality = [], None, None
        config.save()
        self.library.configChanged.emit()
        notes = res.get("skipped", []) + res.get("errors", [])
        self._set_state(self.repair_state,
                        "Флаги и настройки графики возвращены"
                        + ("\n" + "\n".join(notes) if notes else ""), not res.get("errors"))

    # ── обновления ──────────────────────────────────────────────────────
    def _update_row(self) -> QWidget:
        row, left, right = self._row("Обновления", f"Сейчас стоит версия {VERSION}.")
        self.update_state = self._status()
        left.addWidget(self.update_state)
        self.update_btn = self._btn("Скачать новую", "go", self._open_update)
        self.update_btn.hide()
        right.addWidget(self.update_btn)
        right.addWidget(self._btn("Проверить", "go", self.check_updates))
        self._update_url = ""
        return row

    def check_updates(self) -> None:
        self._set_state(self.update_state, "Проверяю…", None)
        self._run("update", updates.check)

    def _open_update(self) -> None:
        if self._update_url:
            QDesktopServices.openUrl(QUrl(self._update_url))

    # ── результаты из фона ──────────────────────────────────────────────
    def _on_done(self, task: str, result) -> None:
        if task == "dns_now":
            self._show_dns(result)
        elif task == "diagnose":
            if isinstance(result, Exception):
                self._set_state(self.net_state, f"Проверка не удалась: {result}", False)
                return
            bad = [d["name"] for d in result.get("details", []) if not d.get("ok")]
            if result.get("ok"):
                self._set_state(self.net_state, "Картинки Roblox грузятся нормально", True)
            else:
                self._set_state(self.net_state, "Не грузится: " + ", ".join(bad)
                                + ". Нажми «Починить картинки»", False)
        elif task == "dns":
            if isinstance(result, Exception) or not result.get("applied"):
                err = result if isinstance(result, Exception) else result.get("error")
                self._set_state(self.net_state, f"DNS не поменялся: {err}", False)
                return
            netfix.flush()
            self._set_state(self.net_state, "DNS поставлен, перезапусти Roblox", True)
            self.library.message.emit("Фикс картинок применён, перезапусти Roblox", True)
        elif task == "restore":
            if isinstance(result, Exception) or not result.get("restored"):
                err = result if isinstance(result, Exception) else result.get("error")
                self._set_state(self.net_state, f"Не вернулось: {err}", False)
                return
            self._set_state(self.net_state, "Старый DNS возвращён", True)
        elif task == "update":
            if isinstance(result, Exception) or result is None:
                self._set_state(self.update_state, "У тебя последняя версия "
                                "(или сервер обновлений недоступен)", None)
                self.update_btn.hide()
                return
            self._update_url = result.get("url", "")
            self._set_state(self.update_state,
                            f"Вышла версия {result['version']}"
                            + (f": {result['notes']}" if result.get("notes") else ""), True)
            self.update_btn.show()
            self.updateFound.emit(result["version"], self._update_url)
