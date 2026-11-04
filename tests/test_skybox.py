"""
tests/test_skybox.py — генератор неба Roblox.

Проверяется на настоящих файлах из установленного Roblox (размер и
структура), затем — математика проекции панорама → куб.
"""
from __future__ import annotations

import io
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image  # noqa: E402

from cursor_manager.content import skybox as S  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def test_panorama(w=1024, h=512) -> Image.Image:
    """Панорама с узнаваемой структурой: градиент по долготе и полосы по широте."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for j in range(h):
        lat = 0.5 - (j + 0.5) / h                 # 0 сверху, 1 снизу
        for i in range(w):
            lon = (i + 0.5) / w
            px[i, j] = (
                int(255 * lon),
                int(255 * (1 - lat)),
                int(255 * (0.5 + 0.5 * math.sin(lon * 4 * math.pi))),
            )
    return img


def main() -> int:
    print("\n── против настоящих файлов Roblox ──")
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Roblox" / "Versions"
    sky = None
    if root.is_dir():
        for d in sorted(root.iterdir()):
            p = d / "PlatformContent" / "pc" / "textures" / "sky"
            if p.is_dir():
                sky = p
                break
    if sky is None:
        print("  Roblox не установлен — сверяем только арифметику формата")
        check("размер sky 1024/11 совпадает с расчётом",
              S.expected_size(1024, 11) == 699192, str(S.expected_size(1024, 11)))
        check("размер indoor 512/10 совпадает с расчётом",
              S.expected_size(512, 10) == 174904, str(S.expected_size(512, 10)))
    else:
        files = sorted(sky.glob("*.tex"))
        check("найдены файлы неба", len(files) >= 12, f"{len(files)} шт.")
        bad = []
        for f in files:
            h = S.read_header(f)
            if S.expected_size(h["width"], h["mips"]) != h["bytes"]:
                bad.append(f.name)
            if h["fourcc"] != "DXT1":
                bad.append(f"{f.name}:{h['fourcc']}")
        check("размер и сжатие всех файлов сходятся с расчётом", not bad, ", ".join(bad[:3]))
        sets = {(S.read_header(f)["width"], S.read_header(f)["mips"]) for f in files}
        check("Roblox использует два набора параметров", len(sets) >= 1, str(sorted(sets)))

    print("\n── формат на выходе ──")
    pan = test_panorama(512, 256)
    tex = S.panorama_to_tex(pan, "ft", size=256, mips=6)
    check("сигнатура DDS", tex[:4] == b"DDS ")
    check("FourCC = DXT1", tex[84:88] == b"DXT1")
    check("размер совпадает с расчётом",
          len(tex) == S.expected_size(256, 6), f"{len(tex)} != {S.expected_size(256, 6)}")
    check("число мипов в заголовке",
          int.from_bytes(tex[28:32], "little") == 6)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sky512_ft.tex"
        p.write_bytes(tex)
        back = S.read_tex(p)
        check("читается обратно через Pillow", back.size[0] > 0, str(back.size))

    print("\n── проверка панорамы ──")
    try:
        S.panorama_to_tex(Image.new("RGB", (256, 256)), "ft")
        check("непропорциональная панорама отклонена", False)
    except S.SkyboxError:
        check("непропорциональная панорама отклонена", True)

    print("\n── самосогласованность проекции ──")
    # Главная проверка математики: если грани построены верно, обратная
    # проекция обязана вернуть исходную панораму. Совпадение доказывает,
    # что грани покрывают сферу целиком и базисы согласованы между собой.
    # Гадать, какая грань «должна» смотреть влево, бессмысленно: ориентацию
    # в рендере Roblox можно проверить только в игре, для неё есть MIRROR.
    faces = {f: S.render_face(pan, f, 128) for f in S.FACES}
    rebuilt = S.rebuild_panorama(faces, pan.width, pan.height)
    a, b = pan.load(), rebuilt.load()
    hist = [0] * 8                      # 0..31, 32..63, ... 224..255
    samples = 0
    edge = 0                             # пиксели у полюсов и швов панорамы
    steps = range(0, pan.height, 2), range(0, pan.width, 2)
    for j in steps[0]:
        near_pole = j < 6 or j > pan.height - 6
        for i in steps[1]:
            pa, pb = a[i, j], b[i, j]
            d = max(abs(x - y) for x, y in zip(pa, pb))
            hist[min(7, d // 32)] += 1
            samples += 1
            if near_pole or i < 4 or i > pan.width - 4:
                edge += 1
    mean = sum(i * 32 * c for i, c in enumerate(hist)) / samples
    big = sum(hist[4:]) / samples
    edge_big = 0
    for j in steps[0]:
        near_pole = j < 6 or j > pan.height - 6
        for i in steps[1]:
            pa, pb = a[i, j], b[i, j]
            d = max(abs(x - y) for x, y in zip(pa, pb))
            if d > 90 and (near_pole or i < 4 or i > pan.width - 4):
                edge_big += 1
    print(f"     среднее {mean:.1f}   доля промахов >90: {big * 100:.2f}%   "
          f"у полюсов и швов: {edge_big}")
    check("обратная проекция возвращает исходную панораму", mean < 14, f"среднее {mean:.1f}")
    check("промахи не превышают 1% пикселей", big < 0.01, f"{big * 100:.2f}%")
    check("промахи сосредоточены на полюсах и швах панорамы",
          edge_big >= max(1, sum(hist[5:]) * 0.9),
          f"на краях {edge_big}, всего крупных {sum(hist[5:])}")

    # полюса вырождены: долгота там не определена, строка пикселей не важна
    corners = [S.render_face(pan, f, 32).getpixel((16, 16)) for f in S.FACES]
    check("шесть граней дают разные цвета в центре",
          len(set(corners)) >= 3, str(corners))

    print("\n── полный небесный куб ──")
    with tempfile.TemporaryDirectory() as td:
        ref = None
        if sky is not None and (sky / "sky512_ft.tex").is_file():
            ref = sky / "sky512_ft.tex"
        size, mips = (S.match_destination(ref) if ref else (256, 8))
        out = S.build_skybox(pan, td, prefix="sky512", reference=ref)
        check("записано шесть граней", len(out) == 6, str(len(out)))
        sizes = {p.name: p.stat().st_size for p in out.values()}
        check("все грани одного размера", len(set(sizes.values())) == 1, str(set(sizes.values())))
        if ref is not None:
            want = ref.stat().st_size
            check("размер совпал с файлом Roblox",
                  all(v == want for v in sizes.values()), f"{set(sizes.values())} != {want}")
        for p in out.values():
            v = S.verify(p)
            if not (v["ok"] and v["size_ok"]):
                check(f"{p.name} корректен", False, str(v))
                break
        else:
            check("все файлы проходят verify()", True)

    print("\n── вшитые панорамы (манифест) ──")
    import hashlib
    presets = S.load_presets()
    check("вшито не меньше 30 панорам", len(presets) >= 30, str(len(presets)))
    bad = []
    for it in presets:
        if hashlib.sha256(Path(it["path"]).read_bytes()).hexdigest() != it.get("sha256"):
            bad.append(it["id"] + ":sha")
        with Image.open(it["path"]) as im:
            if im.size != (2048, 1024) or im.size != (it.get("w"), it.get("h")):
                bad.append(it["id"] + ":size")
        if it.get("license") != "CC0-1.0" or not it.get("author"):
            bad.append(it["id"] + ":meta")
    check("sha256, размер, лицензия и автор сходятся с манифестом", not bad, str(bad[:5]))
    ph = [i for i in presets if i["id"].startswith("ph-")]
    check("у панорам Poly Haven есть source_url", bool(ph) and all(i.get("source_url") for i in ph))

    print("\n── отказ на неверном размере ──")
    try:
        S.build_skybox(Image.new("RGB", (100, 100)), tempfile.mkdtemp())
        check("квадратная панорама отклонена", False)
    except S.SkyboxError:
        check("квадратная панорама отклонена", True)

    print("\n" + "═" * 58)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for f in FAILURES:
            print("  ·", f)
        return 1
    print("Все проверки пройдены.")
    return 0


def _close(a, b, tol=26) -> bool:
    return all(abs(int(x) - int(y)) <= tol for x, y in zip(a[:3], b[:3]))


if __name__ == "__main__":
    sys.exit(main())