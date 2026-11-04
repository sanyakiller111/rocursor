"""
tests/test_materials.py — текстуры мира и настройки Windows для FPS.

Только временные папки и подменённые реестр/powercfg: настоящий Roblox и
настройки Windows не трогаются.
"""
from __future__ import annotations

import io
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" +
          (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def noisy(w: int, h: int, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    im = Image.new("RGBA", (w, h))
    im.putdata([(rnd.randrange(60, 200), rnd.randrange(60, 200),
                 rnd.randrange(60, 200), rnd.randrange(100, 255)) for _ in range(w * h)])
    return im


def main() -> int:
    temp = tempfile.TemporaryDirectory(prefix="sk-mat-")
    tmp = Path(temp.name)
    os.environ["APPDATA"] = str(tmp / "appdata")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from cursor_manager.content import materials as mat
    from cursor_manager.core import cursor_core, pcboost, roblox_paths as RP
    from cursor_manager.ui.library import LibraryPage

    app = QApplication.instance() or QApplication([])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

    print("\n── DDS ──")
    atlas = mat.write_dds(noisy(32, 128, 1), b"DXT1")
    flat = mat.transform(atlas, "flat")
    check("flat: тот же размер и заголовок", len(flat) == len(atlas) and flat[:128] == atlas[:128])
    with Image.open(io.BytesIO(flat)) as im:
        tile = im.convert("RGBA").crop((0, 0, 32, 32))
        check("flat: тайл залит одним цветом", len(tile.getcolors()) == 1,
              str(len(tile.getcolors())))
        flat_px = im.convert("RGB").getpixel((3, 3))
    with Image.open(io.BytesIO(mat.transform(atlas, "dark"))) as im:
        dark_px = im.convert("RGB").getpixel((3, 3))
    check("dark темнее flat", sum(dark_px) < sum(flat_px) * 0.7, f"{dark_px} vs {flat_px}")
    normal = mat.write_dds(noisy(64, 64, 2), b"DXT5")
    check("DXT5 пересобирается", len(mat.transform(normal, "dark")) == len(normal))
    check("keep — байт в байт", mat.transform(atlas, "keep") == atlas)
    try:
        mat.transform(b"not a dds" * 20, "flat")
        check("не-DDS отклонён", False)
    except mat.MaterialError:
        check("не-DDS отклонён", True)

    print("\n── пути ──")
    kind = RP.get(RP.KIND_MATERIAL)
    check("пластик в plastic/", kind.rel("diffuse.dds").as_posix()
          == "PlatformContent/pc/textures/plastic/diffuse.dds")
    check("вода в water/", kind.rel("normal_07.dds").as_posix()
          == "PlatformContent/pc/textures/water/normal_07.dds")
    check("студы в корне textures", kind.rel("studs.dds").as_posix()
          == "PlatformContent/pc/textures/studs.dds")
    check("чужое имя не пускается", RP.validate(RP.KIND_MATERIAL, "brdfLUT.dds") is not None)
    check("путь в имени не пускается", RP.validate(RP.KIND_MATERIAL, "plastic/diffuse.dds") is not None)

    print("\n── установка ──")
    version = tmp / "version-test"
    originals = {
        "diffuse.dds": mat.write_dds(noisy(32, 128, 3), b"DXT1"),
        "normal.dds": mat.write_dds(noisy(32, 128, 4), b"DXT5"),
        "studs.dds": mat.write_dds(noisy(32, 128, 5), b"DXT1"),
        "normal_01.dds": mat.write_dds(noisy(64, 64, 6), b"DXT5"),
    }
    for name, data in originals.items():
        path = version / kind.rel(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    cursor_core.resolve_roblox_dir = lambda: version
    live = {n: version / kind.rel(n) for n in originals}

    page = LibraryPage()
    presets = {p["id"]: p for p in page.items_of(RP.KIND_MATERIAL)}
    check("5 пресетов", len(presets) == 5, str(list(presets)))
    check("минимум текстур ставится",
          page.install_entry(RP.KIND_MATERIAL, presets["min-textures"], version, quiet=True))
    check("все файлы заменены",
          all(live[n].read_bytes() != originals[n] for n in originals))
    check("слот material", page.slot_state("material") == "on")
    check("тёмный пластик ставится",
          page.install_entry(RP.KIND_MATERIAL, presets["dark-plastic"], version, quiet=True))
    check("студы и вода вернулись к оригиналу",
          live["studs.dds"].read_bytes() == originals["studs.dds"]
          and live["normal_01.dds"].read_bytes() == originals["normal_01.dds"])
    check("пластик собран из оригинала, а не из прошлого пресета",
          live["diffuse.dds"].read_bytes()
          == mat.transform(originals["diffuse.dds"], "dark"))
    page.revert_slot("material")
    check("снятие вернуло оригиналы",
          all(live[n].read_bytes() == originals[n] for n in originals))
    check("слот забыт", "material" not in page.config.slots)

    print("\n── windows ──")
    reg: dict[tuple, object] = {(pcboost.GPU_KEY, r"C:\old.exe"): "AppStatus=0;"}
    pcboost.reg_get = lambda k, n: reg.get((k, n))
    pcboost.reg_set = lambda k, n, v: reg.__setitem__((k, n), v)
    pcboost.reg_delete = lambda k, n: reg.pop((k, n), None)
    exes = [Path(r"C:\old.exe"), Path(r"C:\new.exe")]
    pcboost.enable_gpu(exes)
    check("GpuPreference=2 дописан к чужим парам",
          reg[(pcboost.GPU_KEY, r"C:\old.exe")] == "AppStatus=0;GpuPreference=2;",
          str(reg))
    check("новый exe получил настройку",
          reg.get((pcboost.GPU_KEY, r"C:\new.exe")) == "GpuPreference=2;")
    check("включено запомнено", pcboost.gpu_enabled())
    pcboost.disable_gpu()
    check("видеокарта вернулась как было",
          reg == {(pcboost.GPU_KEY, r"C:\old.exe"): "AppStatus=0;"}, str(reg))

    scheme = {"active": "381b4222-f694-41f0-9685-ff5bb260df2e"}
    calls = []

    def fake_powercfg(*args):
        calls.append(args)
        if args[0] == "/getactivescheme":
            return f"GUID: {scheme['active']} (Balanced)"
        if args[0] == "/list":
            return f"{scheme['active']}\n{pcboost.HIGH_PERF}"
        if args[0] == "/setactive":
            scheme["active"] = args[1]
        return ""

    pcboost.powercfg = fake_powercfg
    pcboost.enable_power()
    check("схема — высокая производительность", scheme["active"] == pcboost.HIGH_PERF)
    check("игровой режим включён", reg.get((pcboost.GAMEBAR_KEY, pcboost.GAMEMODE_VALUE)) == 1)
    pcboost.disable_power()
    check("схема вернулась", scheme["active"] == "381b4222-f694-41f0-9685-ff5bb260df2e")
    check("игровой режим как был (не задан)",
          (pcboost.GAMEBAR_KEY, pcboost.GAMEMODE_VALUE) not in reg)

    page.deleteLater()
    app.processEvents()
    temp.cleanup()
    print("\n" + "=" * 58)
    if FAILURES:
        print(f"Провалено проверок: {len(FAILURES)}")
        for f in FAILURES:
            print(f"  · {f}")
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
