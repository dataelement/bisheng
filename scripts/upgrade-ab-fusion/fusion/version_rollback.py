"""升级前冻结目录检查. 不连库, 不写现场.

完整冻结: MySQL dump + compose/config + MinIO/Milvus/ES/etcd 副本 + MANIFEST.
不完整冻结 (本轮演练 20260911124114): 只有 dump+compose, hop 禁止继续,
回滚必须 ACCEPT_INCOMPLETE_STORAGE=1.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fusion.freeze_storage import load_manifest, storage_gaps

DUMP_NAME = "mysql-bisheng.sql"
COMPOSE_NAME = "docker-compose.yml"
SHA_NAME = "mysql-bisheng.sql.sha256"
TODO_NAME = "TODO-storage.txt"
CONFIG_NAME = "config.yaml"


def sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_recorded_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip().split()[0]
    return text.lower()


def compose_service_image(compose_text: str, service: str) -> str:
    """取 compose 里某个 service 的 image. 找不到则空串."""
    in_svc = False
    header = re.compile(rf"^  {re.escape(service)}:\s*$")
    next_svc = re.compile(r"^  [A-Za-z0-9._-]+:\s*$")
    for raw in compose_text.splitlines():
        line = raw.rstrip()
        if header.match(line):
            in_svc = True
            continue
        if in_svc and next_svc.match(line):
            break
        if in_svc:
            m = re.match(r"^\s+image:\s+(\S+)\s*$", line)
            if m:
                return m.group(1)
    return ""


def compose_backend_image(compose_text: str) -> str:
    """取 backend 服务的 image."""
    return compose_service_image(compose_text, "backend")


def dump_has_alembic_revision(dump_text: str) -> bool:
    """dump 里 alembic_version 有 revision 行 (2.5 之后)."""
    m = re.search(
        r"INSERT INTO `alembic_version`[^;]*;",
        dump_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return False
    return bool(re.search(r"f[0-9a-z_]+", m.group(0), flags=re.IGNORECASE))


def inspect_freeze_dir(path: Path) -> dict[str, object]:
    """检查冻结目录. errors 非空则 dump/compose 本身不能用."""
    root = path.resolve()
    errors: list[str] = []
    dump = root / DUMP_NAME
    compose = root / COMPOSE_NAME
    sha_file = root / SHA_NAME
    todo = root / TODO_NAME
    config = root / CONFIG_NAME

    if not dump.is_file():
        errors.append(f"缺少 {DUMP_NAME}")
    if not compose.is_file():
        errors.append(f"缺少 {COMPOSE_NAME}")

    sha_ok = False
    sha_recorded = ""
    sha_actual = ""
    if dump.is_file():
        sha_actual = sha256_hex(dump)
        if sha_file.is_file():
            sha_recorded = read_recorded_sha(sha_file)
            sha_ok = sha_recorded == sha_actual
            if not sha_ok:
                errors.append("dump sha256 与记录不一致")
        else:
            errors.append(f"缺少 {SHA_NAME}")

    has_create_db = False
    has_drop_db = False
    alembic_rev = False
    if dump.is_file():
        dump_head = dump.read_text(encoding="utf-8", errors="ignore")[:20000]
        whole = dump.read_text(encoding="utf-8", errors="ignore")
        has_create_db = "CREATE DATABASE" in dump_head and "`bisheng`" in dump_head
        has_drop_db = "DROP DATABASE" in dump_head
        alembic_rev = dump_has_alembic_revision(whole)
        if not has_create_db:
            errors.append("dump 不是 mysqldump --databases bisheng")

    backend_image = ""
    if compose.is_file():
        backend_image = compose_backend_image(
            compose.read_text(encoding="utf-8", errors="ignore")
        )
        if not backend_image:
            errors.append("compose 里没有 backend image")

    manifest = load_manifest(root)
    gaps = storage_gaps(root, manifest)
    complete = not gaps
    incomplete = (not complete) or todo.is_file()

    return {
        "root": str(root),
        "dump": str(dump) if dump.is_file() else "",
        "compose": str(compose) if compose.is_file() else "",
        "config": str(config) if config.is_file() else "",
        "sha_ok": sha_ok,
        "sha_recorded": sha_recorded,
        "sha_actual": sha_actual,
        "backend_image": backend_image,
        "has_create_db": has_create_db,
        "has_drop_db": has_drop_db,
        "incomplete_storage": incomplete,
        "complete_storage": complete,
        "storage_gaps": gaps,
        "todo_storage": todo.is_file(),
        "errors": errors,
        "alembic_revision_in_dump": alembic_rev,
        "manifest_present": manifest is not None,
    }


def pick_freeze_dir(backup_dir: Path, stamp: str) -> Path:
    """BACKUP_STAMP 必须显式给出 (或由 current-freeze.txt 填入), 禁止自动捡最新目录."""
    text = (stamp or "").strip()
    if not text:
        raise ValueError("必须设置 BACKUP_STAMP, 例如 20260911124114")
    dest = backup_dir / text
    if not dest.is_dir():
        raise FileNotFoundError(f"冻结目录不存在: {dest}")
    return dest
