"""
tests/test_custom.py — своё из картинки, конструктор shiftlock, звуки и шрифты. Только временные папки: настоящий Roblox не трогается.
"""
from __future__ import annotations

import os
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


def main() -> int:
    temp = tempfile.TemporaryDirectory(prefix="sk-custom-")
    tmp = Path(temp.name)
    os.environ["APPDATA"] = str(tmp / "appdata")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from cursor_manager.content import custom, fonts, sounds
    from cursor_manager.core import config as cfg
    from cursor_manager.core import cursor_core, respack, roblox_paths as RP
    from cursor_manager.ui.library import LibraryPage

    app = QApplication.instance() or QApplication([])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

    print("\n── своё из картинки ──")
    src = tmp / "pic.png"
    pic = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    pic.paste((255, 0, 0, 255), (100, 50, 200, 150))
    pic.save(src)
    cur = custom.add("cursor", src, "мой курсор")
    with Image.open(custom.CUSTOM_ROOT / "cursor" / cur["file"]) as im:
        check("курсор: прозрачные поля обрезаны", im.size == (100, 100), str(im.size))
    sl = custom.add("crosshair", src, "мой прицел")
    with Image.open(custom.CUSTOM_ROOT / "crosshair" / sl["file"]) as im:
        check("shiftlock: квадрат 128", im.size == (128, 128), str(im.size))
    photo = tmp / "photo.jpg"
    Image.new("RGB", (1200, 900), (90, 140, 220)).save(photo)
    sk = custom.add("sky", photo, "моё небо")
    with Image.open(custom.CUSTOM_ROOT / "sky" / sk["file"]) as im:
        check("skybox: обрезан до 2:1 и 2048×1024", im.size == (2048, 1024), str(im.size))
    try:
        custom.add("cursor", tmp / "nope.txt", "x")
        check("не-картинка отклонена", False)
    except (custom.CustomError, OSError):
        check("не-картинка отклонена", True)
    check("своё видно в загрузке", [c.id for c in custom.load("cursor")] == [cur["id"]])

    print("\n── конструктор shiftlock ──")
    for shape in custom.SHAPES:
        im = custom.draw_shiftlock(shape=shape)
        alpha = im.getchannel("A").getbbox()
        check(f"форма «{shape}» не пустая и по центру",
              alpha is not None and abs((alpha[0] + alpha[2]) / 2 - 64) <= 2,
              str(alpha))

    for shape in custom.SHAPES:
        for rot in (0, 33):
            im = custom.draw_shiftlock(shape=shape, rotation=rot, glow=True, opacity=70)
            check(f"форма «{shape}» поворот {rot}: непустая 128×128",
                  im.size == (128, 128) and im.getchannel("A").getbbox() is not None)
    base = custom.draw_shiftlock(shape="cross", outline=0)
    half = custom.draw_shiftlock(shape="cross", outline=0, opacity=50)
    check("прозрачность уменьшает альфу",
          half.getchannel("A").getextrema()[1] <= 145 < base.getchannel("A").getextrema()[1])
    plain = custom.draw_shiftlock(shape="dot", outline=0, glow=False)
    glowing = custom.draw_shiftlock(shape="dot", outline=0, glow=True, glow_strength=8)
    check("свечение расширяет рисунок",
          (glowing.getchannel("A").getbbox()[2] - glowing.getchannel("A").getbbox()[0]) >
          (plain.getchannel("A").getbbox()[2] - plain.getchannel("A").getbbox()[0]))
    small = custom.draw_shiftlock(shape="cross", outline=0, size=10, gap=0)
    big = custom.draw_shiftlock(shape="cross", outline=0, size=10, gap=0, scale=200)
    check("масштаб увеличивает рисунок",
          big.getchannel("A").getbbox()[2] - big.getchannel("A").getbbox()[0] >
          small.getchannel("A").getbbox()[2] - small.getchannel("A").getbbox()[0])
    hollow = custom.draw_shiftlock(shape="square", outline=0)
    solid = custom.draw_shiftlock(shape="square", outline=0, filled=True)
    check("залить: центр квадрата закрашивается",
          hollow.getpixel((64, 64))[3] == 0 and solid.getpixel((64, 64))[3] == 255)
    check("точка поверх формы по запросу",
          custom.draw_shiftlock(shape="circle", outline=0).getpixel((64, 64))[3] == 0 and
          custom.draw_shiftlock(shape="circle", outline=0, center_dot=True).getpixel((64, 64))[3] > 200)
    big_side = custom.draw_shiftlock(shape="cross", side=256)
    check("другой side даёт тот же рисунок крупнее", big_side.size == (256, 256))
    try:
        custom.draw_shiftlock(shape="nope")
        check("неизвестная форма отклонена", False)
    except custom.CustomError:
        check("неизвестная форма отклонена", True)

    norm = custom.normalize_params({"shape": "x", "size": 999, "color": "red",
                                    "future_key": 1})
    check("параметры нормализуются", norm["size"] == 120 and norm["color"] == "#ff0000"
          and "future_key" not in norm and norm["shape"] == "x", str(norm))

    print("\n── сохранение параметров и обратная совместимость ──")
    params = custom.normalize_params({"shape": "diamond", "color": "#ffd400", "glow": True})
    made = custom.add("crosshair", custom.draw_shiftlock(**params), "ромб", params=params)
    loaded = {c.id: c for c in custom.load("crosshair")}
    check("параметры лежат в манифесте и читаются",
          loaded[made["id"]].params == params, str(loaded[made["id"]].params))
    check("старый элемент без params грузится", loaded[sl["id"]].params is None)
    check("старый вызов draw_shiftlock без новых аргументов",
          custom.draw_shiftlock("cross_dot", "#3d8bff", 40, 6, 10, 2, "#000000", 128).size == (128, 128))
    # старый манифест: запись без поля params и с лишним полем будущих версий
    manifest = custom.CUSTOM_ROOT / "crosshair" / "manifest.json"
    import json
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["items"][0]["params"] = {"shape": "no-such-shape"}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    check("битые params не ломают загрузку",
          all(c.params is None or c.id != made["id"] for c in custom.load("crosshair")) and
          len(custom.load("crosshair")) == 2)

    print("\n── редактор shiftlock ──")
    from cursor_manager.ui.shiftlock_editor import ShiftlockEditor
    editor = ShiftlockEditor()
    got: list = []
    editor.saved.connect(lambda i, a: got.append((i, a)))
    editor.set_params({"shape": "x", "color": "#ff3b3b", "outline": 0, "glow": True})
    check("редактор: параметры собираются",
          editor.params()["shape"] == "x" and editor.params()["outline"] == 0 and editor.params()["glow"])
    editor.randomize()
    custom.normalize_params(editor.params())
    editor.set_params({"shape": "triangle", "center_dot": True})
    editor.name.setText("тест")
    editor._save(True)
    check("редактор: сохранил и отправил сигнал", len(got) == 1 and got[0][1] is True)
    saved_item = [c for c in custom.load("crosshair") if c.id == got[0][0]]
    check("редактор: params сохранены", bool(saved_item) and saved_item[0].params["shape"] == "triangle")
    editor.deleteLater()

    print("\n── установка в папку версии ──")
    version = tmp / "version-test"
    kb = version / RP.get(RP.KIND_CURSOR).path
    kb.mkdir(parents=True)
    for n in ("ArrowCursor.png", "ArrowFarCursor.png"):
        Image.new("RGBA", (64, 64), (1, 2, 3, 255)).save(kb / n)
    (version / RP.get(RP.KIND_CROSSHAIR).path).mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (32, 32), (4, 5, 6, 255)).save(
        version / RP.get(RP.KIND_CROSSHAIR).path / "MouseLockedCursor.png")
    snd_dir = version / RP.get(RP.KIND_SOUND).path
    snd_dir.mkdir(parents=True)
    for n in ("oof.ogg", "ouch.ogg"):
        (snd_dir / n).write_bytes(b"OggS-original")
    font_dir = version / RP.get(RP.KIND_FONT).path
    font_dir.mkdir(parents=True)
    for n in fonts.TARGETS:
        (font_dir / n).write_bytes(b"original-font")
    cursor_core.resolve_roblox_dir = lambda: version

    page = LibraryPage()
    my = page.find(RP.KIND_CURSOR, cur["id"])
    check("свой курсор в каталоге", my is not None and my.path is not None)
    check("свой курсор ставится", page.install_entry(RP.KIND_CURSOR, my, version, quiet=True))
    with Image.open(kb / "ArrowCursor.png") as im:
        check("свой курсор подогнан под 64×64", im.size == (64, 64), str(im.size))
    my_sl = page.find(RP.KIND_CROSSHAIR, sl["id"])
    check("свой shiftlock ставится", page.install_entry(RP.KIND_CROSSHAIR, my_sl, version, quiet=True))

    death = [s for s in sounds.load_presets() if s["role"] == "death"][0]
    check("звук смерти ставится", page.install_entry(RP.KIND_SOUND, death, version, quiet=True))
    check("oof.ogg заменён", (snd_dir / "oof.ogg").read_bytes() == death["path"].read_bytes())
    check("слот звука по роли", "sound:death" in page.config.slots,
          str(list(page.config.slots)))
    font = fonts.load_presets()[0]
    check("шрифт ставится", page.install_entry(RP.KIND_FONT, font, version, quiet=True))
    check("BuilderSans заменён",
          (font_dir / "BuilderSans-Regular.otf").read_bytes() == font["regular"].read_bytes())
    check("состояние слотов «стоит»",
          all(page.slot_state(k) == "on" for k in ("cursor", "sound:death", "font")),
          str({k: page.slot_state(k) for k in page.config.slots}))

    page.revert_slot("sound:death")
    check("звук вернулся", (snd_dir / "oof.ogg").read_bytes() == b"OggS-original")
    page.revert_slot("font")
    check("шрифт вернулся", (font_dir / "BuilderSans-Bold.otf").read_bytes() == b"original-font")

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
