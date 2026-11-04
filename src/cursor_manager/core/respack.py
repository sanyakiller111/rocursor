"""
respack.py — наборы ресурсов: метаданные, импорт ZIP, применение, сброс.

Набор — это папка с файлами и pack.json:

    my-pack/
      pack.json          метаданные: название, автор, лицензия, источник
      preview.png        превью (необязательно)
      content/…          файлы с путями Roblox, один в один

Применение идёт одним из двух каналов:

  direct      пишем прямо в папку версии Roblox. Работает всегда, но после
              обновления клиента папка меняется и всё слетает.

  bloxstrap   пишем в %LOCALAPPDATA%\\Bloxstrap\\Modifications. Bloxstrap
              копирует оверлей в папку версии при каждом запуске, а удалённый
              оттуда файл при следующем запуске Roblox возвращает оригинал.
              Набор переживает обновления сам.

Безопасность импорта. ZIP приходит с диска, доверять содержимому нельзя:
  * выход за пределы папки (`..`, абсолютные пути, ведущие слеши)
  * симлинки и жёсткие ссылки внутри архива
  * повторяющиеся имена (zip-бомба через два входа с одним именем)
  * кол-во записей и суммарный распакованный объём
  * расширение: .png/.tex/.ogg/.ttf и никаких .exe/.dll/.bat
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from cursor_manager.core import roblox_paths as RP

SCHEMA = 1
MANIFEST_NAME = "pack.json"
APP_ROOT = Path(os.environ.get("APPDATA", Path.home())) / "RobloxCursorChanger"
BACKUP_ROOT = APP_ROOT / "backup"

MAX_ENTRIES = 64
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
ALLOWED_EXT = (".png", ".tex", ".ogg", ".mp3", ".wav", ".ttf", ".otf")

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class PackError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Модели
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class PackMeta:
    name: str = "Без названия"
    author: str = ""
    license: str = "UNKNOWN"
    source_url: str = ""
    description: str = ""
    kind: str = RP.KIND_CURSOR
    version: str = "1.0"
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PackMeta":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if "name" not in known:
            raise PackError("в pack.json нет поля name")
        m = cls(**known)
        m.name = str(m.name)[:80]
        m.description = str(m.description)[:400]
        if m.license not in RP.LICENSES:
            # неизвестная лицензия опаснее отсутствующей: пусть будет UNKNOWN
            m.license = "UNKNOWN"
        try:
            RP.get(m.kind)
        except KeyError:
            raise PackError(f"неизвестная категория: {m.kind}") from None
        return m

    @property
    def safe_for_bundle(self) -> bool:
        return RP.bundle_allowed(self.license)


@dataclass
class Pack:
    meta: PackMeta
    root: Path
    files: dict[str, Path] = field(default_factory=dict)   # rel -> файл
    preview: Path | None = None
    missing: list[str] = field(default_factory=list)      # чего не хватает из набора

    @property
    def id(self) -> str:
        return self.root.name

    def summary(self) -> str:
        return (f"{self.meta.name} · {RP.get(self.meta.kind).label} · "
                f"{self.meta.license} · {len(self.files)} файл(ов)")

    def safety_note(self) -> str:
        if self.meta.safe_for_bundle:
            return ""
        note = RP.LICENSES.get(self.meta.license, "")
        return f"Лицензия {self.meta.license}: {note}. В поставку приложения включать нельзя."


# ─────────────────────────────────────────────────────────────────────────────
# Чтение и запись
# ─────────────────────────────────────────────────────────────────────────────
def load_pack(root: str | Path) -> Pack:
    root = Path(root)
    mpath = root / MANIFEST_NAME
    if not mpath.is_file():
        raise PackError(f"нет {MANIFEST_NAME} в папке набора")
    try:
        raw = json.loads(mpath.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PackError(f"{MANIFEST_NAME} не читается: {exc}") from exc
    if not isinstance(raw, dict):
        raise PackError(f"{MANIFEST_NAME} должен быть объектом")
    try:
        schema = int(raw.get("schema", 0))
    except (TypeError, ValueError):
        raise PackError(f"неподдерживаемая схема набора: {raw.get('schema')}") from None
    if schema != SCHEMA:
        raise PackError(f"неподдерживаемая схема набора: {raw.get('schema')}")
    meta = PackMeta.from_dict(raw)

    kind = RP.get(meta.kind)
    files: dict[str, Path] = {}
    targets: set[str] = set()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name == MANIFEST_NAME or p.name == "preview.png":
            continue
        rel = p.relative_to(root).as_posix()
        pp = PurePosixPath(rel)
        name = pp.name
        if len(pp.parts) > 1:
            allowed_parents = {PurePosixPath(kind.path)}
            if meta.kind == RP.KIND_CURSOR and name.lower() == "mouselockedcursor.png":
                allowed_parents.add(PurePosixPath("content/textures"))
            if pp.parent not in allowed_parents:
                raise PackError(
                    f"{rel}: вложенность не поддерживается — файл должен "
                    f"лежать в {kind.path}/ или в корне набора")
        err = RP.validate(meta.kind, name)
        if err:
            raise PackError(f"{rel}: {err}")
        target = kind.rel(name).as_posix()
        if target in targets:
            raise PackError(f"{rel}: дублирует файл {target}")
        targets.add(target)
        if not p.suffix.lower() in ALLOWED_EXT:
            raise PackError(f"{rel}: расширение {p.suffix} не принимается")
        if p.stat().st_size > MAX_FILE_BYTES:
            raise PackError(f"{rel}: файл больше {MAX_FILE_BYTES // 1048576} МБ")
        files[rel] = p

    if not files:
        raise PackError("в наборе нет ни одного файла ресурса")
    present = {PurePosixPath(f).name for f in files}
    pack = Pack(meta=meta, root=root, files=files,
                preview=(root / "preview.png") if (root / "preview.png").is_file() else None)
    # чего из ожидаемого набора не хватает — не ошибка, но повод сказать
    pack.missing = [n for n in kind.files if n not in present] if kind.files else []
    return pack


def save_pack(meta: PackMeta, files: dict[str, Path], dest: str | Path,
              preview: Path | None = None) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for rel, src in files.items():
        target = dest / PurePosixPath(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    (dest / MANIFEST_NAME).write_text(
        json.dumps(meta.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    if preview and Path(preview).is_file():
        shutil.copy2(preview, dest / "preview.png")
    return dest


# ─────────────────────────────────────────────────────────────────────────────
# Импорт ZIP — единственное место, где внутрь приходят чужие байты
# ─────────────────────────────────────────────────────────────────────────────
def _reject(reason: str):
    raise PackError(f"ZIP отклонён: {reason}")


def inspect_zip(path: str | Path) -> list[tuple[str, int]]:
    """Список (имя, размер) без распаковки. Для предпросмотра в интерфейсе."""
    try:
        with zipfile.ZipFile(path) as z:
            return [(i.filename, i.file_size) for i in z.infolist() if not i.is_dir()]
    except zipfile.BadZipFile as exc:
        raise PackError(f"не ZIP: {exc}") from exc


def import_zip(zip_path: str | Path, dest_root: str | Path) -> Pack:
    """
    Распаковывает набор из ZIP в dest_root/<имя> и возвращает Pack.

    extractall() не используется намеренно: он молча пропускает выход за
    пределы папки, симлинки и перезапись. Здесь каждая запись проверяется.
    """
    zip_path = Path(zip_path)
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise PackError(f"не ZIP: {exc}") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            _reject(f"больше {MAX_ENTRIES} записей")
        total = sum(i.file_size for i in infos)
        if total > MAX_TOTAL_BYTES:
            _reject(f"распакованный объём {total // 1048576} МБ превышает лимит")

        seen: set[str] = set()
        payloads: dict[str, bytes] = {}
        for info in infos:
            if info.is_dir():
                continue
            name = info.filename
            if "\\" in name:
                name = name.replace("\\", "/")
            # нормализация до pure-posix, чтобы отсечь «a/../../b»
            pp = PurePosixPath(name)
            if pp.is_absolute() or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
                _reject(f"абсолютный путь: {info.filename}")
            parts = [p for p in pp.parts if p != "."]
            if any(p == ".." for p in parts):
                _reject(f"выход за пределы папки: {info.filename}")
            if pp.name.lower().endswith((".exe", ".dll", ".bat", ".cmd", ".ps1", ".scr", ".com")):
                _reject(f"исполняемый файл в архиве: {info.filename}")
            if pp.suffix.lower() not in ALLOWED_EXT and pp.name != MANIFEST_NAME \
                    and pp.name != "preview.png":
                _reject(f"неожиданный файл: {info.filename}")
            # внешние атрибуты: 0xA000 = симлинка, 0x4000 = каталог
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode & 0xF000 == 0xA000:
                _reject(f"симлинк в архиве: {info.filename}")
            key = "/".join(parts)
            if key in seen:
                _reject(f"дубль имени: {key}")
            seen.add(key)
            if info.file_size > MAX_FILE_BYTES:
                _reject(f"{key}: больше {MAX_FILE_BYTES // 1048576} МБ")
            payloads[key] = zf.read(info)

    if MANIFEST_NAME not in payloads:
        _reject(f"нет {MANIFEST_NAME} — это не набор ресурсов")

    name = _UNSAFE_NAME.sub("-", zip_path.stem or "pack").strip(".-")[:64]
    if not name:
        digest = hashlib.sha256(zip_path.name.encode("utf-8")).hexdigest()[:8]
        name = f"pack-{digest}"
    dest = Path(dest_root) / name
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    written = 0
    for rel, data in payloads.items():
        target = dest / PurePosixPath(rel)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written += 1
        except OSError:
            # гонка с параллельным импортом того же архива — не повод падать
            continue
    if not written:
        _reject("не удалось записать ни одного файла")

    return load_pack(dest)


# ─────────────────────────────────────────────────────────────────────────────
# Установка и снятие
# ─────────────────────────────────────────────────────────────────────────────
def install(pack: Pack, version_dir: Path, backend: str = "direct",
            dry_run: bool = False) -> dict:
    """
    Кладёт файлы набора в выбранный канал.

    Перед первой заменой оригиналы снимаются в бэкап — по папке на версию.
    Для канала bloxstrap бэкап не обязателен (его снимает сам Bloxstrap),
    но при смешанном применении он всё равно нужен для прямого канала.
    """
    if backend not in RP.BACKENDS:
        raise PackError(f"неизвестный канал: {backend}")
    if backend == "bloxstrap" and not RP.bloxstrap_installed():
        raise PackError("Bloxstrap не установлен — папки Bloxstrap\\Versions нет")
    if version_dir is None:
        raise PackError("Roblox не найден")

    kind = RP.get(pack.meta.kind)
    backup_root = BACKUP_ROOT / version_dir.name

    done, skipped = [], []
    for rel, src in pack.files.items():
        name = PurePosixPath(rel).name
        err = RP.validate(pack.meta.kind, name)
        if err:
            skipped.append(f"{name}: {err}")
            continue
        target = RP.destination(backend, version_dir, pack.meta.kind, name)
        if not dry_run:
            # бэкап оригинала делается только для прямого канала
            if backend == "direct":
                live = version_dir / kind.rel(name)
                if live.is_file():
                    b = backup_root / Path(kind.rel(name))
                    b.parent.mkdir(parents=True, exist_ok=True)
                    if not b.exists():
                        shutil.copy2(live, b)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        done.append(name)

    return {
        "backend": backend,
        "kind": pack.meta.kind,
        "kind_label": kind.label,
        "installed": done,
        "skipped": skipped,
        "dry_run": dry_run,
    }


def _same_as_source(target: Path, source: Path) -> bool:
    """Файл в Roblox — это ровно то, что положил набор, а не чужой оригинал."""
    try:
        if not target.is_file() or not source.is_file():
            return False
        if target.stat().st_size != source.stat().st_size:
            return False
        return sha256_of(target) == sha256_of(source)
    except OSError:
        return False


def uninstall(pack: Pack, version_dir: Path, backend: str = "direct") -> dict:
    """
    Снимает набор.

    direct      файлы возвращаются из бэкапа, если он есть. Без бэкапа
                удаляется только файл, побайтово совпадающий с набором;
                чужой оригинал не трогаем.
    bloxstrap   удаляется только совпадающий файл из Modifications: Bloxstrap
                вернёт оригинал сам при следующем запуске Roblox.
    """
    if backend not in RP.BACKENDS:
        raise PackError(f"неизвестный канал: {backend}")
    if version_dir is None:
        raise PackError("Roblox не найден")
    removed, restored, skipped = [], [], []
    for rel, source in pack.files.items():
        name = PurePosixPath(rel).name
        err = RP.validate(pack.meta.kind, name)
        if err:
            skipped.append(f"{name}: {err}")
            continue
        target = RP.destination(backend, version_dir, pack.meta.kind, name)
        if backend == "bloxstrap":
            if target.is_file():
                if _same_as_source(target, source):
                    target.unlink()
                    removed.append(name)
                else:
                    skipped.append(f"{name}: файл не совпадает с набором")
            continue
        backup = BACKUP_ROOT / version_dir.name / RP.get(pack.meta.kind).rel(name)
        if backup.is_file():
            if target.is_file():
                target.unlink()
                removed.append(name)
            dest = version_dir / RP.get(pack.meta.kind).rel(name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, dest)
            restored.append(name)
        elif target.is_file():
            if _same_as_source(target, source):
                target.unlink()
                removed.append(name)
            else:
                skipped.append(f"{name}: нет бэкапа, файл не совпадает с набором")
    return {"removed": removed, "restored": restored,
            "skipped": skipped, "backend": backend}


def installed_files(version_dir: Path, kind_key: str) -> list[str]:
    """Что сейчас лежит в папке категории в папке версии."""
    d = RP.get(kind_key).target(version_dir)
    return sorted(p.name for p in d.iterdir() if p.is_file()) if d.is_dir() else []


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Сканирование папки наборов
# ─────────────────────────────────────────────────────────────────────────────
def scan_library(root: str | Path) -> list[tuple[Pack, str]]:
    """Все читаемые наборы из папки. Возвращает [(pack, ошибка)] — плохие не теряются молча."""
    root = Path(root)
    out: list[tuple[Pack, str]] = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        try:
            out.append((load_pack(d), ""))
        except (PackError, OSError, ValueError) as exc:
            out.append((_broken(d), str(exc)))
    return out


def _broken(d: Path) -> Pack:
    """Заглушка для набора, который не прочитался, чтобы UI показал его в списке."""
    return Pack(meta=PackMeta(name=d.name), root=d)