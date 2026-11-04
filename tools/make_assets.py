"""
tools/make_assets.py — генератор вшитых ресурсов.

Собирает:
  assets/cursors/*.png      28 курсоров, 128×128 RGBA, хотспот = центр
  assets/cursors/manifest.json  индекс + SHA-256 каждого файла
  assets/icons/icon.ico     иконка приложения (7 размеров)

Запуск:  python tools/make_assets.py

Хотспот. cursor_core.fit_cursor() центрирует картинку на холсте 64×64, поэтому
хотспот обязан совпадать с центром исходного изображения. Все курсоры здесь
нарисованы так, что наконечник стрелки стоит ровно в центре холста. Это тот же
контракт, что и у osu!-скинов, и он же зашит в подпись «Хотспот = центр».
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_CURSORS = ROOT / "assets" / "cursors"
OUT_ICON = ROOT / "assets" / "icons" / "icon.ico"
ICON_SOURCE = ROOT / "assets" / "icons" / "icon-source.png"

SIZE = 128          # сторона исходного PNG курсора
SS = 4              # суперсэмплинг: рисуем в SIZE*SS и ужимаем
CENTER = SIZE // 2  # хотспот

# Курсоры, скачанные tools/fetch_osu.py, по умолчанию остаются в бандле
# (решение 2026-10-21). --no-osu удаляет их и оставляет только свой арт.
KEEP_OSU = "--no-osu" not in sys.argv

# ────────────────────────────────────────────────────────────────────────────
# Геометрия. Все координаты — в системе SIZE (128), потом умножаются на SS.
# Наконечник стрелки = (CENTER, CENTER).
# ────────────────────────────────────────────────────────────────────────────

# классическая стрелка: наконечник (0,0), тело уходит вправо-вниз
ARROW = [(0, 0), (0, 62), (22, 45), (38, 80), (52, 74), (36, 40), (62, 40)]
# тонкий вариант — тот же силуэт, тонкий хвост
ARROW_THIN = [(0, 0), (0, 58), (20, 44), (32, 78), (43, 73), (32, 40), (56, 40)]
# клинок
BLADE = [(0, 0), (66, 50), (36, 52), (44, 78), (33, 84), (24, 56)]

ARROW_SCALE = 0.72


def _scaled(pts, scale, dx, dy):
    return [(dx + x * scale, dy + y * scale) for x, y in pts]


def _circle(cx, cy, r):
    return [(cx, cy)]


# ────────────────────────────────────────────────────────────────────────────
# Каталог. Совпадает с designs: те же имена, категории и теги.
# shape: arrow | thin | blade | pixel | spark | cross | ring | dot
# ────────────────────────────────────────────────────────────────────────────
CATALOG = [
    # id,          slug,                name,            cat,        shape,     fill,     stroke,   glow,               deco,     tags
    ("classic-arrow", "Classic Arrow", "Minimal", "arrow",  "#E8ECF2", "#0A0C10", None,               None,    ["базовая стрелка Roblox без прикрас — светлая, с тёмной обводкой"]),
    ("neon-blue", "Neon Blue",     "Neon",    "arrow",  "#35A0FF", "#0A2E5C", "#35A0FF",         "halo",   ["классическая стрелка с синим свечением и пунктирным ореолом"]),
    ("neon-green", "Neon Green",    "Neon",    "arrow",  "#2BD98A", "#06331F", "#2BD98A",         "halo",   ["то же, но зелёное свечение — читается на тёмном фоне"]),
    ("crimson-blade", "Crimson Blade", "Gaming",  "blade",  "#E03131", "#3D0A0A", "224,49,49",       "none",   ["красный клинок вместо стрелки, угловатый силуэт"]),
    ("void-edge", "Void Edge",     "Minimal", "thin",   "#0B0E14", "#E8ECF2", None,               None,    ["тонкая чёрная стрелка со светлой обводкой — для минимализма"]),
    ("pixel-knight", "Pixel Knight",  "Pixel",   "pixel",  "#C9D4E2", "#0A0C10", None,               None,    ["пиксельная лесенка на сетке 4 px, без сглаживания"]),
    ("sakura", "Sakura",        "Anime",   "spark",  "#FF8FB1", "#4A0E24", None,               None,    ["четырёхлучевая звезда бледно-розовая, как лепесток"]),
    ("toxic-drip", "Toxic Drip",    "Neon",    "arrow",  "#A3E635", "#1F2E05", "#A3E635",         None,    ["кислотно-зелёная стрелка с заметным ореолом"]),
    ("arctic-frost", "Arctic Frost",  "Nature",  "spark",  "#BAE6FD", "#0B4A6F", None,               None,    ["холодная голубая звезда на прозрачном фоне"]),
    ("gold-saber", "Gold Saber",    "Gaming",  "blade",  "#F5C542", "#3D2E05", "245,197,66",      "none",   ["золотой клинок с тёплым свечением по краю"]),
    ("target-lock", "Target Lock",   "Utility", "cross",  "",        "#E8ECF2", None,               "target", ["прицел из четырёх уголков и перекрестья — читается в MM2"]),
    ("carbon-fiber", "Carbon Fiber",  "Minimal", "arrow",  "#2A303C", "#7C8798", None,               None,    ["тёмно-серая стрелка с матовой обводкой, без свечения"]),
    ("plasma-bloom", "Plasma Bloom",  "Neon",    "ring",   "",        "#35A0FF", "#35A0FF",         "halo",   ["кольцо с точкой в центре и мягким синим ореолом"]),
    ("shadow-fang", "Shadow Fang",   "Gaming",  "blade",  "#1F2430", "#9AA3B2", None,               "none",   ["почти чёрный клинок, виден только на светлом фоне"]),
    ("azure-comet", "Azure Comet",   "Nature",  "spark",  "#38BDF8", "#07334D", "#38BDF8",         None,    ["звезда цвета неба с двойным свечением"]),
    ("magenta-pulse", "Magenta Pulse", "Neon",    "arrow",  "#F472B6", "#4A0B2E", "#F472B6",         "halo",   ["розовая стрелка в розовом круге — заметна в тёмном интерфейсе"]),
    ("steel-reticle", "Steel Reticle", "Utility", "cross",  "",        "#94A3B8", None,               "target", ["прицел из уголков без перекрестья, стальной серый"]),
    ("ember", "Ember",         "Gaming",  "arrow",  "#FF7A18", "#3D1405", "255,122,24",      "none",   ["оранжевая стрелка с тёплыем свечением, форма ближе к классике"]),
    ("cyber-ghost", "Cyber Ghost",   "Utility", "spark",  "#22D3EE", "#063B45", "#22D3EE",         None,    ["бирюзовая звезда в стиле неоновой вывески"]),
    ("frost-nova", "Frost Nova",    "Neon",    "ring",   "",        "#7DD3FC", "#7DD3FC",         "halo",   ["холодное кольцо с голубым ореолом"]),
    ("blood-moon", "Blood Moon",    "Gaming",  "dot",    "",        "#DC2626", "#DC2626",         "halo",   ["красная точка в тонком кольце — минималистичный прицел"]),
    ("lime-circuit", "Lime Circuit",  "Pixel",   "pixel",  "#84CC16", "#14260A", None,               None,    ["пиксельная лесенка кислотно-зелёного цвета"]),
    ("obsidian", "Obsidian",      "Minimal", "arrow",  "#111827", "#5A6675", None,               None,    ["стрелка почти в цвет фона, видна только по обводке"]),
    ("candy-rush", "Candy Rush",    "Anime",   "spark",  "#FB7185", "#4A0F16", None,               None,    ["розовая звезда, самая яркая в каталоге"]),
    ("laser-sight", "Laser Sight",   "Utility", "cross",  "",        "#FF3B30", None,               "target", ["красный прицел из перекрестья и уголков — для MM2"]),
    ("dragon-scale", "Dragon Scale",  "Gaming",  "blade",  "#059669", "#022C22", "5,150,105",       "none",   ["зелёный клинок с тёмной обводкой, форма «чешуйки»"]),
    ("sunset-grid", "Sunset Grid",   "Pixel",   "pixel",  "#FB923C", "#3D1505", None,               None,    ["пиксельная лесенка оранжевого цвета"]),
    ("deep-space", "Deep Space",    "Nature",  "dot",    "",        "#93C5FD", "#93C5FD",         "halo",   ["голубая точка в кольце с далёким ореолом"]),
]


def _rgb(spec: str):
    if not spec:
        return None
    if spec.startswith("#"):
        h = spec.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(int(x) for x in spec.split(","))


def _star(cx, cy, r_out, r_in, points=4):
    """N-лучевая звезда с центром в (cx, cy)."""
    import math
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.pi * i / points - math.pi / 2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _pixel_arrow(px):
    """Стрелка по сетке 4·px: диагональная лесенка, читается как пиксель-арт."""
    u = px
    return [(0, 0), (7 * u, 0), (7 * u, 7 * u), (14 * u, 7 * u), (14 * u, 14 * u),
            (21 * u, 14 * u), (21 * u, 21 * u), (28 * u, 21 * u), (28 * u, 28 * u),
            (21 * u, 28 * u), (21 * u, 35 * u), (14 * u, 35 * u), (14 * u, 28 * u),
            (7 * u, 28 * u), (7 * u, 21 * u), (0, 21 * u)]


def draw_cursor(shape: str, fill, stroke, glow, deco) -> Image.Image:
    """Отрисовка одного курсора. Возвращает RGBA SIZE×SIZE."""
    n = SIZE * SS
    c = CENTER * SS
    big = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    sw = (1.6 if shape in ("arrow", "blade") else 1.4) * SS

    if shape == "spark":
        pts = [(c + (x - SIZE // 2) * SS, c + (y - SIZE // 2) * SS)
               for x, y in _star(SIZE // 2, SIZE // 2, 54, 15, 4)]
        d.polygon(pts, fill=(fill or (0, 0, 0)) + (255,), outline=(stroke or (0, 0, 0)) + (255,))
        d.line(pts + [pts[0]], fill=(stroke or (0, 0, 0)) + (255,), width=int(sw), joint="curve")

    elif shape == "cross":
        w = int(4.2 * SS)
        d.line([(c, c - 44 * SS), (c, c + 44 * SS)], fill=(stroke or (255, 255, 255)) + (255,), width=w)
        d.line([(c - 44 * SS, c), (c + 44 * SS, c)], fill=(stroke or (255, 255, 255)) + (255,), width=w)
        for p in ((c - 46 * SS, c - 46 * SS), (c + 46 * SS, c - 46 * SS),
                  (c + 46 * SS, c + 46 * SS), (c - 46 * SS, c + 46 * SS)):
            pass

    elif shape == "ring":
        r = int(34 * SS)
        d.ellipse([c - r, c - r, c + r, c + r], outline=(stroke or (255, 255, 255)) + (255,), width=int(5.4 * SS))
        rr = int(12 * SS)
        d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=(stroke or (255, 255, 255)) + (140,))

    elif shape == "dot":
        r = int(34 * SS)
        d.ellipse([c - r, c - r, c + r, c + r], outline=(stroke or (255, 255, 255)) + (110,), width=int(1.8 * SS))
        rr = int(15 * SS)
        d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=(stroke or (255, 255, 255)) + (255,))

    elif shape == "pixel":
        u = 2.6 * SS
        pts = [(c + x, c + y) for x, y in _pixel_arrow(u)]
        d.polygon(pts, fill=(fill or (0, 0, 0)) + (255,))
        d.line(pts + [pts[0]], fill=(stroke or (0, 0, 0)) + (255,), width=int(1.9 * SS))

    else:  # arrow | thin | blade
        src = {"arrow": ARROW, "thin": ARROW_THIN, "blade": BLADE}[shape]
        scale = ARROW_SCALE if shape != "blade" else 0.80
        pts = [(c + x * scale * SS, c + y * scale * SS) for x, y in src]
        d.polygon(pts, fill=(fill or (0, 0, 0)) + (255,))
        d.line(pts + [pts[0]], fill=(stroke or (0, 0, 0)) + (255,), width=int(sw), joint="curve")

    # deco — рисуется под основной формой
    if deco == "halo":
        r = int(60 * SS)
        h = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        ImageDraw.Draw(h).ellipse([c - r, c - r, c + r, c + r],
                                 outline=((glow or stroke or (255, 255, 255)) + (150,)), width=int(1.2 * SS))
        big = Image.alpha_composite(big, h)
    elif deco == "target":
        col = (glow or stroke or (255, 255, 255)) + (215,)
        g = ImageDraw.Draw(big)
        k, L = 50 * SS, 12 * SS
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            g.line([(c + sx * k, c + sy * k), (c + sx * k, c + sy * (k - L))], fill=col, width=int(1.6 * SS))
            g.line([(c + sx * k, c + sy * k), (c + sx * (k - L), c + sy * k)], fill=col, width=int(1.6 * SS))

    # glow — размытая копия формы снизу. Берём только АЛЬФУ размытия,
    # красим её в цвет свечения и подкладываем под резкую форму.
    if glow:
        gcol = glow + (255,)
        blurred = layer.filter(ImageFilter.GaussianBlur(3.0 * SS))
        alpha = blurred.split()[3].point(lambda v: int(v * 0.70))
        glow_layer = Image.new("RGBA", (n, n), gcol)
        glow_layer.putalpha(alpha)
        big = Image.alpha_composite(big, glow_layer)

        halo = blurred.filter(ImageFilter.GaussianBlur(7.0 * SS))
        wide = Image.new("RGBA", (n, n), gcol)
        wide.putalpha(halo.split()[3].point(lambda v: int(v * 0.34)))
        big = Image.alpha_composite(big, wide)

    big = Image.alpha_composite(big, layer)

    out = big.resize((SIZE, SIZE), Image.LANCZOS)
    return out


def make_icon() -> None:
    """Иконка приложения.

    Есть assets/icons/icon-source.png (арт автора) — .ico собирается из него.
    Нет — рисуется запасная: графитовая плитка с акцентной стрелкой.
    """
    if ICON_SOURCE.is_file():
        with Image.open(ICON_SOURCE) as src:
            img = src.convert("RGBA")
        OUT_ICON.parent.mkdir(parents=True, exist_ok=True)
        img.save(OUT_ICON, format="ICO",
                 sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
        return
    base = 1024
    img = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, base - 1, base - 1], radius=224, fill=(22, 26, 35, 255),
                        outline=(58, 66, 80, 255), width=6)
    d.rounded_rectangle([10, 10, base - 11, base - 11], radius=214, outline=(255, 255, 255, 16), width=4)

    # акцентная стрелка, хотспот не важен — это иконка, а не курсор
    s = base / 128.0
    pts = [(300 + x * 3.3 * s, 260 + y * 3.3 * s) for x, y in ARROW]
    shadow = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(pts, fill=(0, 0, 0, 160))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(26)))
    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=(53, 160, 255, 255))
    d.line(pts + [pts[0]], fill=(6, 18, 31, 255), width=14, joint="curve")

    OUT_ICON.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_ICON, format="ICO",
             sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    # консоль Windows по умолчанию cp1251 и не печатает «→»
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    OUT_CURSORS.mkdir(parents=True, exist_ok=True)
    studio_names = {f"{slug}.png" for slug, *_ in CATALOG}
    for old in OUT_CURSORS.glob("*.png"):
        # чужие файлы (osu-*.png и др.) не трогаем: их качает tools/fetch_osu.py,
        # а этот скрипт раньше сносил их вместе с манифестом
        if old.name in studio_names:
            old.unlink()

    items = []
    for slug, name, cat, shape, fill_h, stroke_h, glow_h, deco, tags in CATALOG:
        img = draw_cursor(shape, _rgb(fill_h), _rgb(stroke_h), _rgb(glow_h), deco)
        path = OUT_CURSORS / f"{slug}.png"
        img.save(path, "PNG", optimize=True)
        items.append({
            "id": slug,
            "name": name,
            "category": cat,
            "tags": tags,
            "blurb": tags[0] if tags else "",
            "file": path.name,
            "w": SIZE,
            "h": SIZE,
            "hotspot": [CENTER, CENTER],
            "sha256": sha256_of(path),
            "bytes": path.stat().st_size,
        })
        print(f"  {path.name:24s} {path.stat().st_size:>6d} B  {sha256_of(path)[:16]}")

    # Курсоры osu!, скачанные tools/fetch_osu.py, переживают регенерацию:
    # build.py зовёт этот скрипт без флагов, и без этого каждая сборка
    # молча выкидывала бы их из exe. Права на арт остаются у авторов
    # osuskinner — README говорит об этом прямо.
    if KEEP_OSU:
        try:
            prev = json.loads((OUT_CURSORS / "manifest.json").read_text(encoding="utf-8"))
            kept = [it for it in prev.get("items", [])
                    if str(it.get("id", "")).startswith("osu-")
                    and (OUT_CURSORS / str(it.get("file", ""))).is_file()]
        except Exception:
            kept = []
        items = items + kept
    else:
        stale = [p for p in OUT_CURSORS.glob("osu-*.png")]
        for p in stale:
            p.unlink()
        if stale:
            print(f"  удалено osu-*.png: {len(stale)} "
                  f"(чтобы вернуть — tools/fetch_osu.py без --no-osu)")
    mixed = bool(kept) if KEEP_OSU else False
    manifest = {
        "schema": 1,
        "source": "bundled+osuskinner" if mixed else "bundled",
        "license": ("mixed: CC0-1.0 (studio) + osuskinner.com (osu!)"
                    if mixed else "CC0-1.0"),
        "canvas": SIZE,
        "hotspot_rule": "center",
        "count": len(items),
        "items": items,
    }
    mf = OUT_CURSORS / "manifest.json"
    mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    make_icon()
    print(f"\n{len(items)} курсоров  → {OUT_CURSORS}")
    print(f"манифест         → {mf}")
    print(f"иконка           → {OUT_ICON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())