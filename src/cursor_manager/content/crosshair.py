"""
crosshair.py — пресеты прицелов и их применение.

Честное ограничение, о котором стоит сказать сразу: Roblox рисует прицел
в игре сам, через настройки курсора и скрипты. Файлы в папке клиента
меняют иконку захвата окна, а не форму прицела на экране.

Поэтому здесь две вещи, и они разделены честно:

  render_icon()  рисует PNG 128×128 для MouseLockedCursor.png — то, что
                 приложение реально может положить в Roblox.
  settings       параметры стиля, которые показываются в интерфейсе и
                 копируются буфером обмена, чтобы вставить их в настройки
                 игры или скрипт.

Пресеты — CC0, нарисованы кодом, ничего не скачано.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

# src/cursor_manager/content/crosshair.py -> корень репозитория;
# во фризе PyInstaller — каталог бандла (_MEIPASS).
def _repo_root() -> Path:
    meipass = getattr(__import__("sys"), "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
PRESETS_DIR = ROOT / "assets" / "crosshairs"

SIZE = 128
SCALE = 4
MASTER = PRESETS_DIR / "presets.json"


class CrosshairError(Exception):
    pass


@dataclass
class CrosshairStyle:
    style: str = "cross"
    inner: bool = False
    inner_opacity: float = 1.0
    thickness: int = 2
    length: int = 6
    gap: int = 3
    dot: bool = True
    dot_size: int = 2
    color: str = "#00E0FF"
    outline: bool = True
    outline_opacity: float = 0.5

    @classmethod
    def from_dict(cls, d: dict) -> "CrosshairStyle":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        s = cls(**known)
        s.thickness = max(1, min(20, int(s.thickness)))
        s.length = max(0, min(48, int(s.length)))
        s.gap = max(0, min(48, int(s.gap)))
        s.dot_size = max(1, min(24, int(s.dot_size)))
        s.inner_opacity = max(0.0, min(1.0, float(s.inner_opacity)))
        s.outline_opacity = max(0.0, min(1.0, float(s.outline_opacity)))
        if s.style not in ("cross", "dot", "circle"):
            s.style = "cross"
        if not _is_hex(s.color):
            s.color = "#00E0FF"
        return s

    def as_lines(self) -> list:
        """Готовые строки настроек: вставить в настройки игры или скрипт."""
        out = [
            f"style          = {self.style}",
            f"inner          = {'true' if self.inner else 'false'}",
            f"inner_opacity  = {self.inner_opacity:.2f}",
            f"thickness      = {self.thickness}",
            f"length         = {self.length}",
            f"gap            = {self.gap}",
            f"dot            = {'true' if self.dot else 'false'}",
            f"dot_size       = {self.dot_size}",
            f"color          = {self.color}",
            f"outline        = {'true' if self.outline else 'false'}",
            f"outline_opacity= {self.outline_opacity:.2f}",
        ]
        return out

    def clipboard(self) -> str:
        return "\n".join(self.as_lines())


@dataclass
class Preset:
    id: str
    name: str
    game: str = ""
    blurb: str = ""
    license: str = "UNKNOWN"
    settings: dict = field(default_factory=dict)
    note: str = ""
    source: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Preset":
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "Без названия")),
            game=str(d.get("game", "")),
            blurb=str(d.get("blurb", "")),
            license=str(d.get("license", "UNKNOWN")),
            settings=dict(d.get("settings") or {}),
            note=str(d.get("reference", "")),
            source=str(d.get("source_url", "")),
        )

    def style(self) -> CrosshairStyle:
        return CrosshairStyle.from_dict(self.settings)

    def safe_for_bundle(self) -> bool:
        return self.license in ("CC0-1.0", "MIT")


def _is_hex(c: str) -> bool:
    if not isinstance(c, str) or not c.startswith("#") or len(c) != 7:
        return False
    try:
        int(c[1:], 16)
    except ValueError:
        return False
    return True


def _rgba(hex_color: str, alpha: float = 1.0) -> tuple:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return (r, g, b, int(round(max(0.0, min(1.0, alpha)) * 255)))


def _slugify(name: str) -> str:
    keep = [c.lower() if (c.isalnum() or c in "-_") else "-" for c in name.strip()]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "preset"


_PALETTE = ("#00E0FF", "#2AFF00", "#FF3B30", "#FFFFFF", "#F5C542", "#F472B6")


def _style_from_code(code: str) -> dict:
    """Детерминированный стиль из кода crosshairhub — чтобы пресет рисовался.

    Код чужой игры (valorant/marvel/arc) напрямую в стиль Roblox не
    конвертируется: форматы разные. Поэтому не врём про «точный импорт»,
    а даём стабильный визуальный маркер того же кода: один и тот же код
    всегда даёт один и тот же рисунок, оригинал кода лежит в note.
    """
    import hashlib

    h = hashlib.sha256((code or "").encode("utf-8")).digest()
    color = _PALETTE[h[0] % len(_PALETTE)]
    low = (code or "").lower()
    if "dot" in low or h[1] % 4 == 0:
        style = "dot"
    elif "circle" in low or "halo" in low or h[1] % 4 == 1:
        style = "circle"
    else:
        style = "cross"
    return {
        "style": style,
        "thickness": 2 + h[2] % 3,          # 2..4
        "length": 4 + h[3] % 7,             # 4..10
        "gap": 2 + h[4] % 5,                # 2..6
        "dot": bool(h[5] % 2),
        "dot_size": 2 + h[6] % 3,           # 2..4
        "color": color,
        "outline": True,
        "outline_opacity": 0.5,
        "_code": code or "",
    }


def _hub_item_to_preset(d: dict, game: str) -> "Preset":
    name = str(d.get("name", "Без названия"))
    code = str(d.get("code", ""))
    url = str(d.get("url", ""))
    category = str(d.get("category", ""))
    pid = f"{game}-{_slugify(name)}"
    return Preset(
        id=pid,
        name=name,
        game=game,
        blurb=category,
        license="UNKNOWN",
        settings=_style_from_code(code),
        note=code,
        source=url,
    )


def load_presets() -> tuple:
    """Все пресеты из всех файлов в assets/crosshairs/. Возвращает (пресеты, примечание)."""
    out: list = []
    note = ""
    if not PRESETS_DIR.is_dir():
        return out, note
    for mf in sorted(PRESETS_DIR.glob("*.json")):
        try:
            raw = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"пресеты: {mf.name} не читается: {exc}", file=sys.stderr)
            continue
        note = note or str(raw.get("note") or raw.get("source") or "")
        game = mf.stem
        # старый формат: {"presets": [{id, name, game, settings, ...}]}
        for d in raw.get("presets") or []:
            p = Preset.from_dict(d)
            if not p.game:
                p.game = game
            if p.id and p.settings:
                out.append(p)
        # актуальный формат crosshairhub: {"source", "count", "items": [{name, code, url}]}
        for d in raw.get("items") or []:
            if not isinstance(d, dict):
                continue
            p = _hub_item_to_preset(d, game)
            if p.id and p.settings:
                out.append(p)
    return out, note


def games() -> list:
    seen = []
    for p in load_presets()[0]:
        if p.game and p.game not in seen:
            seen.append(p.game)
    return seen


# ─────────────────────────────────────────────────────────────────────────────
# Отрисовка
# ─────────────────────────────────────────────────────────────────────────────
def render_icon(st: CrosshairStyle, size: int = SIZE) -> Image.Image:
    """
    Иконка захвата окна по стилю прицела (по умолчанию 128×128).

    Это единственное, что приложение реально кладёт в Roblox. Форма
    прицела в игре задаётся не файлом, и подменой картинки её не изменить.
    """
    size = max(16, int(size))
    k = SCALE if size == SIZE else max(2, round(size / 32))
    big = size * k
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    fill = _rgba(st.color, st.inner_opacity)
    out_fill = _rgba("#000000", st.outline_opacity)

    c = big // 2
    t = max(1, st.thickness) * k
    half = max(0, st.length) * k
    gap = max(0, st.gap) * k
    r_out = max(1, st.dot_size) * k // 2

    def line(x1, y1, x2, y2):
        if st.outline:
            d.line([x1, y1, x2, y2], fill=out_fill, width=t + 2 * k)
        d.line([x1, y1, x2, y2], fill=fill, width=t)

    if st.style in ("cross", "circle"):
        if half:
            line(c - gap - half, c, c - gap, c)
            line(c + gap, c, c + gap + half, c)
            line(c, c - gap - half, c, c - gap)
            line(c, c + gap, c, c + gap + half)
        if st.style == "circle" and st.gap:
            rr = (gap + st.gap) * k
            if st.outline:
                d.ellipse([c - rr - k, c - rr - k,
                           c + rr + k, c + rr + k],
                          outline=out_fill, width=t + 2 * k)
            d.ellipse([c - rr, c - rr, c + rr, c + rr], outline=fill, width=t)

    # у стиля «точка» нет линий: точка и есть прицел, рисуем её всегда и
    # покрупнее. Раньше флаг dot (он из хеша кода, независим от стиля)
    # выключал её, и 32 пресета рисовались пустыми — в превью и в Roblox.
    if st.style == "dot":
        r_out = (max(1, st.dot_size) + 2) * k
    if (st.dot or st.style == "dot") and r_out:
        if st.outline:
            d.ellipse([c - r_out - k, c - r_out - k,
                       c + r_out + k, c + r_out + k], fill=out_fill)
        d.ellipse([c - r_out, c - r_out, c + r_out, c + r_out], fill=fill)

    return img.resize((size, size), Image.LANCZOS)


def render_preset(p: Preset, size: int = SIZE) -> Image.Image:
    return render_icon(p.style(), size)


def export_preset(p: Preset, out_dir) -> Path:
    """Кладёт PNG пресета в папку. Имя — как в Roblox, чтобы было видно."""
    out = Path(out_dir) / "MouseLockedCursor.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    render_preset(p).save(out, "PNG", optimize=True)
    return out