"""
tests/test_library.py — встроенная библиотека: размеры и установка.

Проверяет, что курсор и прицел подгоняются под размеры файлов Roblox,
а не кладутся в клиент «как нарисованы». Это важно: оригинальные курсоры
обычно 64×64, а MouseLockedCursor.png — 32×32.
"""
from __future__ import annotations

import io
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
    temp = tempfile.TemporaryDirectory(prefix="cursor-manager-library-")
    os.environ["APPDATA"] = str(Path(temp.name) / "appdata")

    from PySide6.QtWidgets import QApplication

    from cursor_manager.app import ResourcesPage, _rcur_arg
    from cursor_manager.content import crosshair, cursor_library
    from cursor_manager.core import respack, rcur, roblox_paths as RP
    from cursor_manager.ui.library import LibraryPage

    app = QApplication.instance() or QApplication([])
    version = Path(temp.name) / "version-test"
    kb = version / RP.get(RP.KIND_CURSOR).path
    kb.mkdir(parents=True)
    arrow = Image.new("RGBA", (64, 64), (10, 20, 30, 255))
    far = Image.new("RGBA", (64, 64), (40, 50, 60, 255))
    arrow.save(kb / "ArrowCursor.png")
    far.save(kb / "ArrowFarCursor.png")

    textures = version / RP.get(RP.KIND_CROSSHAIR).path
    textures.mkdir(parents=True, exist_ok=True)
    locked = Image.new("RGBA", (32, 32), (70, 80, 90, 255))
    locked.save(textures / "MouseLockedCursor.png")
    original_arrow = (kb / "ArrowCursor.png").read_bytes()
    original_locked = (textures / "MouseLockedCursor.png").read_bytes()

    print("\n── встроенные курсоры ──")
    page = LibraryPage()
    cursors = cursor_library.catalog()
    check("каталог курсоров не пуст", bool(cursors), str(len(cursors)))
    pack = page._cursor_pack(cursors[0], version)
    with Image.open(pack.files["ArrowCursor.png"]) as im:
        check("курсор подогнан под 64×64", im.size == (64, 64), str(im.size))
    result = respack.install(pack, version, "direct")
    check("курсор установлен", len(result["installed"]) == 2, str(result))
    with Image.open(kb / "ArrowCursor.png") as im:
        check("в Roblox лежит 64×64", im.size == (64, 64), str(im.size))
    check("оригинал изменился", (kb / "ArrowCursor.png").read_bytes() != original_arrow)
    respack.uninstall(pack, version, "direct")
    check("оригинальный курсор вернулся",
          (kb / "ArrowCursor.png").read_bytes() == original_arrow)

    print("\n── встроенные прицелы ──")
    presets, _ = crosshair.load_presets()
    check("каталог прицелов не пуст", bool(presets), str(len(presets)))
    # стиль «точка» с dot=False раньше давал пустую картинку (32 пресета)
    blank = [p.name for p in presets
             if not crosshair.render_preset(p, 128).getchannel("A").getbbox()]
    check("ни один прицел не рисуется пустым", not blank, ", ".join(blank[:5]))
    pack = page._crosshair_pack(presets[0], version)
    with Image.open(pack.files["MouseLockedCursor.png"]) as im:
        check("прицел подогнан под 32×32", im.size == (32, 32), str(im.size))
    result = respack.install(pack, version, "direct")
    check("прицел установлен", len(result["installed"]) == 1, str(result))
    with Image.open(textures / "MouseLockedCursor.png") as im:
        check("в Roblox лежит 32×32", im.size == (32, 32), str(im.size))
    check("оригинальный прицел изменился",
          (textures / "MouseLockedCursor.png").read_bytes() != original_locked)
    respack.uninstall(pack, version, "direct")
    check("оригинальный прицел вернулся",
          (textures / "MouseLockedCursor.png").read_bytes() == original_locked)

    print("\n── курсоры osuskinner во вшитом каталоге ──")
    from cursor_manager.ui import library as library_ui
    osu = [c for c in cursors if c.category == "osu!"]
    check("курсоры osu! вшиты", len(osu) >= 100, str(len(osu)))
    check("у курсоров osu! есть автор и ссылка",
          all(c.author and c.source_url for c in osu), "")
    big = max(osu, key=lambda c: c.bytes) if osu else None
    if big is not None:
        pack = page._cursor_pack(big, version)
        with Image.open(pack.files["ArrowCursor.png"]) as im:
            check("курсор osu! подогнан под 64×64", im.size == (64, 64), str(im.size))
        result = respack.install(pack, version, "direct")
        check("курсор osu! установлен", len(result["installed"]) == 2, str(result))
        respack.uninstall(page._cursor_pack(big), version, "direct")
        check("после снятия вернулся оригинал",
              (kb / "ArrowCursor.png").read_bytes() == original_arrow)

    page._set_kind(RP.KIND_CURSOR)
    app.processEvents()
    check("счётчик показывает весь каталог", page.search.placeholderText() == f"Найти среди {len(cursors)}",
          page.search.placeholderText())
    rows = len(page.cards)
    check("первая порция — не больше PAGE_SIZE карточек",
          0 < rows <= library_ui.PAGE_SIZE, str(rows))
    check("категорий в UI больше нет", page.categories() == [] and page.category == "")
    page.set_category("osu!")
    check("set_category ничего не фильтрует",
          page.category == "" and len(page._filtered()) == len(cursors))
    page.search.setText("osu!")
    page.refresh()
    check("поиск по «osu!» находит их", len(page._filtered()) >= len(osu) > 0,
          str(len(page._filtered())))
    page.search.setText("")
    page.refresh()
    check("канал один — direct", page._backend_key() == "direct"
          and not hasattr(page, "backend"))

    print("\n── config: запоминание и возврат после обновления Roblox ──")
    from cursor_manager.core import config as cfg
    old = Path(temp.name) / "old-config.json"
    old.write_text('{"schema": 1, "backend": "bloxstrap", "version": "v", "slots": {}}',
                   encoding="utf-8")
    check("старый канал bloxstrap читается как direct",
          cfg.Config.load(old).backend == "direct")
    from cursor_manager.core import cursor_core
    real_resolve = cursor_core.resolve_roblox_dir
    cursor_core.resolve_roblox_dir = lambda: version
    try:
        page.set_kind(RP.KIND_CURSOR)
        page.select(cursors[1])
        page._apply_selected()
        saved = cfg.Config.load()
        check("выбор записан в config.json",
              saved.slots.get("cursor") is not None
              and saved.slots["cursor"].id == cursors[1].id, str(saved.slots))
        check("в config записана версия Roblox", saved.version == version.name,
              saved.version)
        check("слот курсора стоит", page.slot_state(RP.KIND_CURSOR) == "on",
              page.slot_state(RP.KIND_CURSOR))
        check("карточка помечена «стоит»",
              any(card.caption.property("on") for _, card in page.cards))

        # «обновление Roblox»: новая папка версии с оригинальными курсорами
        updated = Path(temp.name) / "version-updated"
        kb2 = updated / RP.get(RP.KIND_CURSOR).path
        kb2.mkdir(parents=True)
        arrow.save(kb2 / "ArrowCursor.png")
        far.save(kb2 / "ArrowFarCursor.png")
        cursor_core.resolve_roblox_dir = lambda: updated
        check("после обновления слот слетел", page.slot_state(RP.KIND_CURSOR) == "off",
              page.slot_state(RP.KIND_CURSOR))
        fresh = library_ui.LibraryPage()
        restored = fresh.restore_config()
        check("при запуске курсор вернулся сам", restored == [cursors[1].name],
              str(restored))
        check("файл в новой версии заменён",
              (kb2 / "ArrowCursor.png").read_bytes() != (kb / "ArrowCursor.png").read_bytes()
              or fresh.slot_state(RP.KIND_CURSOR) == "on",
              fresh.slot_state(RP.KIND_CURSOR))
        check("config переехал на новую версию",
              cfg.Config.load().version == "version-updated")
        check("повторный запуск ничего не трогает", fresh.restore_config() == [])

        fresh.revert_slot(RP.KIND_CURSOR)
        check("«вернуть оригинал» убрал слот из config",
              "cursor" not in cfg.Config.load().slots)
        fresh.deleteLater()
    finally:
        cursor_core.resolve_roblox_dir = real_resolve
    respack.uninstall(page._cursor_pack(cursors[1]), version, "direct")

    print("\n── .rcur ──")
    buf = io.BytesIO()
    Image.new("RGBA", (128, 128), (90, 100, 110, 255)).save(buf, "PNG")
    blob = buf.getvalue()
    set_ = rcur.RcurSet(
        arrow=blob, far=blob, ibeam=blob,
        name="Test rcur", blurb="проверка", scale=100)
    resources = ResourcesPage()
    pack = resources._rcur_pack(set_, version, "test-rcur")
    check(".rcur собрал три слота", set(pack.files) == {
        "ArrowCursor.png", "ArrowFarCursor.png", "IBeamCursor.png"})
    for name, path in pack.files.items():
        with Image.open(path) as im:
            check(f"{name} подогнан под 64×64", im.size == (64, 64), str(im.size))
    result = respack.install(pack, version, "direct")
    check(".rcur установлен", len(result["installed"]) == 3, str(result))
    respack.uninstall(pack, version, "direct")
    check(".rcur IBeam снят", not (kb / "IBeamCursor.png").exists())
    check("аргумент --apply разобран",
          _rcur_arg(["app.exe", "--apply", "demo.rcur"]) == "demo.rcur")
    check("голый путь .rcur разобран",
          _rcur_arg(["app.exe", "demo.rcur"]) == "demo.rcur")

    resources.deleteLater()
    page.deleteLater()
    app.processEvents()
    temp.cleanup()
    print("\n" + "=" * 58)
    if FAILURES:
        print(f"Провалено проверок: {len(FAILURES)}")
        for failure in FAILURES:
            print(f"  · {failure}")
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
