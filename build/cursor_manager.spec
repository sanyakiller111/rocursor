# -*- mode: python ; coding: utf-8 -*-
"""
build/cursor_manager.spec — конфигурация PyInstaller (onefile).

Запуск:  python -m PyInstaller --clean build/cursor_manager.spec
         (обычно через build/build.py, который заполняет версию)

Почему ONEFILE
──────────────
Цель сборки — один готовый sanyakiller111.exe, который не надо искать и
который можно просто запустить. Ассеты (курсоры, прицелы, небо, иконка)
упакованы внутрь и при старте распаковываются во временный каталог
(sys._MEIPASS); поиск ресурсов в content/*.py уже учитывает это.
Цена — распаковка при каждом запуске и чуть больше внимания антивирусов;
подпись Authenticode (см. docs/BUILD.md) это снимает.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# spec лежит в build/, корень — на уровень выше
HERE = Path(SPECPATH).resolve()
ROOT = HERE.parent if HERE.name == "build" else HERE

sys.path.insert(0, str(ROOT / "src"))
from cursor_manager.version import APP_SLUG  # noqa: E402

datas = [
    # Вшитые каталоги: приложение обязано запускаться без сети.
    (str(ROOT / "assets" / "cursors"), "assets/cursors"),
    (str(ROOT / "assets" / "crosshairs"), "assets/crosshairs"),
    (str(ROOT / "assets" / "skyboxes"), "assets/skyboxes"),
    (str(ROOT / "assets" / "sounds"), "assets/sounds"),
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
]
icon_path = ROOT / "assets" / "icons" / "icon.ico"
if icon_path.is_file():
    datas.append((str(icon_path), "assets/icons"))

for extra in collect_data_files("PIL", include_py_files=False):
    if "plugins" not in extra[0]:
        datas.append(extra)

block_cipher = None

a = Analysis(
    [str(ROOT / "src" / "cursor_manager" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "cursor_manager.app",
        "cursor_manager.core.cursor_core",
        "cursor_manager.core.profiles",
        "cursor_manager.core.rcur",
        "cursor_manager.core.respack",
        "cursor_manager.core.roblox_paths",
        "cursor_manager.content.cursor_library",
        "cursor_manager.content.sounds",
        "cursor_manager.content.fonts",
        "cursor_manager.content.crosshair",
        "cursor_manager.content.skybox",
        "cursor_manager.ui.library",
        # грузится лениво в LibraryPage._play — анализатор его не видит
        "PySide6.QtMultimedia",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # не тащим то, что приложение не использует: tkinter и чужие
        # Qt-биндинги PyInstaller запрещает собирать вместе (см. changelog 6.x)
        "PyQt5", "PyQt6", "PySide2",
        "tkinter", "tkinter.test", "test", "unittest", "pydoc_data",
        "numpy", "matplotlib", "scipy", "pandas",
        "setuptools", "pip", "wheel",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_SLUG,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX триггерит эвристики; выигрыш в 3 МБ не окупает карантин
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # GUI-приложение: чёрное окно консоли не нужно
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,    # подпись делает build.py, после сборки
    entitlements_file=None,
    icon=str(icon_path) if icon_path.is_file() else None,
    version=str(HERE / "version_info.txt")
            if (HERE / "version_info.txt").is_file() else None,
)
