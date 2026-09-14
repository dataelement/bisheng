#!/usr/bin/env python3
"""把 A 空间 JSON 里的目录/文件/版本链写入 B。新 ID, 不复用 A 自增主键。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)

VIOLATION = KnowledgeFileStatus.VIOLATION.value


def remap_path(path: str | None, id_map: dict[int, int]) -> str | None:
    """把 A 的 /祖先id 路径改成 B 新文件夹 id。"""
    if not path:
        return None
    parts = [p for p in str(path).split("/") if p]
    if not parts:
        return None
    mapped: list[str] = []
    for part in parts:
        if not part.isdigit():
            continue
        new_id = id_map.get(int(part))
        if new_id is None:
            raise KeyError(f"folder id {part} not mapped")
        mapped.append(str(new_id))
    return "/" + "/".join(mapped) if mapped else None


def _safe_path(path: str | None, id_map: dict[int, int]) -> str | None:
    try:
        return remap_path(path, id_map)
    except KeyError:
        return None


def dst_object_key(batch_no: str, b_space_id: int, a_file_id: int, src_key: str) -> str:
    name = Path(src_key or "file").name
    return f"fusion/{batch_no}/{b_space_id}/{a_file_id}/{name}"


def _put_side_object(
    src_key: str | None,
    local: Path,
    dst_key: str,
    put_object,
    new_object_keys: list[str],
) -> str | None:
    """预览/缩略图: 本地有文件才上传并返回新 key, 否则保持空。"""
    if not (src_key or "").strip():
        return None
    if not local.is_file():
        return None
    put_object(dst_key, local)
    new_object_keys.append(dst_key)
    return dst_key


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def ingest_files(
    session: AsyncSession,
    *,
    export: dict[str, Any],
    b_space_id: int,
    owner_b: int,
    owner_name: str,
    user_map: dict[int, int],
    object_dir: Path,
    batch_no: str,
    existing_file_map: dict[int, dict[str, Any]],
    put_object,
) -> dict[str, Any]:
    """创建文件夹与文件, 拷对象, 重建版本链。已有 b_file_id 的跳过拷贝。"""
    file_repo = KnowledgeFileRepositoryImpl(session)
    doc_repo = KnowledgeDocumentRepositoryImpl(session)
    ver_repo = KnowledgeDocumentVersionRepositoryImpl(session)

    files = list(export.get("files") or [])
    id_map: dict[int, int] = {}
    file_map_rows: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    new_object_keys: list[str] = []
    a_space_id = int(export["space"]["id"])

    folders = [f for f in files if int(f.get("file_type") or 1) == FileType.DIR.value]
    folders.sort(key=lambda f: (int(f.get("level") or 0), int(f["id"])))
    others = [f for f in files if int(f.get("file_type") or 1) != FileType.DIR.value]
    others.sort(key=lambda f: int(f["id"]))

    async def _user(a_uid: int | None) -> tuple[int, str]:
        if a_uid and int(a_uid) in user_map:
            return user_map[int(a_uid)], owner_name
        return owner_b, owner_name

    for folder in folders:
        a_id = int(folder["id"])
        existed = existing_file_map.get(a_id)
        if existed and existed.get("b_file_id"):
            id_map[a_id] = int(existed["b_file_id"])
            continue
        uid, uname = await _user(folder.get("user_id"))
        try:
            folder_path = remap_path(folder.get("file_level_path"), id_map)
        except KeyError as exc:
            exceptions.append(
                {
                    "kind": "minio_missing",
                    "a_space_id": a_space_id,
                    "a_file_id": a_id,
                    "detail": f"folder path remap failed: {exc}",
                }
            )
            folder_path = None
        row = KnowledgeFile(
            user_id=uid,
            user_name=uname,
            knowledge_id=b_space_id,
            file_name=folder.get("file_name") or "folder",
            file_type=FileType.DIR.value,
            file_source=folder.get("file_source") or "space_upload",
            level=int(folder.get("level") or 0),
            file_level_path=folder_path,
            status=KnowledgeFileStatus.SUCCESS.value,
            tenant_id=1,
        )
        saved = await file_repo.save(row)
        id_map[a_id] = int(saved.id)
        file_map_rows.append(
            {
                "a_file_id": a_id,
                "b_file_id": int(saved.id),
                "src_object_key": None,
                "dst_object_key": None,
                "size_bytes": None,
                "content_sha256": None,
            }
        )

    for item in others:
        a_id = int(item["id"])
        existed = existing_file_map.get(a_id)
        src_key = item.get("object_name") or None
        dst_key = None
        sha = None
        size = item.get("file_size")
        if existed and existed.get("b_file_id"):
            id_map[a_id] = int(existed["b_file_id"])
            file_map_rows.append(
                {
                    "a_file_id": a_id,
                    "b_file_id": int(existed["b_file_id"]),
                    "src_object_key": existed.get("src_object_key") or src_key,
                    "dst_object_key": existed.get("dst_object_key"),
                    "size_bytes": existed.get("size_bytes") or size,
                    "content_sha256": existed.get("content_sha256"),
                }
            )
            continue
        uid, uname = await _user(
            item.get("user_id") or item.get("original_uploader_id")
        )
        if src_key:
            dst_key = dst_object_key(batch_no, b_space_id, a_id, src_key)
            local = object_dir / str(a_id)
            if not local.is_file():
                exceptions.append(
                    {
                        "kind": "minio_missing",
                        "a_space_id": a_space_id,
                        "a_file_id": a_id,
                        "detail": src_key,
                    }
                )
                dst_key = None
            else:
                sha = file_sha256(local)
                size = local.stat().st_size
                put_object(dst_key, local)
                new_object_keys.append(dst_key)

        status = int(item.get("status") or KnowledgeFileStatus.WAITING.value)
        row = KnowledgeFile(
            user_id=uid,
            user_name=item.get("user_name") or uname,
            knowledge_id=b_space_id,
            file_name=item.get("file_name") or f"file-{a_id}",
            file_type=FileType.FILE.value,
            file_source=item.get("file_source") or "space_upload",
            level=int(item.get("level") or 0),
            file_level_path=_safe_path(item.get("file_level_path"), id_map),
            file_size=size,
            md5=item.get("md5") or None,
            parse_type=item.get("parse_type") or None,
            status=status,
            object_name=dst_key,
            remark=item.get("remark") or "",
            updater_id=user_map.get(int(item["updater_id"]))
            if item.get("updater_id")
            else None,
            updater_name=item.get("updater_name"),
            tenant_id=1,
            original_uploader_id=user_map.get(int(item["original_uploader_id"]))
            if item.get("original_uploader_id")
            else uid,
            original_knowledge_id=b_space_id,
            entry_type=item.get("entry_type") or None,
            entry_status=item.get("entry_status") or None,
            preview_file_object_name=_put_side_object(
                item.get("preview_file_object_name"),
                object_dir / f"{a_id}.preview",
                dst_object_key(
                    batch_no,
                    b_space_id,
                    a_id,
                    item.get("preview_file_object_name") or "preview",
                ),
                put_object,
                new_object_keys,
            ),
            thumbnails=_put_side_object(
                item.get("thumbnails"),
                object_dir / f"{a_id}.thumb",
                dst_object_key(
                    batch_no, b_space_id, a_id, item.get("thumbnails") or "thumb"
                ),
                put_object,
                new_object_keys,
            ),
        )
        saved = await file_repo.save(row)
        id_map[a_id] = int(saved.id)
        file_map_rows.append(
            {
                "a_file_id": a_id,
                "b_file_id": int(saved.id),
                "src_object_key": src_key,
                "dst_object_key": dst_key,
                "size_bytes": size,
                "content_sha256": sha,
            }
        )

    doc_id_map: dict[int, int] = {}
    ver_id_map: dict[int, int] = {}
    for doc in export.get("documents") or []:
        a_doc_id = int(doc["id"])
        path = _safe_path(doc.get("file_level_path"), id_map)
        entity = KnowledgeDocument(
            tenant_id=1,
            knowledge_id=b_space_id,
            file_level_path=path,
            level=int(doc.get("level") or 0),
            predecessor_logic_file_id=id_map.get(int(doc["predecessor_logic_file_id"]))
            if doc.get("predecessor_logic_file_id")
            else None,
            content_generation=int(doc.get("content_generation") or 0),
            lifecycle_status=doc.get("lifecycle_status") or "active",
        )
        saved_doc = await doc_repo.save(entity)
        doc_id_map[a_doc_id] = int(saved_doc.id)

    versions = list(export.get("versions") or [])
    versions.sort(key=lambda v: (int(v["document_id"]), int(v.get("version_no") or 1)))
    for ver in versions:
        a_file = int(ver["knowledge_file_id"])
        b_file = id_map.get(a_file)
        b_doc = doc_id_map.get(int(ver["document_id"]))
        if not b_file or not b_doc:
            continue
        entity = KnowledgeDocumentVersion(
            document_id=b_doc,
            knowledge_file_id=b_file,
            version_no=int(ver.get("version_no") or 1),
            is_primary=bool(ver.get("is_primary")),
        )
        saved_ver = await ver_repo.save(entity)
        ver_id_map[int(ver["id"])] = int(saved_ver.id)

    for doc in export.get("documents") or []:
        a_doc_id = int(doc["id"])
        b_doc = doc_id_map.get(a_doc_id)
        if not b_doc:
            continue
        primary_a = doc.get("primary_version_id")
        if not primary_a:
            continue
        primary_b = ver_id_map.get(int(primary_a))
        if not primary_b:
            continue
        entity = await doc_repo.find_by_id(b_doc)
        if entity is None:
            continue
        entity.primary_version_id = primary_b
        await doc_repo.update(entity)

    for item in others:
        a_id = int(item["id"])
        b_id = id_map.get(a_id)
        if not b_id:
            continue
        entity = await file_repo.find_by_id(b_id)
        if entity is None:
            continue
        changed = False
        if (
            item.get("reference_document_id")
            and int(item["reference_document_id"]) in doc_id_map
        ):
            entity.reference_document_id = doc_id_map[
                int(item["reference_document_id"])
            ]
            changed = True
        if (
            item.get("predecessor_logic_file_id")
            and int(item["predecessor_logic_file_id"]) in id_map
        ):
            entity.predecessor_logic_file_id = id_map[
                int(item["predecessor_logic_file_id"])
            ]
            changed = True
        if changed:
            await file_repo.update(entity)

    return {
        "file_id_map": id_map,
        "file_map_rows": file_map_rows,
        "doc_map_rows": [
            {"a_doc_id": a_id, "b_doc_id": b_id} for a_id, b_id in doc_id_map.items()
        ],
        "exceptions": exceptions,
        "new_object_keys": new_object_keys,
        "violation_b_ids": [
            id_map[int(f["id"])]
            for f in others
            if int(f.get("status") or 0) == VIOLATION and int(f["id"]) in id_map
        ],
    }
