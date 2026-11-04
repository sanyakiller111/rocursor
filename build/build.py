"""
build/build.py — сборка приложения.

Порядок: ассеты -> ресурс версии -> PyInstaller (onefile) -> exe в корень
-> Inno Setup -> source zip -> контрольные суммы.

Запуск из корня:  build.bat   (или  python build/build.py)

Результат:
  • <корень>/sanyakiller111.exe — готовое приложение, один файл. Это то, что
    нужно запускать; PyInstaller кладёт его в build/work/dist и build.py
    копирует в корень проекта.
  • dist/<slug>-Setup-<версия>.exe — установщик Inno Setup (упаковывает тот же
    onefile exe). Inno Setup обязателен: нет ISCC.exe — сборка падает с
    понятной ошибкой, а не «молча пропускает installer».
  • dist/<slug>-<версия>-src.zip — только исходники, SHA256SUMS, build.json.

Промежуточные файлы PyInstaller — в build/work/ (в .gitignore).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from cursor_manager import version

DIST = ROOT / "dist"
BUILD = ROOT / "build" / "work"
PYI_DIST = BUILD / "dist"      # куда PyInstaller кладёт onefile exe
ROOT_EXE = ROOT / f"{version.APP_SLUG}.exe"
ASSETS = ROOT / "assets"
VENV = ROOT / ".venv"
SPEC = HERE / "cursor_manager.spec"
ISS = HERE / "installer.iss"

# ─────────────────────────────────────────────────────────────────────────────
# Состав source zip. Всё, что не перечислено, в релиз не идёт.
# tools/ — dev-среда, для сборки из архива они не нужны:
# ассеты уже сгенерированы и лежат в assets/.
# ─────────────────────────────────────────────────────────────────────────────
SOURCE_DIRS = ("src", "assets", "build", "tests", "docs")
SOURCE_FILES = ("README.md", "LICENSE", "pyproject.toml",
                "requirements-build.txt", "build.bat", ".gitignore")

# Папки-мусор в любом месте. Внутри build/ PyInstaller кладёт промежуточные
# work/ и cursor_manager/ — их тоже нельзя тащить в релиз.
SKIP_DIRS_ANY = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache",
                 "venv", ".venv", "node_modules", "egg-info"}
SKIP_DIRS_UNDER_BUILD = {"work", "cursor_manager"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".swp", ".orig", ".bak",
                 ".sha256"}
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini", "nul",
              "version_info.txt"}


def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def py() -> str:
    """Интерпретатор: сначала venv проекта, иначе системный."""
    for cand in (VENV / "Scripts" / "python.exe",
                 VENV / "Scripts" / "python",
                 ROOT / ".venv" / "Scripts" / "python.exe"):
        if cand.exists():
            return str(cand)
    return sys.executable


def run(args: list[str], cwd: Path | None = None) -> int:
    return subprocess.call([py(), *args], cwd=str(cwd or ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Ассеты
# ─────────────────────────────────────────────────────────────────────────────
def make_assets() -> None:
    say("ассеты")
    script = ROOT / "tools" / "make_assets.py"
    if not script.is_file():
        # В source zip tools/ не возится — это dev-сценарии. Ассеты на тот
        # момент уже сгенерированы и входят в архив, регенерация не нужна.
        if not any((ASSETS / "cursors").glob("*.png")):
            raise SystemExit(
                "tools/make_assets.py не найден, а assets/ пуст — регенерировать нечем")
        say("tools/ нет (source zip) — ассеты уже сгенерированы в assets/")
        return
    if run([str(script)]) != 0:
        raise SystemExit("make_assets.py упал")
    pngs = sorted((ASSETS / "cursors").glob("*.png"))
    say(f"курсоров: {len(pngs)}")


def write_version_resource() -> None:
    """Windows-ресурс с версией: свойства файла в проводнике показывают её."""
    say("ресурс версии")
    HERE.mkdir(parents=True, exist_ok=True)
    v = version.VERSION.split(".")
    nums = [int(x) for x in (v + ["0", "0"])[:4]]

    body = f"""
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({nums[0]}, {nums[1]}, {nums[2]}, {nums[3]}),
    prodvers=({nums[0]}, {nums[1]}, {nums[2]}, {nums[3]}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', '{version.AUTHOR}'),
        StringStruct('FileDescription', '{version.APP_NAME}'),
        StringStruct('FileVersion', '{version.VERSION}'),
        StringStruct('InternalName', '{version.APP_SLUG}'),
        StringStruct('OriginalFilename', '{version.APP_SLUG}.exe'),
        StringStruct('ProductName', '{version.APP_NAME}'),
        StringStruct('ProductVersion', '{version.VERSION}'),
        StringStruct('LegalCopyright', 'MIT'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    out = HERE / "version_info.txt"
    out.write_text(body, encoding="utf-8")
    say(f"version_info.txt: {version.VERSION}")


# ─────────────────────────────────────────────────────────────────────────────
# PyInstaller
# ─────────────────────────────────────────────────────────────────────────────
def build_exe(skip_assets: bool = False) -> Path:
    say("PyInstaller")
    if not skip_assets:
        make_assets()
    write_version_resource()

    for d in (BUILD, DIST):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    DIST.mkdir(parents=True, exist_ok=True)

    code = run(["-m", "PyInstaller", "--noconfirm", "--clean",
                "--workpath", str(BUILD), "--distpath", str(PYI_DIST),
                str(SPEC)])
    if code != 0:
        raise SystemExit("PyInstaller упал")

    built = PYI_DIST / f"{version.APP_SLUG}.exe"
    if not built.is_file():
        raise SystemExit(f"не найден исполняемый файл: {built}")

    # Готовый exe — прямо в корень проекта, чтобы его не приходилось искать.
    # Если старый запущен, Windows не даст его перезаписать — говорим прямо.
    try:
        shutil.copy2(built, ROOT_EXE)
    except PermissionError:
        raise SystemExit(f"не удалось перезаписать {ROOT_EXE}: "
                         "закройте запущенное приложение и повторите")
    return ROOT_EXE


# ─────────────────────────────────────────────────────────────────────────────
# Установщик Inno Setup — обязательный шаг, ошибку пропуска сделать нельзя
# ─────────────────────────────────────────────────────────────────────────────
def find_iscc() -> Path | None:
    """ISCC.exe: env override, PATH, затем известные каталоги установки.

    winget ставит per-user в %LOCALAPPDATA%\\Programs\\Inno Setup 6,
    классический инсталлятор и choco — в Program Files (x86).
    """
    candidates: list[Path] = []
    env = os.environ.get("ISCC")
    if env:
        candidates.append(Path(env))
    which_hit = shutil.which("ISCC") or shutil.which("ISCC.exe")
    if which_hit:
        candidates.append(Path(which_hit))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        pf = os.environ.get(var)
        if pf:
            candidates.append(Path(pf) / "Inno Setup 6" / "ISCC.exe")
    for c in candidates:
        if c.is_file():
            return c
    return None


def build_installer(exe: Path) -> Path:
    say("установщик (Inno Setup)")
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit(
            "Inno Setup не найден: ISCC.exe отсутствует.\n"
            "Установщик — обязательный артефакт релиза, без него сборка "
            "не продолжается.\n"
            "Как исправить:\n"
            "  winget install -e --id JRSoftware.InnoSetup\n"
            "  или задать переменную окружения ISCC = полный путь к ISCC.exe"
        )
    say(f"ISCC: {iscc}")
    cmd = [str(iscc),
           f"/DAppVersion={version.VERSION}",
           f"/DAppSlug={version.APP_SLUG}",
           f"/DAppExe={exe}",
           str(ISS)]
    if subprocess.call(cmd, cwd=str(ROOT)) != 0:
        raise SystemExit("ISCC вернул ошибку, установщик не собран")

    target = DIST / f"{version.APP_SLUG}-Setup-{version.VERSION}.exe"
    if not target.is_file():
        raise SystemExit(f"установщик не создан: {target}")
    say(f"{target.name}: {target.stat().st_size / 1048576:.1f} МБ")
    return target


# ─────────────────────────────────────────────────────────────────────────────
# Source zip и контрольные суммы
# ─────────────────────────────────────────────────────────────────────────────
def _collect_source_entries() -> list[tuple[Path, str]]:
    """Пар (файл, имя в архиве). Архив плоский: распаковался — корень проекта."""
    entries: list[tuple[Path, str]] = []

    for top in SOURCE_DIRS:
        base = ROOT / top
        if not base.is_dir():
            raise SystemExit(f"для source zip нет каталога: {base}")
        for dirpath, dirnames, filenames in os.walk(base):
            under_build = Path(dirpath).relative_to(ROOT).parts[:1] == ("build",)
            skip = (SKIP_DIRS_ANY | SKIP_DIRS_UNDER_BUILD) if under_build \
                else SKIP_DIRS_ANY
            dirnames[:] = sorted(n for n in dirnames if n not in skip)
            for name in sorted(filenames):
                if Path(name).suffix.lower() in SKIP_SUFFIXES:
                    continue
                if name.lower() in SKIP_FILES:
                    continue
                f = Path(dirpath) / name
                entries.append((f, f.relative_to(ROOT).as_posix()))

    for name in SOURCE_FILES:
        f = ROOT / name
        if not f.is_file():
            raise SystemExit(f"для source zip нет файла: {f}")
        entries.append((f, name))

    return entries


def make_source_zip() -> Path:
    say("source zip")
    target = DIST / f"{version.APP_SLUG}-{version.VERSION}-src.zip"
    entries = _collect_source_entries()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path, arcname in entries:
            z.write(path, arcname)
    n = target.stat().st_size
    say(f"{target.name}: {n // 1048576}.{n % 1048576 // 1024} МБ, файлов: {len(entries)}")
    return target


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_checksums(paths: list[Path]) -> None:
    say("контрольные суммы")
    rows = []
    for p in paths:
        if not p.is_file():
            continue
        digest = sha256_of(p)
        rows.append(f"{digest}  {p.name}")
        p.with_suffix(p.suffix + ".sha256").write_text(digest + "\n", encoding="ascii")

    (DIST / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="ascii")

    meta = {
        "schema": 1,
        "app": version.APP_NAME,
        "version": version.VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "exe": {"name": ROOT_EXE.name, "bytes": ROOT_EXE.stat().st_size,
                "sha256": sha256_of(ROOT_EXE)},
        "artifacts": [{"name": p.name, "bytes": p.stat().st_size,
                       "sha256": sha256_of(p)} for p in paths if p.is_file()],
    }
    (DIST / "build.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    say(f"артефактов: {len(rows)}")


def main() -> int:
    skip_assets = "--skip-assets" in sys.argv
    sign = "--sign" in sys.argv

    print(f"\n{version.APP_NAME} {version.VERSION}\n")

    exe = build_exe(skip_assets)
    say(f"exe: {exe.stat().st_size / 1048576:.1f} МБ")

    # Порядок фиксирован: сначала установщик, потом source zip.
    inst = build_installer(exe)
    src = make_source_zip()

    write_checksums([inst, src])

    if sign:
        say("подпись: сертификат не настроен, шаг пропущен")

    print(f"\n  готово. Установщик и архивы в {DIST}:")
    for p in (inst, src):
        print(f"    {p.name}  {sha256_of(p)}")
    print(f"\n  ГОТОВЫЙ EXE: {exe}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
