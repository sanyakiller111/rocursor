"""
roblox_paths.py — карта того, где Roblox держит свои ресурсы.

Всё, что здесь написано, проверено на живой установке Roblox: пути сняты
с диска, а не взяты из документации. Где доказанное расходится с ожидаемым,
это отмечено в поле caveat — чтобы интерфейс мог сказать правду, а не
красивое предположение.

Два канала применения:

  direct      пишем прямо в папку версии Roblox. Работает всегда, но папка
              версии меняется при каждом обновлении клиента — ресурсы слетают.

  bloxstrap   пишем в %LOCALAPPDATA%\\Bloxstrap\\Modifications. Bloxstrap
              копирует оверлей в папку версии при запуске Roblox, а удалённый
              из Modifications файл при следующем запуске возвращает в
              исходном виде. Набор переживает обновления клиента сам.
"""
from __future__ import annotations

import os
import winreg
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# Ключи реестра, где Roblox держит путь к установленному клиенту.
# На практике значения в них расходятся между собой, поэтому проверяем
# все и берём тот, что реально лежит на диске.
REG_ROBLOX_KEYS = (
    r"Software\Classes\roblox-player\shell\open\command",
    r"Software\Classes\roblox\shell\open\command",
)


@dataclass
class Kind:
    key: str
    label: str
    path: str                    # путь внутри версии Roblox
    exts: tuple[str, ...]
    hint: str                    # что вообще меняет этот класс файлов
    size_hint: str = ""
    caveat: str = ""
    files: tuple[str, ...] = ()  # ожидаемые имена, пусто если неизвестно
    crosshair: bool = False

    def rel(self, filename: str) -> PurePosixPath:
        # В актуальных версиях MouseLockedCursor.png лежит на уровень выше
        # остальных курсоров: content/textures/, а не .../Cursors/KeyboardMouse/.
        if self.key == KIND_CURSOR and filename.lower() == "mouselockedcursor.png":
            return PurePosixPath("content/textures") / filename
        if self.key == KIND_MATERIAL:
            return PurePosixPath(self.path) / material_subdir(filename) / filename
        return PurePosixPath(self.path) / filename

    def target(self, version_dir: Path) -> Path:
        return version_dir / self.path


KIND_CURSOR = "cursor"
KIND_CROSSHAIR = "crosshair"
KIND_SKY = "sky"
KIND_SOUND = "sound"
KIND_FONT = "font"
KIND_UI = "ui"
KIND_EDITOR = "editor"
KIND_MATERIAL = "material"

# Текстуры материалов, которые ещё лежат на диске. Остальные (трава, кирпич,
# дерево…) клиент с 2022 года качает из сети — их файлами не заменить.
# Имена уникальны, поэтому подпапку можно вывести из имени, а validate()
# по-прежнему принимает только голое имя файла.
MATERIAL_PLASTIC = ("diffuse.dds", "normal.dds", "normaldetail.dds")
MATERIAL_STUDS = ("studs.dds",)
MATERIAL_WATER = tuple(f"normal_{i:02d}.dds" for i in range(1, 33))


def material_subdir(filename: str) -> str:
    name = filename.lower()
    if name in MATERIAL_PLASTIC:
        return "plastic"
    if name in MATERIAL_WATER:
        return "water"
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# Категории. Порядок — это порядок вкладок в интерфейсе.
# ─────────────────────────────────────────────────────────────────────────────
KINDS: dict[str, Kind] = {
    KIND_CURSOR: Kind(
        key=KIND_CURSOR,
        label="Курсоры",
        path="content/textures/Cursors/KeyboardMouse",
        exts=(".png",),
        hint="Стрелки, которые видит игрок. Roblox читает их напрямую из папки "
             "версии; размер берётся от оригинала (обычно 64×64).",
        size_hint="PNG, RGBA; размер оригинала, обычно 64×64",
        files=(
            "ArrowCursor.png",
            "ArrowFarCursor.png",
            "IBeamCursor.png",
            "MouseLockedCursor.png",
        ),
        caveat="MouseLockedCursor.png в текущей версии лежит отдельно, "
               "в content/textures/ — приложение учитывает это при установке.",
    ),
    KIND_CROSSHAIR: Kind(
        key=KIND_CROSSHAIR,
        label="Прицел",
        path="content/textures",
        exts=(".png",),
        hint="Прицел в Roblox рисует сам клиент из MouseLockedCursor и "
             "скриптовых настроек. Отдельной текстуры прицела нет.",
        size_hint="PNG, RGBA; размер оригинала, обычно 32×32",
        files=("MouseLockedCursor.png",),
        crosshair=True,
        caveat="Прицел рисует клиент. Подмена PNG меняет вид иконки захвата, "
               "но не форму прицела в игре — за это отвечают скрипты и "
               "настройки курсора. Обещать иное нельзя.",
    ),
    KIND_SKY: Kind(
        key=KIND_SKY,
        label="Небо",
        path="PlatformContent/pc/textures/sky",
        exts=(".tex",),
        hint="Шесть граней кубической панорамы плюс внутренние небеса. "
             "Формат — DDS/DXT1 с цепочкой мипов, расширение .tex.",
        size_hint="DDS/DXT1, 6 граней × мипы",
        files=(
            "sky512_ft.tex", "sky512_bk.tex", "sky512_lf.tex",
            "sky512_rt.tex", "sky512_up.tex", "sky512_dn.tex",
            "indoor512_ft.tex", "indoor512_bk.tex", "indoor512_lf.tex",
            "indoor512_rt.tex", "indoor512_up.tex", "indoor512_dn.tex",
        ),
        caveat="Имя файла врёт. sky512_* — реально 1024×1024, 11 мипов; "
               "indoor512_* — 512×512, 10 мипов. Размер бери из заголовка, "
               "не из имени.",
    ),
    KIND_SOUND: Kind(
        key=KIND_SOUND,
        label="Звуки",
        path="content/sounds",
        exts=(".ogg", ".mp3", ".wav"),
        hint="Звуки Roblox лежат плоско, без подпапок по назначению. "
             "Имя файла — это идентификатор, на который ссылаются скрипты.",
        size_hint="OGG Vorbis — основной формат Roblox",
        caveat="Формат в названии папки не указан: в установке встречаются "
               "ogg, mp3 и wav. Клиент умеет не всё — при подмене на mp3 "
               "часть звуков перестаёт играть.",
    ),
    KIND_FONT: Kind(
        key=KIND_FONT,
        label="Шрифты",
        path="content/fonts",
        exts=(".ttf", ".otf"),
        hint="Шрифты Roblox для встроенного текста и нативных элементов. "
             "Шрифт, подключённый через FontFace в студии, лежит не здесь.",
        size_hint="TTF/OTF",
        caveat="Шрифты из студии лежат в месте установки игры, а не в "
               "content/fonts. Здесь меняются только системные шрифты клиента.",
    ),
    KIND_UI: Kind(
        key=KIND_UI,
        label="Интерфейс",
        path="PlatformContent/pc/textures/ui",
        exts=(".png",),
        hint="Текстуры интерфейса Roblox: рамки, кнопки, иконки меню.",
        size_hint="PNG, RGBA",
        caveat="Отрисовка интерфейса частично векторная. Часть PNG лежит в "
               "слотах интерфейса и подменяется надёжно, часть перерисовывается "
               "поверх. Проверяй каждый конкретный файл.",
    ),
    KIND_EDITOR: Kind(
        key=KIND_EDITOR,
        label="Редактор",
        path="content/textures",
        exts=(".png",),
        hint="Текстуры студии: панели инструментов, иконки редактора, "
             "превью ресурсов.",
        size_hint="PNG, RGBA",
        caveat="Студия кэширует текстуры. После подмены может понадобиться "
               "полный перезапуск Roblox Studio, а не только закрытие окна.",
    ),
    KIND_MATERIAL: Kind(
        key=KIND_MATERIAL,
        label="Текстуры",
        path="PlatformContent/pc/textures",
        exts=(".dds",),
        hint="Локальные текстуры материалов: пластик (plastic/), атлас "
             "поверхностей studs.dds и карты нормалей воды (water/).",
        size_hint="DDS DXT1/DXT5 с мипами",
        files=MATERIAL_PLASTIC + MATERIAL_STUDS + MATERIAL_WATER,
        caveat="Остальные материалы клиент качает из сети и держит в кэше — "
               "менять можно только пластик, студы и воду.",
    ),
}

ORDER = (KIND_CURSOR, KIND_CROSSHAIR, KIND_SKY, KIND_SOUND, KIND_UI,
         KIND_FONT, KIND_EDITOR, KIND_MATERIAL)


def get(key: str) -> Kind:
    try:
        return KINDS[key]
    except KeyError:
        raise KeyError(f"неизвестная категория: {key}") from None


def kind_for_path(rel: str) -> str | None:
    """Определяет категорию по относительному пути внутри версии Roblox."""
    rel = rel.replace("\\", "/").lower()
    best, best_len = None, -1
    for key in ORDER:
        k = KINDS[key]
        p = k.path.lower() + "/"
        if rel.startswith(p) and len(p) > best_len:
            best, best_len = key, len(p)
    return best


def validate(kind_key: str, filename: str) -> str | None:
    """
    Проверяет имя файла для категории. Возвращает причину отказа или None.

    Это единственная точка, где решается, можно ли вообще класть файл
    в Roblox. Через неё проходят и импорт ZIP, и прямая установка.
    """
    k = get(kind_key)
    if not filename:
        return "пустое имя файла"
    if "/" in filename or "\\" in filename:
        return "в имени файла не должно быть пути"
    if ".." in filename:
        return "в имени файла не должно быть '..'"
    name = filename.lower()
    if not any(name.endswith(e) for e in k.exts):
        return f"расширение не подходит категории «{k.label}» (ожидается {', '.join(k.exts)})"
    if k.files and name not in [f.lower() for f in k.files]:
        allowed = ", ".join(k.files[:4])
        return f"файл не из списка известных для «{k.label}» ({allowed}, …)"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Канал Bloxstrap
# ─────────────────────────────────────────────────────────────────────────────
BLOXSTRAP_SUBDIR = "Bloxstrap"
BLOXSTRAP_MODS = "Modifications"
BLOXSTRAP_VERSIONS = "Versions"


def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def bloxstrap_root() -> Path:
    return _localappdata() / BLOXSTRAP_SUBDIR


def bloxstrap_mods() -> Path:
    return bloxstrap_root() / BLOXSTRAP_MODS


def bloxstrap_versions() -> Path:
    return bloxstrap_root() / BLOXSTRAP_VERSIONS


def bloxstrap_installed() -> bool:
    """
    Bloxstrap считается установленным, если есть папка Versions.

    Наличия самой папки Modifications мало: её может не быть, пока не
    применён ни один мод, и каталог создастся при первой записи.
    """
    return bloxstrap_versions().is_dir()


BACKENDS = ("direct", "bloxstrap")

BACKEND_LABEL = {
    "direct": "Прямой (папка Roblox)",
    "bloxstrap": "Bloxstrap (переживает обновления)",
}

BACKEND_HINT = {
    "direct": "Файлы пишутся прямо в папку версии Roblox. При обновлении "
              "клиента папка меняется и ресурсы слетают.",
    "bloxstrap": "Файлы кладутся в %LOCALAPPDATA%\\Bloxstrap\\Modifications. "
                 "Bloxstrap применяет их при каждом запуске и возвращает "
                 "оригинал, когда файл убран из папки.",
}


def backend_available(backend: str) -> bool:
    if backend == "direct":
        return True
    if backend == "bloxstrap":
        return bloxstrap_installed()
    return False


def destination(backend: str, version_dir: Path, kind_key: str, filename: str) -> Path:
    """Куда физически ложится файл при выбранном канале."""
    if backend == "bloxstrap":
        return bloxstrap_mods() / get(kind_key).rel(filename)
    return version_dir / get(kind_key).rel(filename)


# ─────────────────────────────────────────────────────────────────────────────
# Лицензии — чтобы набор нельзя было распространять, не подумав
# ─────────────────────────────────────────────────────────────────────────────
LICENSES = {
    "CC0-1.0": "общественное достояние, можно всё",
    "CC-BY-4.0": "можно с указанием автора",
    "CC-BY-SA-4.0": "как CC-BY, но производные под той же лицензией",
    "CC-BY-NC-4.0": "нельзя для коммерческого использования",
    "MIT": "свободная, с указанием автора",
    "OFL-1.1": "SIL Open Font License: шрифт можно распространять, не продавая отдельно",
    "Apache-2.0": "свободная, с указанием автора и лицензии",
    "GPL-3.0": "производное обязано быть под GPL",
    "PROPRIETARY": "права автора, распространение запрещено",
    "UNKNOWN": "лицензия не указана — распространять нельзя",
}

# Что можно включать в сборку приложения без отдельного разрешения
BUNDLE_SAFE = {"CC0-1.0", "MIT", "OFL-1.1", "Apache-2.0"}

# Что нельзя: лицензия запрещает или требует согласования
BUNDLE_BLOCKED = {"CC-BY-NC-4.0", "PROPRIETARY", "UNKNOWN", "GPL-3.0"}


def bundle_allowed(license_id: str) -> bool:
    return license_id in BUNDLE_SAFE


def license_note(license_id: str) -> str:
    return LICENSES.get(license_id, "неизвестная лицензия — считай её запрещённой")