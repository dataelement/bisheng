"""冻结目录的对象存储副本: 文件清单指纹与 MANIFEST.

只扫相对路径和文件大小, 不把整盘做 content hash (MinIO/Milvus 可能很大).
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

MANIFEST_NAME = "MANIFEST.json"
STORAGE_KEYS = ("minio", "milvus", "elasticsearch", "etcd")


def tree_inventory(root: Path) -> dict[str, Any]:
    """统计目录: 文件数、字节数、路径+大小的 sha256."""
    base = root.resolve()
    if not base.is_dir():
        return {"bytes": 0, "files": 0, "list_sha256": ""}
    digest = sha256()
    total = 0
    count = 0
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(base).as_posix()
        size = path.stat().st_size
        total += size
        count += 1
        digest.update(rel.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\n")
    return {
        "bytes": total,
        "files": count,
        "list_sha256": digest.hexdigest() if count else "",
    }


def load_manifest(root: Path) -> dict[str, Any] | None:
    path = root / MANIFEST_NAME
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return data


def write_manifest(root: Path, payload: dict[str, Any]) -> Path:
    path = root / MANIFEST_NAME
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def storage_gaps(root: Path, manifest: dict[str, Any] | None) -> list[str]:
    """完整冻结缺哪一块. 空列表表示 MinIO/Milvus/ES/etcd 副本与 MANIFEST 一致."""
    if not manifest:
        return [f"缺少 {MANIFEST_NAME}"]
    if manifest.get("complete_storage") is not True:
        return ["MANIFEST.complete_storage 不是 true"]
    storage = manifest.get("storage")
    if not isinstance(storage, dict):
        return ["MANIFEST.storage 缺失"]
    gaps: list[str] = []
    for key in STORAGE_KEYS:
        item = storage.get(key)
        if not isinstance(item, dict):
            gaps.append(f"MANIFEST 无 {key}")
            continue
        rel = str(item.get("backup_rel") or "").strip()
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            gaps.append(f"{key} backup_rel 非法")
            continue
        dest = (root / rel).resolve()
        try:
            dest.relative_to(root.resolve())
        except ValueError:
            gaps.append(f"{key} backup_rel 跳出冻结目录")
            continue
        if not dest.is_dir():
            gaps.append(f"缺少存储副本 {key}: {rel}")
            continue
        inv = tree_inventory(dest)
        if inv["files"] < 1:
            gaps.append(f"{key} 副本为空")
            continue
        recorded = str(item.get("list_sha256") or "")
        if recorded and recorded != inv["list_sha256"]:
            gaps.append(f"{key} list_sha256 与副本不一致")
        recorded_files = item.get("files")
        if isinstance(recorded_files, int) and recorded_files != inv["files"]:
            gaps.append(f"{key} 文件数与 MANIFEST 不一致")
    return gaps
