"""
cursor_core.py — логика без GUI:
  • парсинг курсоров с osuskinner.com
  • поиск папки Roblox
  • бэкап / подмена / восстановление курсоров
"""
import json
import os
import re
import shutil
import time
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

BASE = "https://osuskinner.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "RobloxCursorChanger"
CACHE_DIR = APP_DIR / "cache"      # скачанные курсоры
BACKUP_DIR = APP_DIR / "backup"    # оригиналы Roblox (по версиям)
INDEX_FILE = APP_DIR / "index.json"
CONFIG_FILE = APP_DIR / "config.json"

# путь внутри папки version-xxxx
REL = Path("content") / "textures" / "Cursors" / "KeyboardMouse"

# ────────────────────────────────────────────────────────────────────────────
# Файлы курсоров Roblox
#
# Разведка реальной установки (version-cec3ad5889b447cf) показала:
#   Cursors/KeyboardMouse/ArrowCursor.png      934 Б  64x64
#   Cursors/KeyboardMouse/ArrowFarCursor.png   934 Б  64x64
#   Cursors/KeyboardMouse/IBeamCursor.png       173 Б  64x64
#
# MouseLockedCursor.png лежит в content/textures/ (корень), а НЕ в
# KeyboardMouse/, поэтому apply() его не найдёт и пропустит. Он остаётся
# в списке на случай версий, где раскладка другая.
#
# IBeamCursor — вертикальная черта для текстовых полей ввода. Ставить туда
# игровую стрелку бессмысленно: она нужна ровно там, где пользователь вводит
# текст. Поэтому по умолчанию выключен, в отличие от первых двух.
# ────────────────────────────────────────────────────────────────────────────
FILES = ["ArrowCursor.png", "ArrowFarCursor.png", "IBeamCursor.png", "MouseLockedCursor.png"]
DEFAULT_FILES = ["ArrowCursor.png", "ArrowFarCursor.png"]

FILE_ROLE = {
    "ArrowCursor.png":       ("main",  True),
    "ArrowFarCursor.png":    ("alt",   True),
    "IBeamCursor.png":       ("ibeam", False),
    "MouseLockedCursor.png": ("locked", False),
}

# Реестр Windows: Roblox регистрирует протокол roblox-player. Из этих значений
# берётся номер текущей версии — точнее, чем сортировка папок по дате.
REG_ROBLOX_KEY = r"roblox-player\shell\open\command"


# ───────────────────────────── конфиг / индекс ─────────────────────────────
def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_config():
    return _read_json(CONFIG_FILE, {})


def save_config(cfg):
    _write_json(CONFIG_FILE, cfg)


def load_index():
    return _read_json(INDEX_FILE, [])


def save_index(items):
    _write_json(INDEX_FILE, items)


# ───────────────────────────── парсер osuskinner ───────────────────────────
def img_url(item):
    return f"{BASE}/elements/interface/cursor/{item['skin']}/{item['id']}.png"


def scrape_index(progress=None):
    """Обходит все страницы /interface/cursor?p=N и собирает [{'id':..,'skin':..}].
    Порядок = как на сайте (по популярности/скачиваниям)."""
    session = requests.Session()
    session.headers.update(HEADERS)
    items, seen = [], set()
    page, last = 1, None

    while True:
        r = session.get(f"{BASE}/interface/cursor", params={"p": page}, timeout=20)
        r.raise_for_status()
        html = r.text

        if last is None:  # номер последней страницы берём из пагинации
            nums = [int(n) for n in re.findall(r"(?:\?|&amp;|&)p=(\d+)", html)]
            last = max(nums) if nums else 1

        new = 0
        for eid, skin in re.findall(r"/element/(\d+)/(\d+)", html):
            if eid not in seen:
                seen.add(eid)
                items.append({"id": int(eid), "skin": int(skin)})
                new += 1

        if progress:
            progress(page, last, len(items))
        if new == 0:
            if page == 1:
                raise RuntimeError(
                    "На странице не найдено ни одного курсора "
                    "(сайт мог поменять вёрстку или отдаёт защиту Cloudflare)."
                )
            break
        if page >= last:
            break
        page += 1
        time.sleep(0.4)  # не долбим сайт
    return items


def get_cursor_image(item):
    """Возвращает путь к PNG курсора; скачивает в кэш, если его там нет."""
    path = CACHE_DIR / f"{item['id']}.png"
    if path.exists() and path.stat().st_size > 0:
        return path
    r = requests.get(img_url(item), headers=HEADERS, timeout=20)
    r.raise_for_status()
    Image.open(BytesIO(r.content)).verify()  # убедимся, что это картинка
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(r.content)
    tmp.replace(path)
    return path


# ───────────────────────────── поиск Roblox ────────────────────────────────
def _versions_in(root: Path):
    out = []
    for r in (root, root / "Versions"):
        if (r / REL).is_dir():
            out.append(r)
        if r.is_dir():
            try:
                out += [d for d in r.iterdir() if d.is_dir() and (d / REL).is_dir()]
            except OSError:
                pass
    return out


def _is_usable(version_dir: Path) -> bool:
    """Папка годится, только если это полноценная версия Roblox с текстурами."""
    try:
        return (version_dir / "RobloxPlayerBeta.exe").is_file() and (version_dir / REL).is_dir()
    except OSError:
        return False


def _extract_exe_path(raw: str):
    """Из строки команды Roblox вытащить путь к .exe."""
    exe = str(raw).strip().strip('"')
    exe = exe.split('"')[0] if '"' in exe else exe.split(" %")[0].split(" /")[0]
    exe = exe.strip().strip('"')
    if exe.lower().endswith(".exe") and Path(exe).is_file():
        return Path(exe)
    return None


def _registry_roots():
    for var in ("LOCALAPPDATA", "PROGRAMFILES(X86)", "PROGRAMFILES"):
        v = os.environ.get(var)
        if v:
            yield Path(v) / "Roblox"


def registry_versions():
    """
    Кандидаты из реестра Windows, от более доверенного к менее.

    Разведка реальной установки показала, что значения в реестре расходятся
    между собой: version указывало на version-4310300497aa4917, команда
    открытия — на version-cec3ad5889b447cf, и папки version-4310300497aa4917
    на диске вообще не было. Поэтому ни одно значение не берётся вслепую:
    реестр только предлагает кандидатов, решает проверка на диске.

    Порядок доверия:
      1. version         — номер текущей версии, который Roblox пишет сам
      2. команда открытия — (default), путь к .exe
      3. ogProtocol       — иногда указывает на живую версию при мёртвой (default)
    """
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, REG_ROBLOX_KEY) as key:
            values = {}
            for i in range(winreg.QueryInfoKey(key)[1]):
                name, data, _ = winreg.EnumValue(key, i)
                # у значения по умолчанию имя пустое — без подмены оно бы
                # потерялось, а это как раз путь к .exe
                values[name or "(default)"] = data
    except OSError:
        return []

    candidates = []

    if values.get("version"):
        name = str(values["version"]).strip()
        if name.startswith("version-"):
            for base in _registry_roots():
                p = base / "Versions" / name
                if p.is_dir():
                    candidates.append((p, "registry:version"))
                    break

    for key_name, label in (("(default)", "command"), ("ogProtocol", "ogProtocol")):
        exe = _extract_exe_path(values.get(key_name) or "")
        if exe and exe.parent.name.startswith("version-"):
            candidates.append((exe.parent, f"registry:{label}"))

    seen, out = set(), []
    for path, source in candidates:
        k = str(path).lower()
        if k in seen or not _is_usable(path):
            continue
        seen.add(k)
        out.append((path, source))
    return out


def scan_versions():
    """Папки, найденные обычным сканированием диска. Запасной путь."""
    found = {}
    for root in _registry_roots():
        for d in _versions_in(root):
            found[str(d)] = d
    manual = os.environ.get("ROBLOX_EXTRA_DIR")
    if manual:
        for d in _versions_in(Path(manual)):
            found[str(d)] = d

    def key(d: Path):
        has_exe = (d / "RobloxPlayerBeta.exe").exists()
        try:
            mtime = d.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (has_exe, mtime)

    return sorted(found.values(), key=key, reverse=True)


def find_roblox_versions(extra=None):
    """
    Список папок version-xxxx с текстурами курсора.

    Порядок: реестр → ручной путь → скан по дате изменения. Реестр точнее,
    потому что Roblox сам пишет номер текущей версии; скан нужен, когда
    регистрация слетела. Каждый кандидат проверяется на диске.
    """
    ordered = [d for d, _ in registry_versions()]
    if extra:
        ordered += [d for d in _versions_in(Path(extra))]
    ordered += scan_versions()

    seen, out = set(), []
    for d in ordered:
        k = str(d).lower()
        if k in seen or not _is_usable(d):
            continue
        seen.add(k)
        out.append(d)
    return out


def resolve_roblox_dir(extra=None):
    """Актуальная папка Roblox или None."""
    versions = find_roblox_versions(extra)
    return versions[0] if versions else None


def roblox_source(extra=None):
    """Папка + источник сведений. Для статус-бара и отчётов о багах."""
    reg = registry_versions()
    if reg:
        return reg[0][0], reg[0][1]
    versions = find_roblox_versions(extra)
    return (versions[0], "scan") if versions else (None, "none")


# ───────────────────────────── подмена курсора ─────────────────────────────
def backup_originals(version_dir: Path):
    """Копирует оригиналы один раз (существующий бэкап НЕ перезаписывается)."""
    dst = BACKUP_DIR / version_dir.name
    dst.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        src, bak = version_dir / REL / name, dst / name
        if src.exists() and not bak.exists():
            shutil.copy2(src, bak)


def original_size(version_dir: Path, name="ArrowCursor.png", fallback=(64, 64)):
    for p in (BACKUP_DIR / version_dir.name / name, version_dir / REL / name):
        if p.exists():
            try:
                with Image.open(p) as im:
                    return im.size
            except Exception:
                pass
    return fallback


def fit_cursor(src: Image.Image, size, scale: float = 1.0,
               nudge: tuple[int, int] = (0, 0)) -> Image.Image:
    """Вписывает курсор по центру прозрачного холста нужного размера.
    Центр картинки = хотспот (и в osu, и в Roblox), поэтому центрируем.

    nudge — сдвиг в пикселях готового холста, шаг 1px. Применяется в рантайме
    и в кэш не пишется: кэш хранит оригинал без позиции, а результат
    ресемплится лениво под тот размер, который запросили.
    """
    src = src.convert("RGBA")
    tw, th = size
    k = min(tw / src.width, th / src.height) * scale
    nw, nh = max(1, round(src.width * k)), max(1, round(src.height * k))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    dx, dy = (tw - nw) // 2 + int(nudge[0]), (th - nh) // 2 + int(nudge[1])
    # часть курсора может уехать за край холста — Roblox обрежет это корректно
    out.paste(resized, (dx, dy))  # без маски: сохраняет альфу
    return out


def apply_cursor(version_dir: Path, png_path, names=None, scale=1.0, nudge=(0, 0)):
    """Подменяет выбранные файлы. Возвращает (применено, пропущено)."""
    names = names or DEFAULT_FILES
    kb = version_dir / REL
    backup_originals(version_dir)
    done, skipped = [], []
    with Image.open(png_path) as im:
        src = im.convert("RGBA")
    for name in names:
        target = kb / name
        if not target.exists():
            skipped.append(name)
            continue
        size = original_size(version_dir, name)
        fit_cursor(src, size, scale, nudge).save(target, "PNG")
        done.append(name)
    return done, skipped


def restore_originals(version_dir: Path):
    bdir = BACKUP_DIR / version_dir.name
    restored = []
    for name in FILES:
        b = bdir / name
        if b.exists():
            shutil.copy2(b, version_dir / REL / name)
            restored.append(name)
    return restored
