"""
config_page.py — вкладка config: что сейчас выбрано и стоит ли оно.

Блоки по слотам: курсор, shiftlock, skybox, звук смерти, шрифт; остальные
звуки — строкой ниже. Данные берутся из core.config через LibraryPage: она
же умеет собрать набор и сравнить его с файлами Roblox, поэтому страница
ничего не пишет на диск сама.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from cursor_manager.content import sounds as snd
from cursor_manager.core import config as cfg
from cursor_manager.core import cursor_core as core
from cursor_manager.core import roblox_paths as RP
from cursor_manager.ui.library import KIND_ONE, LibraryPage, entry_name

BLOCK_PREVIEW = 96
BLOCKS = ("cursor", "crosshair", "sky", "material", cfg.SOUND_PREFIX + "death", "font")
STATE_TEXT = {
    "on": ("Стоит сейчас", "ok"),
    "off": ("Слетело, нажми «Поставить заново»", "bad"),
    "none": ("Оригинал Roblox", "faint"),
}
# не пересобирать состояние слотов при каждом заходе на вкладку: оно считает
# хеши файлов и собирает наборы, а меняется только после применения/снятия
STALE_SECONDS = 30


def slot_title(key: str) -> str:
    if key.startswith(cfg.SOUND_PREFIX):
        role = key[len(cfg.SOUND_PREFIX):]
        return "Звук: " + snd.ROLES.get(role, {}).get("title", role)
    return KIND_ONE.get(key, key).capitalize()


class ConfigPage(QWidget):
    # открыть вкладку библиотеки нужной категории
    pickRequested = Signal(str)

    def __init__(self, library: LibraryPage, parent=None):
        super().__init__(parent)
        self.library = library
        self.blocks: dict[str, dict] = {}
        self._dirty = True
        self._fresh_at = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 28, 14)
        root.setSpacing(24)

        head = QLabel("Config")
        head.setObjectName("h1")
        root.addWidget(head)
        sub = QLabel("Выбор запоминается при закрытии программы. Если Roblox "
                     "обновится, при следующем запуске всё поставится обратно само.")
        sub.setObjectName("body")
        sub.setWordWrap(True)
        sub.setMaximumWidth(620)
        root.addWidget(sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(26)
        for i, key in enumerate(BLOCKS):
            grid.addWidget(self._block(key), i // 3, i % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        root.addLayout(grid)

        self.extra = QLabel("")
        self.extra.setObjectName("faint")
        self.extra.setWordWrap(True)
        root.addWidget(self.extra)
        self.info = QLabel("")
        self.info.setObjectName("faint")
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.reapply = QPushButton("Поставить заново")
        self.reapply.setObjectName("go")
        self.reapply.setCursor(Qt.PointingHandCursor)
        self.reapply.setFixedHeight(40)
        self.reapply.setFixedWidth(max(170, self.reapply.sizeHint().width() + 8))
        self.reapply.clicked.connect(self._reapply)
        actions.addWidget(self.reapply)
        reset = QPushButton("Снять всё")
        reset.setObjectName("textbtn")
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(self.library.revert_all)
        actions.addWidget(reset)
        actions.addStretch(1)
        root.addLayout(actions)
        root.addStretch(1)

        library.configChanged.connect(self._mark_dirty)

    def _block(self, key: str) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        title = QLabel(slot_title(key))
        title.setObjectName("rowtitle")
        lay.addWidget(title)
        preview = QLabel()
        preview.setObjectName("preview")
        preview.setAlignment(Qt.AlignCenter)
        preview.setFixedHeight(BLOCK_PREVIEW + 16)
        lay.addWidget(preview)
        name = QLabel("")
        name.setObjectName("body")
        name.setWordWrap(True)
        lay.addWidget(name)
        state = QLabel("")
        state.setWordWrap(True)
        lay.addWidget(state)
        buttons = QHBoxLayout()
        pick = QPushButton("Выбрать")
        pick.setObjectName("pill")
        pick.setCursor(Qt.PointingHandCursor)
        pick.clicked.connect(lambda: self.pickRequested.emit(cfg.slot_kind(key)))
        buttons.addWidget(pick)
        drop = QPushButton("Снять")
        drop.setObjectName("textbtn")
        drop.setCursor(Qt.PointingHandCursor)
        drop.clicked.connect(lambda: self.library.revert_slot(key))
        buttons.addWidget(drop)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        self.blocks[key] = {"preview": preview, "name": name,
                            "state": state, "drop": drop}
        return box

    def _mark_dirty(self) -> None:
        self._dirty = True
        if self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        self._dirty = False
        self._fresh_at = time.monotonic()
        config = self.library.config
        try:
            version_dir = core.resolve_roblox_dir()
        except OSError:
            version_dir = None
        for key, w in self.blocks.items():
            kind = cfg.slot_kind(key)
            slot = config.slots.get(key)
            entry = self.library.find(kind, slot.id) if slot else None
            state = self.library.slot_state(key, version_dir)
            if entry is not None:
                size = ((200, 100) if kind in (RP.KIND_SKY, RP.KIND_FONT)
                        else (BLOCK_PREVIEW, BLOCK_PREVIEW))
                pixmap = self.library._thumb(kind, entry, size)
                w["preview"].setText("" if pixmap else "?")
                w["preview"].setPixmap(pixmap or QPixmap())
                w["name"].setText(entry_name(kind, entry))
            else:
                w["preview"].setPixmap(QPixmap())
                w["preview"].setText("—")
                w["name"].setText(slot.name if slot else "Оригинал")
            text, obj = STATE_TEXT[state]
            w["state"].setText(text)
            w["state"].setObjectName(obj)
            w["state"].style().unpolish(w["state"])
            w["state"].style().polish(w["state"])
            w["drop"].setEnabled(slot is not None)

        others = [f"{slot_title(k)} — {s.name}" for k, s in config.slots.items()
                  if k not in BLOCKS]
        self.extra.setText("Ещё звуки: " + "; ".join(others) if others else "")
        self.extra.setVisible(bool(others))

        current = version_dir.name if version_dir else "не найден"
        lines = [f"Сейчас установлен Roblox: {current}"]
        if config.version:
            lines.append(f"Ставили на версию: {config.version}")
        if config.fps_options:
            lines.append(f"Включено опций fps: {len(config.fps_options)}")
        self.info.setText("\n".join(lines))
        self.reapply.setEnabled(bool(config.slots or config.fps_options)
                                and version_dir is not None)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # вкладка открывается сразу, состояние слотов дочитывается следом
        if self._dirty or time.monotonic() - self._fresh_at > STALE_SECONDS:
            QTimer.singleShot(0, self.refresh)

    def _reapply(self) -> None:
        names = self.library.restore_config(force=True)
        if names:
            self.library.message.emit("Поставлено заново: " + ", ".join(names), True)
        else:
            self.library.message.emit("Нечего ставить или Roblox не найден", True)
        self.refresh()
