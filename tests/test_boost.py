"""
tests/test_boost.py — fps-флаги, лимит кадров и выбор сервера.

Без сети и без настоящего Roblox: флаги пишутся во временную папку версии,
GlobalBasicSettings — временная копия, список серверов — подставной.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" +
          (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


BASIC_XML = """<roblox><Item class="UserGameSettings"><Properties>
<int name="FramerateCap">60</int>
<int name="GraphicsQualityLevel">13</int>
<token name="SavedQualityLevel">7</token>
<bool name="Fullscreen">false</bool>
</Properties></Item></roblox>"""


def main() -> int:
    temp = tempfile.TemporaryDirectory(prefix="sk-boost-")
    tmp = Path(temp.name)
    os.environ["APPDATA"] = str(tmp / "appdata")
    os.environ["LOCALAPPDATA"] = str(tmp / "local")

    from cursor_manager.core import config as cfg
    from cursor_manager.core import fps, servers

    print("\n── fps: флаги ──")
    version = tmp / "version-aaa"
    version.mkdir()
    own = fps.flags_path(version, "direct")
    own.parent.mkdir(parents=True)
    own.write_text(json.dumps({"FFlagUserOwn": "True"}), encoding="utf-8")
    fps.apply_flags(version, fps.PRESET_MAX, "direct")
    data = json.loads(own.read_text(encoding="utf-8"))
    check("флаги максимума записаны", data.get("FIntDebugForceMSAASamples") == "0"
          and data.get("FFlagDebugGraphicsPreferD3D11") == "True", str(data))
    check("чужой флаг пользователя не тронут", data.get("FFlagUserOwn") == "True")
    check("серое небо не входит в максимум", "FFlagDebugSkyGray" not in data)
    check("только разрешённые флаги",
          set(data) - {"FFlagUserOwn"} <= fps.OWN_FLAGS, str(set(data)))
    check("active_options видит пресет",
          set(fps.active_options(version)) == set(fps.PRESET_MAX),
          str(fps.active_options(version)))
    fps.apply_flags(version, ["msaa"], "direct")
    data = json.loads(own.read_text(encoding="utf-8"))
    check("снятая опция убирает свои флаги", "DFIntTextureQualityOverride" not in data
          and data.get("FIntDebugForceMSAASamples") == "0", str(data))
    fps.revert_flags(version, "direct")
    check("откат вернул оригинал",
          json.loads(own.read_text(encoding="utf-8")) == {"FFlagUserOwn": "True"})

    fresh = tmp / "version-bbb"
    fresh.mkdir()
    fps.apply_flags(fresh, ["grass"], "direct")
    check("файла не было — создан", fps.flags_path(fresh, "direct").is_file())
    fps.revert_flags(fresh, "direct")
    check("откат удалил созданный файл", not fps.flags_path(fresh, "direct").exists())
    try:
        fps.flags_for(["nope"])
        check("неизвестная опция отклонена", False)
    except fps.FpsError:
        check("неизвестная опция отклонена", True)

    print("\n── fps: лимит кадров ──")
    roblox = tmp / "local" / "Roblox"
    roblox.mkdir(parents=True)
    basic = roblox / "GlobalBasicSettings_13.xml"
    basic.write_text(BASIC_XML, encoding="utf-8")
    (roblox / "GlobalBasicSettings_13_Studio.xml").write_text("<x/>", encoding="utf-8")
    check("найден файл игры, а не Studio", fps.basic_settings_path() == basic,
          str(fps.basic_settings_path()))
    check("прочитаны текущие значения",
          fps.read_basic() == {"cap": 60, "quality": 7, "graphics": 13}, str(fps.read_basic()))
    res = fps.apply_basic(240, 1)
    check("лимит и качество записаны",
          fps.read_basic() == {"cap": 240, "quality": 1, "graphics": 1}, str(res))
    check("остальной файл не тронут", '<bool name="Fullscreen">false</bool>'
          in basic.read_text(encoding="utf-8"))
    check("откат лимита", fps.revert_basic() and fps.read_basic()["cap"] == 60)

    print("\n── config: fps переживает обновление ──")
    c = cfg.Config()
    c.fps_options, c.fps_cap, c.fps_quality = ["msaa", "grass"], 240, 1
    c.version, c.backend = "version-aaa", "direct"
    c.remember_place(920587237, "Adopt Me!")
    c.save()
    back = cfg.Config.load()
    check("fps-настройки сохранились",
          (back.fps_options, back.fps_cap, back.fps_quality) == (["msaa", "grass"], 240, 1))
    check("недавняя игра сохранилась", back.recent_places[0]["place"] == 920587237)
    check("после обновления нужен возврат даже без слотов",
          back.needs_restore("version-new"))

    print("\n── сервера ──")
    check("номер из ссылки", servers.parse_place(
        "https://www.roblox.com/games/920587237/Adopt-Me") == 920587237)
    check("номер из ссылки с языком", servers.parse_place(
        "https://www.roblox.com/ru/games/142823291/Murder-Mystery-2") == 142823291)
    check("голый номер", servers.parse_place(" 606849621 ") == 606849621)
    try:
        servers.parse_place("привет")
        check("мусор отклонён", False)
    except servers.ServerError:
        check("мусор отклонён", True)
    S = servers.Server
    pool = [S("a", 12, 12, 60, 40), S("b", 5, 12, 59, 180), S("c", 3, 12, 60, 90),
            S("d", 0, 12, 60, None), S("e", 8, 12, 30, 90)]
    order = [s.id for s in servers.ranked(pool)]
    check("полный сервер выкинут, пинг по возрастанию, без пинга в конце",
          order == ["c", "e", "b", "d"], str(order))
    check("лучший — с минимальным пингом и местом", servers.best(pool).id == "c")
    check("ссылка входа на сервер", servers.join_url(1, "ab-12") ==
          "roblox://experiences/start?placeId=1&gameInstanceId=ab-12")

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
