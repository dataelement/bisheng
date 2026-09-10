#!/usr/bin/env python3
# ruff: noqa: E402, RUF001, RUF002, RUF003
"""合并同用户的重复默认个人库，保留 ID 最小者，排除收藏库。

从 src/backend 执行：
  .venv/bin/python scripts/merge_personal_knowledge_spaces.py --all-users
  .venv/bin/python scripts/merge_personal_knowledge_spaces.py --user-id 7 --apply
默认只读预览；多租户必须指定 --tenant-id。来源库 ID、文件 ID 升序迁移，
同目录同名的后迁入文档覆盖前面的及目标原有文档，完整旧版本链永久删除。
保留原文件 ID、原文件地址和版本链, 事务内调整归属后清理空旧库。
优先读取 Milvus, 无可读数据时读取 ES; 索引或附属资源处理失败则迁入后标记解析失败。
数据库、版本完整性和审计失败仍停止, 不伪报合并成功。
单文件部署, 不依赖其他 scripts 脚本。必须停写并串行执行。JSONL 记录不能恢复已覆盖的旧内容，不能代替备份。
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, Protocol

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import col, delete, or_, select

from bisheng.api.services.knowledge_imp import delete_minio_files, delete_vector_files
from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.common.services.config_service import settings
from bisheng.core.context.manager import close_app_context, initialize_app_context
from bisheng.core.context.tenant import (
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    strict_tenant_filter,
    visible_tenant_ids,
)
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTagDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.knowledge.domain.constants import parse_shougang_file_encoding_codes
from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeDao,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import (
    KnowledgeFileSimilarityCandidate,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.models.portal_recommendation_file_projection import (
    PortalRecommendationFileProjection,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.share_link.domain.models.share_link import (
    ResourceTypeEnum as ShareResourceTypeEnum,
)
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.user.domain.models.user import User
from bisheng.worker.knowledge.file_worker import copy_normal, copy_vector

logger = logging.getLogger(__name__)


_LABEL_FORMAT_CHARACTER_TRANSLATION = str.maketrans("", "", "\u200b\ufeff")


class PreflightError(RuntimeError):
    """Raised when validation must stop the whole batch before any write."""


class SourceIndexMismatch(PreflightError):
    """来源两种索引不一致, 无法通过从 Milvus 复制重建相同的 ES 数据。"""


def _read_merge_milvus(source: Knowledge, file_id: int) -> tuple[list[dict], Any]:
    from bisheng.core.ai import FakeEmbeddings
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(0, knowledge=source, embeddings=FakeEmbeddings())
    if store.col is None:
        return [], None
    fields = [f.name for f in store.col.schema.fields]
    iterator = store.col.query_iterator(
        expr=f"document_id=={file_id} && knowledge_id=={source.id}", output_fields=fields, batch_size=500, timeout=60
    )
    rows = []
    try:
        while batch := iterator.next():
            rows.extend(dict(row) for row in batch)
    finally:
        iterator.close()
    return rows, store.col.schema


def _read_merge_es(source: Knowledge, file_id: int) -> list[dict]:
    from elasticsearch.helpers import scan

    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=source)
    client = store.client.options(request_timeout=60, max_retries=0, retry_on_timeout=False)
    index = source.index_name or source.collection_name
    if not client.indices.exists(index=index):
        return []
    rows = []
    for hit in scan(client, index=index, query={"query": {"term": {"metadata.document_id": file_id}}}, size=500):
        body = hit["_source"]
        row = dict(body.get("metadata") or {})
        row["text"] = body.get("text", "")
        if "vector" in body:
            row["vector"] = body["vector"]
        row["_merge_key"] = hit["_id"]
        rows.append(row)
    return rows


def _write_merge_milvus(rows: list[dict], schema: Any, target: Knowledge) -> None:
    from pymilvus import Collection

    from bisheng.core.ai import FakeEmbeddings
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(0, knowledge=target, embeddings=FakeEmbeddings())
    if store.col is None:
        if schema is None:
            raise RuntimeError("ES fallback has no Milvus schema")
        Collection(
            name=target.collection_name, schema=schema, using=store.alias, consistency_level=store.consistency_level
        )
        store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(0, knowledge=target, embeddings=FakeEmbeddings())
    # 相同文件 ID 重跑时只替换该文件在目标库中的向量, 不产生重复主键。
    file_id = int(rows[0]["document_id"])
    store.col.delete(expr=f"document_id=={file_id} && knowledge_id=={target.id}", timeout=60)
    fields = [field.name for field in store.col.schema.fields if not (field.is_primary and field.auto_id)]
    for offset in range(0, len(rows), 500):
        batch = rows[offset : offset + 500]
        result = store.col.insert([[row[name] for row in batch] for name in fields], timeout=60)
        if result.insert_count != len(batch):
            raise RuntimeError(f"Milvus insert incomplete: expected={len(batch)} actual={result.insert_count}")


def _write_merge_es(rows: list[dict], target: Knowledge) -> None:
    from elasticsearch.helpers import bulk

    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=target)
    client = store.client.options(request_timeout=60, max_retries=0, retry_on_timeout=False)
    index = target.index_name or target.collection_name
    actions = []
    for position, row in enumerate(rows):
        metadata = dict(row)
        text = metadata.pop("text", "")
        metadata.pop("vector", None)
        key = metadata.pop("_merge_key", metadata.pop("pk", position))
        actions.append(
            {
                "_index": index,
                "_id": f"merge:{row['document_id']}:{key}",
                "_source": {"text": text, "metadata": metadata},
            }
        )
    bulk(client, actions, chunk_size=100, max_retries=0)
    response = client.indices.refresh(index=index)
    if response.get("_shards", {}).get("failed", 0):
        raise RuntimeError(f"ES refresh failed: {response}")


def _transfer_record_indexes(file: KnowledgeFile, source: Knowledge, target: Knowledge) -> dict[str, Any]:
    result: dict[str, Any] = {"via": "none", "milvus_count": 0, "es_count": 0, "issues": []}
    rows, schema = [], None
    try:
        rows, schema = _read_merge_milvus(source, int(file.id))
    except Exception as exc:
        result["issues"].append(f"read Milvus: {type(exc).__name__}: {exc}")
    if rows:
        result["via"] = "milvus"
    else:
        try:
            rows = _read_merge_es(source, int(file.id))
        except Exception as exc:
            result["issues"].append(f"read ES: {type(exc).__name__}: {exc}")
        if rows:
            result["via"] = "es"
    if not rows:
        result["issues"].append("no readable index chunks; reparse required")
        return result
    rows = copy.deepcopy(rows)
    for row in rows:
        row.update(document_id=int(file.id), knowledge_id=int(target.id))
    if str(source.model) != str(target.model):
        result["issues"].append("embedding model changed; reparse required")
    elif all(row.get("vector") is not None for row in rows):
        try:
            _write_merge_milvus(rows, schema, target)
            result["milvus_count"] = len(rows)
        except Exception as exc:
            result["issues"].append(f"write Milvus: {type(exc).__name__}: {exc}")
    else:
        result["issues"].append("ES chunks contain no vectors; reparse required")
    try:
        _write_merge_es(rows, target)
        result["es_count"] = len(rows)
    except Exception as exc:
        result["issues"].append(f"write ES: {type(exc).__name__}: {exc}")
    return result


def _cleanup_record_indexes(space: Knowledge, target: Knowledge, file_id: int) -> list[str]:
    """两个索引独立清理; 失败留待清理, 不回滚已迁入的文件记录。"""
    from bisheng.core.ai import FakeEmbeddings
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    issues = []
    try:
        store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(0, knowledge=space, embeddings=FakeEmbeddings())
        if store.col is not None:
            store.col.delete(expr=f"document_id=={file_id} && knowledge_id=={space.id}", timeout=60)
    except Exception as exc:
        issues.append(f"cleanup Milvus space={space.id} file={file_id}: {type(exc).__name__}: {exc}")
    try:
        store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=space)
        client = store.client.options(request_timeout=60, max_retries=0, retry_on_timeout=False)
        index = space.index_name or space.collection_name
        filters = [{"term": {"metadata.document_id": file_id}}]
        if index == (target.index_name or target.collection_name) and space.id != target.id:
            filters.append({"term": {"metadata.knowledge_id": int(space.id)}})
        if client.indices.exists(index=index):
            response = client.delete_by_query(index=index, query={"bool": {"filter": filters}}, refresh=True)
            if response.get("failures") or response.get("timed_out"):
                raise RuntimeError(str(response))
    except Exception as exc:
        issues.append(f"cleanup ES space={space.id} file={file_id}: {type(exc).__name__}: {exc}")
    return issues


def _merge_failure_remark(issues: list[str]) -> str:
    from bisheng.common.errcode.knowledge import KnowledgeFileFailedError

    return KnowledgeFileFailedError(exception=RuntimeError("合库完成，需重新解析: " + "; ".join(issues))).to_json_str()


async def _validate_record_graph(session: Any, document: Any, versions: Sequence[Any]) -> Any:
    current = (
        await session.exec(select(KnowledgeDocument).where(KnowledgeDocument.id == document.id).with_for_update())
    ).first()
    actual = list(
        (
            await session.exec(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == document.id)
            )
        ).all()
    )
    if (
        current is None
        or current.model_dump() != document.model_dump()
        or sorted((v.id, v.knowledge_file_id, v.version_no, v.is_primary) for v in actual)
        != sorted((v.id, v.knowledge_file_id, v.version_no, v.is_primary) for v in versions)
    ):
        raise PreflightError(f"version_graph_changed: {document.id}")
    return current


async def _rehome_file_records(candidate: Any, target: Any, transfers: dict[int, dict]) -> list[KnowledgeFile]:
    """同一事务调整文件与文档归属, 保留文件 ID、版本 ID 和所有原文件地址。"""
    async with get_async_db_session() as session:
        try:
            moving = []
            for expected in candidate.files:
                current = (
                    await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == expected.id).with_for_update())
                ).first()
                if current is None or current.model_dump() != expected.model_dump():
                    raise PreflightError(f"source_record_changed: {expected.id}")
                moving.append(current)
            for overwrite in candidate.overwrites:
                for expected in overwrite.files:
                    current = (
                        await session.exec(
                            select(KnowledgeFile).where(KnowledgeFile.id == expected.id).with_for_update()
                        )
                    ).first()
                    if current is None or current.model_dump() != expected.model_dump():
                        raise PreflightError(f"overwrite_record_changed: {expected.id}")
                ids = [f.id for f in overwrite.files]
                if set(ids) & {f.id for f in moving}:
                    raise PreflightError("overwrite_contains_source")
                conditions = [
                    col(KnowledgeFileSimilarityCandidate.source_file_id).in_(ids),
                    col(KnowledgeFileSimilarityCandidate.candidate_file_id).in_(ids),
                ]
                if overwrite.document is not None:
                    await _validate_record_graph(session, overwrite.document, overwrite.versions)
                    conditions.append(KnowledgeFileSimilarityCandidate.candidate_document_id == overwrite.document.id)
                await session.exec(delete(KnowledgeFileSimilarityCandidate).where(or_(*conditions)))
                await session.exec(
                    delete(PortalRecommendationFileProjection).where(
                        col(PortalRecommendationFileProjection.file_id).in_(ids)
                    )
                )
                await session.exec(
                    delete(ShareLink).where(
                        ShareLink.resource_type == ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
                        col(ShareLink.resource_id).in_([str(i) for i in ids]),
                    )
                )
                if overwrite.document is not None:
                    await session.exec(
                        delete(KnowledgeDocumentVersion).where(
                            KnowledgeDocumentVersion.document_id == overwrite.document.id
                        )
                    )
                    await session.exec(delete(KnowledgeDocument).where(KnowledgeDocument.id == overwrite.document.id))
                await session.exec(delete(KnowledgeFile).where(col(KnowledgeFile.id).in_(ids)))
            if candidate.document is not None:
                doc = await _validate_record_graph(session, candidate.document, candidate.versions)
                doc.knowledge_id, doc.file_level_path, doc.level = target.space.id, target.file_level_path, target.level
                session.add(doc)
            for current in moving:
                info = transfers[int(current.id)]
                current.knowledge_id = target.space.id
                current.file_level_path, current.level = target.file_level_path, target.level
                current.user_id, current.user_name = target.owner.user_id, target.owner.user_name
                if current.status != 2:
                    info["issues"].append(f"source parse status={current.status}; reparse required")
                current.status = 3 if info["issues"] else 2
                current.remark = _merge_failure_remark(info["issues"]) if info["issues"] else current.remark
                current.user_metadata = {
                    **(current.user_metadata or {}),
                    "personal_space_merge": {"source_space_id": candidate.source_space.id, **info},
                }
                session.add(current)
            await session.commit()
            for current in moving:
                await session.refresh(current)
            return moving
        except Exception:
            await session.rollback()
            raise


async def _mark_record_for_reparse(file_id: int, issues: list[str]) -> None:
    if not issues:
        return
    async with get_async_db_session() as session:
        record = await session.get(KnowledgeFile, file_id)
        if record is None:
            raise RuntimeError(f"migrated record missing: {file_id}")
        metadata = dict(record.user_metadata or {})
        detail = dict(metadata.get("personal_space_merge") or {})
        detail["issues"] = list(dict.fromkeys([*detail.get("issues", []), *issues]))
        metadata["personal_space_merge"] = detail
        record.user_metadata, record.status = metadata, 3
        record.remark = _merge_failure_remark(detail["issues"])
        session.add(record)
        await session.commit()


async def _delete_empty_space_records(space_id: int) -> None:
    """附属系统不可用时仍移除空旧库; 数据库错误不降级, 非空旧库绝不删除。"""
    async with get_async_db_session() as session:
        try:
            files = list(
                (
                    await session.exec(
                        select(KnowledgeFile).where(KnowledgeFile.knowledge_id == space_id).with_for_update()
                    )
                ).all()
            )
            document = (
                await session.exec(select(KnowledgeDocument).where(KnowledgeDocument.knowledge_id == space_id).limit(1))
            ).first()
            if any(f.file_type != 0 for f in files) or document is not None:
                raise PreflightError("source_not_empty")
            await session.exec(delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == space_id))
            await session.exec(delete(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == space_id))
            await session.exec(delete(Knowledge).where(Knowledge.id == space_id))
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _refresh_merge_projections(file_ids: list[int], space_id: int) -> None:
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
    from bisheng.worker.knowledge.portal_recommendation import enqueue_portal_recommendation_projection_refresh

    await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)
    if not await KnowledgeSpaceContentStat.enqueue_file_stat_async(file_ids):
        raise RuntimeError("content statistics refresh enqueue failed")
    for file_id in file_ids:
        await asyncio.to_thread(enqueue_portal_recommendation_projection_refresh, file_id=file_id)


class TargetCopyError(RuntimeError):
    """Expose a partially created target record to the compensation path."""

    def __init__(self, message: str, target_file: KnowledgeFile | None = None) -> None:
        super().__init__(message)
        self.target_file = target_file


def _copy_with_es_timeout(copy_action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """单文件适配旧容器的复制函数, 设置本次写入和刷新的请求超时。"""
    worker = import_module("bisheng.worker.knowledge.file_worker")
    original_insert = worker.insert_es
    copy_thread = threading.get_ident()

    def insert_es(rows: Any, target: Any, index_name: str) -> Any:
        if threading.get_ident() != copy_thread:
            return original_insert(rows, target, index_name=index_name)
        original_client = target.client
        target.client = original_client.options(request_timeout=60, max_retries=0, retry_on_timeout=False)
        try:
            logger.info("Copying ES index=%s request_timeout=60s", index_name)
            return original_insert(rows, target, index_name=index_name)
        finally:
            target.client = original_client

    # 脚本要求串行执行; 适配仅在本进程本次复制期间生效, 不改容器业务文件。
    worker.insert_es = insert_es
    try:
        return copy_action(*args, **kwargs)
    finally:
        worker.insert_es = original_insert


class RollbackRecordError(RuntimeError):
    """JSONL 回溯记录无法持久化。"""


class OverwritePreconditionError(RuntimeError):
    """覆盖目标在执行前发生变化，禁止继续删除。"""


ROLLBACK_RECORD_SCHEMA_VERSION = 1


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return enum_value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


class RollbackJournal:
    def __init__(self, *, path: Path, run_id: str) -> None:
        self.path = Path(path).expanduser()
        self.run_id = run_id
        self._sequence = 0
        self._buffer: list[str] = []
        self._handle: Any | None = None
        self.failed = False

    def open(self) -> None:
        if self._handle is not None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                self._handle = os.fdopen(file_descriptor, "w", encoding="utf-8")
            except Exception:
                os.close(file_descriptor)
                raise
        except FileExistsError as exc:
            raise RollbackRecordError(f"rollback record already exists: {self.path}") from exc
        except OSError as exc:
            raise RollbackRecordError(f"unable to create rollback record: {self.path}") from exc

    def append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._handle is None:
            raise RollbackRecordError("rollback record is not open")
        self._sequence += 1
        row = {
            "schema_version": ROLLBACK_RECORD_SCHEMA_VERSION,
            "run_id": self.run_id,
            "sequence": self._sequence,
            "event_type": event_type,
            "timestamp": datetime.now().astimezone().isoformat(),
            "payload": payload,
        }
        try:
            self._buffer.append(json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
        except (TypeError, ValueError) as exc:
            raise RollbackRecordError(f"unable to serialize rollback event: {event_type}") from exc

    def flush(self) -> None:
        if self._handle is None:
            raise RollbackRecordError("rollback record is not open")
        if not self._buffer:
            return
        try:
            self._handle.writelines(self._buffer)
            self._handle.flush()
            os.fsync(self._handle.fileno())
        except OSError as exc:
            raise RollbackRecordError(f"unable to persist rollback record: {self.path}") from exc
        self._buffer.clear()

    def close(self, *, flush: bool = True) -> None:
        if self._handle is None:
            return
        try:
            if flush:
                self.flush()
        finally:
            self._handle.close()
            self._handle = None


@dataclass(frozen=True)
class SourceFolderRef:
    source_folder_id: int
    folder_name: str
    source_file_level_path: str
    source_level: int


@dataclass(frozen=True)
class TargetContext:
    tenant_id: int
    space: Knowledge
    folder: KnowledgeFile | None
    owner: User
    file_level_path: str
    level: int

    @property
    def key(self) -> tuple[int, int]:
        return int(self.space.id or 0), int(self.folder.id or 0) if self.folder else 0


@dataclass(frozen=True)
class OverwriteTarget:
    logical_id: str
    files: tuple[KnowledgeFile, ...]
    document: KnowledgeDocument | None = None
    versions: tuple[KnowledgeDocumentVersion, ...] = ()
    matched_file_ids: tuple[int, ...] = ()
    match_reasons: tuple[Literal["name", "md5"], ...] = ()


@dataclass(frozen=True)
class OverwriteResolution:
    target: OverwriteTarget | None = None
    reason_code: str = ""
    reason: str = ""


@dataclass
class FileMoveResult:
    source_file_id: int
    source_space_id: int
    source_file_name: str
    status: Literal["ready", "success", "failed"]
    unit_id: str = ""
    unit_type: Literal["file", "version_chain"] = "file"
    source_document_id: int | None = None
    target_document_id: int | None = None
    target_version_id: int | None = None
    version_no: int | None = None
    target_space_id: int | None = None
    target_folder_id: int | None = None
    target_file_id: int | None = None
    category_code: str = ""
    category_label: str = ""
    subcategory_code: str = ""
    subcategory_label: str = ""
    source_deleted: bool = False
    target_cleanup_succeeded: bool | None = None
    reason_code: str = ""
    error: str = ""
    cleanup_errors: list[str] = field(default_factory=list)
    overwrite_cleanup_errors: list[str] = field(default_factory=list)
    folder_mappings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OverwriteDeletionStep:
    component: str
    status: Literal["success", "failed"]
    target_file_id: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True)
class MigrationUnit:
    unit_id: str
    unit_type: Literal["file", "version_chain"]
    source_files: tuple[KnowledgeFile, ...]
    target: TargetContext
    category_code: str
    category_label: str
    subcategory_code: str
    subcategory_label: str
    source_folder_chain: tuple[SourceFolderRef, ...] = ()
    target_folder_plan: tuple[TargetFolderPlanStep, ...] = ()
    overwrite_target: OverwriteTarget | None = None
    source_document: KnowledgeDocument | None = None
    source_versions: tuple[KnowledgeDocumentVersion, ...] = ()


@dataclass(frozen=True)
class TargetFolderPlanStep:
    source_folder_id: int
    source_folder_name: str
    source_file_level_path: str
    target_folder_id: int | None
    target_parent_folder_id: int | None
    target_folder_name: str
    target_file_level_path: str | None
    target_full_path: str | None
    target_relative_name_path: str
    target_level: int
    action: Literal["planned", "reused"]


@dataclass(frozen=True)
class FolderMapping:
    source_folder_id: int
    source_folder_name: str
    source_file_level_path: str
    target_folder_id: int
    target_folder_name: str
    target_file_level_path: str
    target_full_path: str
    target_level: int
    action: Literal["created", "reused"]


@dataclass(frozen=True)
class TagSnapshot:
    approved_ids: tuple[int, ...] = ()
    pending_review_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class IndexSnapshot:
    milvus_count: int
    es_count: int


@dataclass(frozen=True)
class SourceSnapshot:
    tags: TagSnapshot
    permissions: tuple[dict[str, str], ...]
    indexes: IndexSnapshot
    storage_exists: dict[str, bool]


@dataclass
class StopController:
    requested: bool = False

    def request_stop(self) -> None:
        self.requested = True


@dataclass
class CompletedMigration:
    unit: MigrationUnit
    results: list[FileMoveResult]


class MoveOperations(Protocol):
    async def snapshot_unit(self, unit: MigrationUnit) -> None: ...

    async def copy_file(self, source_file: KnowledgeFile, target: TargetContext) -> KnowledgeFile: ...

    async def copy_tags(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None: ...

    async def write_permissions(self, target_file: KnowledgeFile, target: TargetContext) -> None: ...

    async def verify_target(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None: ...

    async def delete_source(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None: ...

    async def restore_source(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> list[str]: ...

    async def cleanup_target(self, target_file: KnowledgeFile, target: TargetContext) -> list[str]: ...


class VersionGraphStore(Protocol):
    async def create_target_graph(
        self,
        unit: MigrationUnit,
        target_files: Sequence[KnowledgeFile],
    ) -> int: ...

    async def verify_target_graph(
        self,
        unit: MigrationUnit,
        target_document_id: int,
        target_files: Sequence[KnowledgeFile],
    ) -> None: ...

    async def delete_source_graph(self, unit: MigrationUnit) -> None: ...

    async def restore_source_graph(self, unit: MigrationUnit) -> list[str]: ...

    async def delete_target_graph(self, target_document_id: int) -> list[str]: ...

    def get_target_graph_payload(self, target_document_id: int) -> dict[str, Any] | None: ...


class TargetFolderStore(Protocol):
    async def list_folders(self, space_id: int) -> Sequence[KnowledgeFile]: ...

    async def create_folder_record(
        self,
        source_folder: SourceFolderRef,
        parent_folder: KnowledgeFile,
        target: TargetContext,
    ) -> KnowledgeFile: ...

    async def write_folder_permissions(
        self,
        folder: KnowledgeFile,
        parent_folder: KnowledgeFile,
        target: TargetContext,
    ) -> None: ...

    async def is_folder_empty(self, folder: KnowledgeFile) -> bool: ...

    async def delete_folder(self, folder: KnowledgeFile) -> None: ...


class TargetFolderManager:
    def __init__(self, store: TargetFolderStore) -> None:
        self.store = store
        self._folders_by_space: dict[int, list[KnowledgeFile]] = {}
        self._folders_by_id: dict[int, KnowledgeFile] = {}
        self._mappings_by_unit_id: dict[str, list[FolderMapping]] = {}

    async def _folders_for_space(self, space_id: int) -> list[KnowledgeFile]:
        cached = self._folders_by_space.get(space_id)
        if cached is not None:
            return cached
        folders = list(await self.store.list_folders(space_id))
        self._folders_by_space[space_id] = folders
        self._folders_by_id.update({int(folder.id): folder for folder in folders if folder.id is not None})
        return folders

    @staticmethod
    def _mapping(
        source_folder: SourceFolderRef,
        target_folder: KnowledgeFile,
        action: Literal["created", "reused"],
    ) -> FolderMapping:
        return FolderMapping(
            source_folder_id=source_folder.source_folder_id,
            source_folder_name=source_folder.folder_name,
            source_file_level_path=source_folder.source_file_level_path,
            target_folder_id=int(target_folder.id or 0),
            target_folder_name=target_folder.file_name,
            target_file_level_path=target_folder.file_level_path or "",
            target_full_path=_folder_child_path(target_folder),
            target_level=int(target_folder.level or 0),
            action=action,
        )

    async def prepare_unit(self, unit: MigrationUnit) -> MigrationUnit:
        mappings = self._mappings_by_unit_id.setdefault(unit.unit_id, [])
        if not unit.source_folder_chain:
            return unit

        space_id = int(unit.target.space.id or 0)
        folders = await self._folders_for_space(space_id)
        if mappings:
            parent_folder = self._folders_by_id.get(mappings[-1].target_folder_id)
            if parent_folder is None:
                raise RuntimeError(f"prepared target folder {mappings[-1].target_folder_id} is no longer available")
        else:
            parent_folder = unit.target.folder
        for source_folder in unit.source_folder_chain[len(mappings) :]:
            parent_path = _folder_child_path(parent_folder)
            candidates = [
                folder
                for folder in folders
                if (folder.file_level_path or "").rstrip("/") == parent_path
                and _normalize_label(folder.file_name) == _normalize_label(source_folder.folder_name)
            ]
            if len(candidates) > 1:
                raise RuntimeError(
                    "multiple target folders match the same parent and normalized name: "
                    f"parent={parent_folder.id}, name={source_folder.folder_name}"
                )
            if candidates:
                target_folder = candidates[0]
                if int(target_folder.status or 0) != KnowledgeFileStatus.SUCCESS.value:
                    raise RuntimeError(f"target folder {target_folder.id} is not in SUCCESS status")
                action: Literal["created", "reused"] = "reused"
            else:
                target_folder = await self.store.create_folder_record(
                    source_folder,
                    parent_folder,
                    unit.target,
                )
                if target_folder.id is None:
                    raise RuntimeError("target folder creation returned no ID")
                folders.append(target_folder)
                self._folders_by_id[int(target_folder.id)] = target_folder
                action = "created"

            mapping = self._mapping(source_folder, target_folder, action)
            mappings.append(mapping)
            if action == "created":
                await self.store.write_folder_permissions(target_folder, parent_folder, unit.target)
            parent_folder = target_folder

        final_target = TargetContext(
            tenant_id=unit.target.tenant_id,
            space=unit.target.space,
            folder=parent_folder,
            owner=unit.target.owner,
            file_level_path=_folder_child_path(parent_folder),
            level=int(parent_folder.level or 0) + 1,
        )
        return replace(unit, target=final_target)

    def get_unit_mappings(self, unit_id: str) -> tuple[FolderMapping, ...]:
        return tuple(self._mappings_by_unit_id.get(unit_id, ()))

    def release_unit(self, unit_id: str) -> None:
        self._mappings_by_unit_id.pop(unit_id, None)

    async def cleanup_unit_folders(self, unit_id: str) -> list[str]:
        errors: list[str] = []
        descendant_preserved = False
        for mapping in reversed(self._mappings_by_unit_id.get(unit_id, ())):
            if mapping.action != "created":
                continue
            folder = self._folders_by_id.get(mapping.target_folder_id)
            if folder is None:
                continue
            if descendant_preserved:
                errors.append(f"target folder {mapping.target_folder_id} was preserved because a descendant remains")
                continue
            try:
                is_empty = await self.store.is_folder_empty(folder)
            except Exception as exc:
                descendant_preserved = True
                errors.append(f"check target folder {mapping.target_folder_id}: {type(exc).__name__}: {exc}")
                continue
            if not is_empty:
                descendant_preserved = True
                errors.append(f"target folder {mapping.target_folder_id} was preserved because it is not empty")
                continue
            try:
                await self.store.delete_folder(folder)
            except Exception as exc:
                descendant_preserved = True
                errors.append(f"delete target folder {mapping.target_folder_id}: {type(exc).__name__}: {exc}")
                continue
            self._folders_by_id.pop(mapping.target_folder_id, None)
            space_folders = self._folders_by_space.get(int(folder.knowledge_id), [])
            self._folders_by_space[int(folder.knowledge_id)] = [
                item for item in space_folders if int(item.id or 0) != mapping.target_folder_id
            ]
        return errors


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _normalize_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_label(value: Any) -> str:
    return str(value or "").translate(_LABEL_FORMAT_CHARACTER_TRANSLATION).strip()


def _folder_child_path(folder: KnowledgeFile) -> str:
    base = (folder.file_level_path or "").rstrip("/")
    return f"{base}/{folder.id}" if base else f"/{folder.id}"


def _version_no_by_file(versions: Sequence[KnowledgeDocumentVersion]) -> dict[int, int]:
    return {int(version.knowledge_file_id): int(version.version_no) for version in versions}


class TargetConflictIndex:
    def __init__(
        self,
        files: Sequence[KnowledgeFile],
        documents_by_id: dict[int, KnowledgeDocument],
        versions: Sequence[KnowledgeDocumentVersion],
    ) -> None:
        self.files_by_id = {
            int(record.id): record
            for record in files
            if record.id is not None and int(record.file_type) == FileType.FILE.value
        }
        self.documents_by_id = documents_by_id
        self.versions_by_file: dict[int, list[KnowledgeDocumentVersion]] = defaultdict(list)
        self.versions_by_document: dict[int, list[KnowledgeDocumentVersion]] = defaultdict(list)
        for version in versions:
            self.versions_by_file[int(version.knowledge_file_id)].append(version)
            self.versions_by_document[int(version.document_id)].append(version)

        self.files_by_name: dict[tuple[int, str, str], list[KnowledgeFile]] = defaultdict(list)
        self.files_by_md5: dict[tuple[int, str], list[KnowledgeFile]] = defaultdict(list)
        for record in self.files_by_id.values():
            self.files_by_name[(int(record.knowledge_id), record.file_level_path or "", record.file_name)].append(
                record
            )
            if record.md5:
                self.files_by_md5[(int(record.knowledge_id), str(record.md5))].append(record)

    @staticmethod
    def _valid_version_graph(
        document: KnowledgeDocument,
        versions: Sequence[KnowledgeDocumentVersion],
    ) -> bool:
        primary_versions = [version for version in versions if version.is_primary]
        version_ids = [version.id for version in versions]
        version_numbers = [int(version.version_no) for version in versions]
        file_ids = [int(version.knowledge_file_id) for version in versions]
        return bool(
            len(primary_versions) == 1
            and all(version_id is not None for version_id in version_ids)
            and len(set(version_ids)) == len(version_ids)
            and all(version_no > 0 for version_no in version_numbers)
            and len(set(version_numbers)) == len(version_numbers)
            and len(set(file_ids)) == len(file_ids)
            and document.primary_version_id is not None
            and int(document.primary_version_id) == int(primary_versions[0].id or 0)
        )

    def resolve(
        self,
        unit: MigrationUnit,
        *,
        target_path: str | None,
    ) -> OverwriteResolution:
        space_id = int(unit.target.space.id or 0)
        matched_reasons_by_file: dict[int, set[Literal["name", "md5"]]] = defaultdict(set)
        for source_file in unit.source_files:
            if target_path is not None:
                for target_file in self.files_by_name.get(
                    (space_id, target_path, source_file.file_name),
                    (),
                ):
                    matched_reasons_by_file[int(target_file.id or 0)].add("name")
            if source_file.md5:
                for target_file in self.files_by_md5.get((space_id, str(source_file.md5)), ()):
                    matched_reasons_by_file[int(target_file.id or 0)].add("md5")

        if not matched_reasons_by_file:
            return OverwriteResolution()

        logical_keys: set[tuple[str, int]] = set()
        for file_id in matched_reasons_by_file:
            file_versions = self.versions_by_file.get(file_id, [])
            if len(file_versions) > 1:
                return OverwriteResolution(
                    reason_code="target_overwrite_invalid_graph",
                    reason=f"target file {file_id} belongs to multiple version rows",
                )
            if file_versions:
                logical_keys.add(("document", int(file_versions[0].document_id)))
            else:
                logical_keys.add(("file", file_id))

        if len(logical_keys) != 1:
            logical_ids = [f"{kind}:{identifier}" for kind, identifier in sorted(logical_keys)]
            return OverwriteResolution(
                reason_code="target_overwrite_ambiguous",
                reason=f"target conflicts span multiple logical documents: {logical_ids}",
            )

        logical_kind, logical_identifier = next(iter(logical_keys))
        matched_file_ids = tuple(sorted(matched_reasons_by_file))
        match_reasons = tuple(
            reason
            for reason in ("name", "md5")
            if any(reason in reasons for reasons in matched_reasons_by_file.values())
        )
        if logical_kind == "file":
            target_file = self.files_by_id.get(logical_identifier)
            if target_file is None:
                return OverwriteResolution(
                    reason_code="target_overwrite_incomplete",
                    reason=f"target file {logical_identifier} is missing",
                )
            return OverwriteResolution(
                target=OverwriteTarget(
                    logical_id=f"file:{logical_identifier}",
                    files=(target_file,),
                    matched_file_ids=matched_file_ids,
                    match_reasons=match_reasons,
                )
            )

        document = self.documents_by_id.get(logical_identifier)
        ordered_versions = tuple(
            sorted(
                self.versions_by_document.get(logical_identifier, ()),
                key=lambda version: (int(version.version_no), int(version.id or 0)),
            )
        )
        chain_files = tuple(self.files_by_id.get(int(version.knowledge_file_id)) for version in ordered_versions)
        if (
            document is None
            or not ordered_versions
            or any(record is None for record in chain_files)
            or not self._valid_version_graph(document, ordered_versions)
            or int(document.knowledge_id) != space_id
            or any(int(record.knowledge_id) != space_id for record in chain_files if record is not None)
        ):
            return OverwriteResolution(
                reason_code="target_overwrite_invalid_graph",
                reason=f"target version graph document:{logical_identifier} is incomplete or invalid",
            )
        return OverwriteResolution(
            target=OverwriteTarget(
                logical_id=f"document:{logical_identifier}",
                files=tuple(record for record in chain_files if record is not None),
                document=document,
                versions=ordered_versions,
                matched_file_ids=matched_file_ids,
                match_reasons=match_reasons,
            )
        )


@contextmanager
def _tenant_scope(tenant_id: int):
    tenant_token = set_current_tenant_id(tenant_id)
    visible_token = set_visible_tenant_ids(frozenset({tenant_id}))
    try:
        with strict_tenant_filter():
            yield
    finally:
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)


@contextmanager
def _sigint_stop_scope(controller: StopController, *, enabled: bool):
    if not enabled:
        yield
        return
    try:
        previous_handler = signal.getsignal(signal.SIGINT)

        def request_stop(_signum: int, _frame: Any) -> None:
            if not controller.requested:
                print("SIGINT received; finishing the current migration unit before stopping.", file=sys.stderr)
            controller.request_stop()

        signal.signal(signal.SIGINT, request_stop)
    except (ValueError, OSError):
        logger.warning("Unable to install SIGINT handler; graceful stop is unavailable in this thread")
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def _storage_object_names(file: KnowledgeFile) -> dict[str, str]:
    preview = KnowledgeUtils.resolve_preview_object_name(
        int(file.id or 0), file.file_name, file.preview_file_object_name
    )
    return {
        "original": str(file.object_name or ""),
        "converted": str(file.id or ""),
        "bbox": str(file.bbox_object_name or ""),
        "preview": str(preview or ""),
    }


def _storage_exists(file: KnowledgeFile) -> dict[str, bool]:
    client = get_minio_storage_sync()
    return {
        key: bool(name) and bool(client.object_exists_sync(client.bucket, name))
        for key, name in _storage_object_names(file).items()
    }


def _overwrite_object_names(file: KnowledgeFile) -> tuple[str, ...]:
    metadata = file.user_metadata or {}
    names = {
        name
        for name in (
            *_storage_object_names(file).values(),
            str(file.thumbnails or ""),
            str(metadata.get("pdf_preview_object_name") or ""),
        )
        if name
    }
    return tuple(sorted(names))


def _copy_object_if_present(source_name: str, target_name: str) -> None:
    if not source_name or not target_name:
        return
    client = get_minio_storage_sync()
    if not client.object_exists_sync(client.bucket, source_name):
        return
    client.copy_object_sync(
        source_bucket=client.bucket,
        source_object=source_name,
        dest_bucket=client.bucket,
        dest_object=target_name,
    )


def _target_preview_object_name(source_file: KnowledgeFile, target_file: KnowledgeFile) -> str:
    canonical_name = KnowledgeUtils.get_knowledge_preview_file_object_name(
        int(target_file.id or 0),
        target_file.file_name,
    )
    if canonical_name:
        return canonical_name
    source_name = _storage_object_names(source_file)["preview"]
    if not source_name:
        return ""
    suffix = Path(source_name).suffix
    return f"preview/{target_file.id}{suffix}"


def _count_milvus_records(space: Knowledge, file_id: int) -> int:
    from bisheng.core.ai import FakeEmbeddings
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
        0,
        knowledge=space,
        embeddings=FakeEmbeddings(),
    )
    if store.col is None:
        return 0
    expression = f"document_id=={file_id} && knowledge_id=={space.id}"
    if hasattr(store.col, "query_iterator"):
        iterator = store.col.query_iterator(expr=expression, output_fields=["pk"], batch_size=1000)
        count = 0
        try:
            while True:
                batch = iterator.next()
                if not batch:
                    break
                count += len(batch)
        finally:
            iterator.close()
        return count
    return len(store.col.query(expr=expression, output_fields=["pk"], limit=16384))


def _count_es_records(space: Knowledge, file_id: int) -> int:
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=space)
    index_name = space.index_name or space.collection_name
    if store is None or not store.client.indices.exists(index=index_name):
        return 0
    response = store.client.count(
        index=index_name,
        query={"bool": {"filter": [{"term": {"metadata.document_id": file_id}}]}},
    )
    return int(response.get("count", 0))


def _index_snapshot(space: Knowledge, file_id: int) -> IndexSnapshot:
    return IndexSnapshot(
        milvus_count=_count_milvus_records(space, file_id),
        es_count=_count_es_records(space, file_id),
    )


def _refresh_es_after_delete(space: Knowledge) -> None:
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=space)
    index_name = space.index_name or space.collection_name
    if store is None or not store.client.indices.exists(index=index_name):
        return
    # 仅延长维护刷新请求的等待时间；不改全局客户端，也不重复发送超时请求。
    client = store.client.options(request_timeout=60, max_retries=0, retry_on_timeout=False)
    logger.info("Refreshing ES for verification index=%s request_timeout=60s", index_name)
    response = client.indices.refresh(index=index_name)
    if response.get("_shards", {}).get("failed", 0):
        raise RuntimeError(f"ES refresh failed: {response}")


async def _verify_source_indexes_deleted(space: Knowledge, file_id: int) -> None:
    """删除后的短暂可见性延迟不应直接触发整份文档回迁。"""
    for delay in (0, 0.25, 0.5, 1.0):
        if delay:
            await asyncio.sleep(delay)
        indexes = await asyncio.to_thread(_index_snapshot, space, file_id)
        permissions = await _read_permission_tuples(file_id)
        if not (indexes.milvus_count or indexes.es_count or permissions):
            return
        logger.warning(
            "Source cleanup pending file_id=%s milvus_count=%s es_count=%s permission_count=%s",
            file_id,
            indexes.milvus_count,
            indexes.es_count,
            len(permissions),
        )
    if indexes.es_count:
        try:
            await asyncio.to_thread(_refresh_es_after_delete, space)
        except Exception as exc:
            raise RuntimeError(f"来源删除后 ES 刷新失败: file_id={file_id}; {type(exc).__name__}: {exc}") from exc
        indexes = await asyncio.to_thread(_index_snapshot, space, file_id)
        permissions = await _read_permission_tuples(file_id)
    if indexes.milvus_count or indexes.es_count or permissions:
        raise RuntimeError(
            f"来源索引或权限仍存在: file_id={file_id}; milvus_count={indexes.milvus_count}; "
            f"es_count={indexes.es_count}; permission_count={len(permissions)}"
        )


async def _tag_snapshot(file_id: int, tenant_id: int) -> TagSnapshot:
    resource_id = str(file_id)
    approved = await TagDao.aget_resource_tag_ids_batch([resource_id], ResourceTypeEnum.SPACE_FILE)
    pending = await asyncio.to_thread(
        ReviewTagDao.get_tags_by_resource_batch,
        [ResourceTypeEnum.SPACE_FILE],
        [resource_id],
        tenant_id=tenant_id,
    )
    return TagSnapshot(
        approved_ids=tuple(sorted({int(tag_id) for tag_id in approved.get(resource_id, [])})),
        pending_review_ids=tuple(
            sorted(
                {
                    int(tag.id)
                    for tag in pending.get(resource_id, [])
                    if tag.id is not None and getattr(tag, "review_status", 0) == 0
                }
            )
        ),
    )


async def _read_resource_permission_tuples(object_ref: str) -> tuple[dict[str, str], ...]:
    fga = PermissionService._get_fga()
    if fga is None:
        raise PreflightError("OpenFGA is unavailable")
    rows = await fga.read_tuples(object=object_ref)
    return tuple(
        {"user": str(row["user"]), "relation": str(row["relation"]), "object": str(row["object"])}
        for row in (rows or [])
    )


async def _read_permission_tuples(file_id: int) -> tuple[dict[str, str], ...]:
    return await _read_resource_permission_tuples(f"knowledge_file:{file_id}")


async def _replace_resource_permission_tuples(
    object_ref: str,
    desired: Sequence[dict[str, str]],
) -> None:
    existing = await _read_resource_permission_tuples(object_ref)
    operations = [
        TupleOperation(action="delete", user=row["user"], relation=row["relation"], object=row["object"])
        for row in existing
    ]
    operations.extend(
        TupleOperation(action="write", user=row["user"], relation=row["relation"], object=row["object"])
        for row in desired
    )
    if operations:
        await PermissionService.batch_write_tuples(
            operations,
            crash_safe=True,
            raise_on_failure=True,
            stop_on_failure=True,
        )


async def _replace_permission_tuples(file_id: int, desired: Sequence[dict[str, str]]) -> None:
    await _replace_resource_permission_tuples(f"knowledge_file:{file_id}", desired)


async def _clear_tag_links(file_id: int, owner_id: int, tenant_id: int) -> None:
    resource_id = str(file_id)
    await TagDao.aupdate_resource_tags([], resource_id, ResourceTypeEnum.SPACE_FILE, owner_id)
    await ReviewTagDao.aupdate_resource_tags(
        [], resource_id, ResourceTypeEnum.SPACE_FILE, owner_id, tenant_id=tenant_id
    )


async def _restore_tag_links(file_id: int, owner_id: int, tenant_id: int, snapshot: TagSnapshot) -> None:
    resource_id = str(file_id)
    await TagDao.aupdate_resource_tags(list(snapshot.approved_ids), resource_id, ResourceTypeEnum.SPACE_FILE, owner_id)
    await ReviewTagDao.aupdate_resource_tags(
        list(snapshot.pending_review_ids),
        resource_id,
        ResourceTypeEnum.SPACE_FILE,
        owner_id,
        tenant_id=tenant_id,
    )


def _target_permission_rows(
    target_file: KnowledgeFile,
    target: TargetContext,
) -> tuple[dict[str, str], ...]:
    object_ref = f"knowledge_file:{target_file.id}"
    return (
        {"user": f"user:{target.owner.user_id}", "relation": "owner", "object": object_ref},
        {
            "user": f"folder:{target.folder.id}" if target.folder else f"knowledge_space:{target.space.id}",
            "relation": "parent",
            "object": object_ref,
        },
    )


def _target_folder_permission_rows(
    folder: KnowledgeFile,
    parent_folder: KnowledgeFile,
    target: TargetContext,
) -> tuple[dict[str, str], ...]:
    object_ref = f"folder:{folder.id}"
    return (
        {"user": f"user:{target.owner.user_id}", "relation": "owner", "object": object_ref},
        {"user": f"folder:{parent_folder.id}", "relation": "parent", "object": object_ref},
    )


class DatabaseTargetFolderStore:
    async def list_folders(self, space_id: int) -> Sequence[KnowledgeFile]:
        return await KnowledgeFileDao.aget_folders_by_space(space_id)

    async def create_folder_record(
        self,
        source_folder: SourceFolderRef,
        parent_folder: KnowledgeFile,
        target: TargetContext,
    ) -> KnowledgeFile:
        return await KnowledgeFileDao.aadd_file(
            KnowledgeFile(
                tenant_id=target.tenant_id,
                knowledge_id=int(target.space.id or 0),
                user_id=int(target.owner.user_id),
                user_name=target.owner.user_name,
                updater_id=int(target.owner.user_id),
                updater_name=target.owner.user_name,
                file_name=source_folder.folder_name,
                file_type=FileType.DIR.value,
                level=int(parent_folder.level or 0) + 1,
                file_level_path=_folder_child_path(parent_folder),
                status=KnowledgeFileStatus.SUCCESS.value,
            )
        )

    async def write_folder_permissions(
        self,
        folder: KnowledgeFile,
        parent_folder: KnowledgeFile,
        target: TargetContext,
    ) -> None:
        await _replace_resource_permission_tuples(
            f"folder:{folder.id}",
            _target_folder_permission_rows(folder, parent_folder, target),
        )

    async def is_folder_empty(self, folder: KnowledgeFile) -> bool:
        async with get_async_db_session() as session:
            child = (
                await session.exec(
                    select(KnowledgeFile.id)
                    .where(
                        KnowledgeFile.knowledge_id == int(folder.knowledge_id),
                        KnowledgeFile.file_level_path == _folder_child_path(folder),
                    )
                    .limit(1)
                )
            ).first()
        return child is None

    async def delete_folder(self, folder: KnowledgeFile) -> None:
        await _replace_resource_permission_tuples(f"folder:{folder.id}", ())
        await KnowledgeFileDao.adelete_batch([int(folder.id or 0)])


class BishengMoveOperations:
    def __init__(self, tenant_id: int, source_spaces: dict[int, Knowledge]) -> None:
        self.tenant_id = tenant_id
        self.source_spaces = source_spaces
        self.snapshots: dict[int, SourceSnapshot] = {}
        self.target_files_by_source_id: dict[int, KnowledgeFile] = {}
        self.failed_copy_target_ids: set[int] = set()
        self.folder_manager = TargetFolderManager(DatabaseTargetFolderStore())

    async def prepare_unit_target(self, unit: MigrationUnit) -> MigrationUnit:
        return await self.folder_manager.prepare_unit(unit)

    def get_unit_folder_mappings(self, unit_id: str) -> tuple[FolderMapping, ...]:
        return self.folder_manager.get_unit_mappings(unit_id)

    async def cleanup_unit_folders(self, unit_id: str) -> list[str]:
        return await self.folder_manager.cleanup_unit_folders(unit_id)

    def release_unit_folders(self, unit_id: str) -> None:
        self.folder_manager.release_unit(unit_id)

    def _accepts_copied_status(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> bool:
        return int(target_file.status or 0) == KnowledgeFileStatus.SUCCESS.value

    def _source_space(self, source_file: KnowledgeFile) -> Knowledge:
        try:
            return self.source_spaces[int(source_file.knowledge_id)]
        except KeyError as exc:
            raise PreflightError(f"source space {source_file.knowledge_id} is outside the plan") from exc

    async def _snapshot_source(self, source_file: KnowledgeFile) -> SourceSnapshot:
        file_id = int(source_file.id or 0)
        cached = self.snapshots.get(file_id)
        if cached is not None:
            return cached
        snapshot = SourceSnapshot(
            tags=await _tag_snapshot(file_id, self.tenant_id),
            permissions=await _read_permission_tuples(file_id),
            indexes=await asyncio.to_thread(_index_snapshot, self._source_space(source_file), file_id),
            storage_exists=await asyncio.to_thread(_storage_exists, source_file),
        )
        self.snapshots[file_id] = snapshot
        return snapshot

    async def snapshot_unit(self, unit: MigrationUnit) -> None:
        for source_file in unit.source_files:
            snapshot = await self._snapshot_source(source_file)
            indexes = snapshot.indexes
            # 正常文件不增加读取; 不一致时短暂复查, 避免把可见性延迟当作源数据缺失。
            for delay in (0.25, 0.5, 1.0):
                if indexes.milvus_count == indexes.es_count:
                    break
                await asyncio.sleep(delay)
                indexes = await asyncio.to_thread(_index_snapshot, self._source_space(source_file), source_file.id)
            if indexes.milvus_count != indexes.es_count:
                raise SourceIndexMismatch(
                    f"source_index_count_mismatch: file_id={source_file.id}; "
                    f"milvus_count={indexes.milvus_count}; es_count={indexes.es_count}; 来源保留, 需修复索引后再迁移"
                )
            self.snapshots[int(source_file.id)] = replace(snapshot, indexes=indexes)

    async def copy_file(self, source_file: KnowledgeFile, target: TargetContext) -> KnowledgeFile:
        snapshot = await self._snapshot_source(source_file)
        target_file = await asyncio.to_thread(
            _copy_with_es_timeout,
            copy_normal,
            source_file,
            self._source_space(source_file),
            target.space,
            int(target.owner.user_id),
            target_level=target.level,
            target_file_level_path=target.file_level_path,
        )
        if target_file is None or target_file.id is None:
            raise TargetCopyError("copy_normal did not create a target file")
        try:
            if not self._accepts_copied_status(source_file, target_file):
                # 底层可能吞掉写入超时; 请求仍可能完成, 不能立即清掉副本记录。
                self.failed_copy_target_ids.add(int(target_file.id))
                raise RuntimeError(
                    f"target file status is {target_file.status}, incompatible with source status {source_file.status}; "
                    f"target_file_id={target_file.id}; copy_failure={target_file.remark or 'unavailable'}"
                )
            target_file.user_id = int(target.owner.user_id)
            target_file.user_name = target.owner.user_name
            target_file.updater_id = int(target.owner.user_id)
            target_file.updater_name = target.owner.user_name

            source_preview = _storage_object_names(source_file)["preview"]
            target_preview = _target_preview_object_name(source_file, target_file)
            if snapshot.storage_exists.get("preview", False):
                await asyncio.to_thread(_copy_object_if_present, source_preview, target_preview)
                target_file.preview_file_object_name = target_preview
            else:
                target_file.preview_file_object_name = None
            target_file = await KnowledgeFileDao.async_update(target_file)
            self.target_files_by_source_id[int(source_file.id)] = target_file
            return target_file
        except Exception as exc:
            raise TargetCopyError(str(exc), target_file) from exc

    async def copy_tags(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None:
        await _restore_tag_links(
            int(target_file.id),
            int(target.owner.user_id),
            self.tenant_id,
            self.snapshots[int(source_file.id)].tags,
        )

    @staticmethod
    def _target_permission_rows(
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> tuple[dict[str, str], ...]:
        return _target_permission_rows(target_file, target)

    async def write_permissions(self, target_file: KnowledgeFile, target: TargetContext) -> None:
        await _replace_permission_tuples(
            int(target_file.id),
            self._target_permission_rows(target_file, target),
        )

    async def verify_target(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None:
        current = await KnowledgeFileDao.query_by_id(int(target_file.id))
        if current is None or not self._accepts_copied_status(source_file, current):
            raise RuntimeError("target database record is missing or has an incompatible status")
        if int(current.knowledge_id) != int(target.space.id):
            raise RuntimeError("target database record belongs to the wrong knowledge space")
        if int(current.user_id or 0) != int(target.owner.user_id):
            raise RuntimeError("target database record has the wrong owner")
        if (current.file_level_path or "") != target.file_level_path:
            raise RuntimeError("target database record has the wrong folder path")

        snapshot = self.snapshots[int(source_file.id)]
        target_storage = await asyncio.to_thread(_storage_exists, current)
        missing_objects = [
            key for key, existed in snapshot.storage_exists.items() if existed and not target_storage.get(key, False)
        ]
        if missing_objects:
            raise RuntimeError(f"target storage objects are missing: {missing_objects}")

        for delay in (0, 0.25, 0.5, 1.0):
            if delay:
                await asyncio.sleep(delay)
            target_indexes = await asyncio.to_thread(_index_snapshot, target.space, int(current.id))
            if target_indexes == snapshot.indexes:
                break
            logger.warning(
                "Target indexes pending file_id=%s source=%s target=%s", current.id, snapshot.indexes, target_indexes
            )
        if target_indexes.es_count != snapshot.indexes.es_count:
            # 复用有超时上限的显式刷新, 不重发复制或写入请求。
            await asyncio.to_thread(_refresh_es_after_delete, target.space)
            target_indexes = await asyncio.to_thread(_index_snapshot, target.space, int(current.id))
        if target_indexes.milvus_count != snapshot.indexes.milvus_count:
            raise RuntimeError(
                f"Milvus count mismatch: source={snapshot.indexes.milvus_count} target={target_indexes.milvus_count}"
            )
        if target_indexes.es_count != snapshot.indexes.es_count:
            raise RuntimeError(
                f"Elasticsearch count mismatch: source={snapshot.indexes.es_count} target={target_indexes.es_count}"
            )

        target_tags = await _tag_snapshot(int(current.id), self.tenant_id)
        if target_tags != snapshot.tags:
            raise RuntimeError(
                "target file tags do not match the source file: "
                f"source=approved={list(snapshot.tags.approved_ids)}, "
                f"pending={list(snapshot.tags.pending_review_ids)}; "
                f"target=approved={list(target_tags.approved_ids)}, "
                f"pending={list(target_tags.pending_review_ids)}"
            )
        actual_permissions = await _read_permission_tuples(int(current.id))
        expected_permissions = self._target_permission_rows(current, target)
        if not all(row in actual_permissions for row in expected_permissions):
            raise RuntimeError("target owner or parent permission tuple is missing")

    async def _ensure_source_record(self, source_file: KnowledgeFile) -> None:
        if await KnowledgeFileDao.query_by_id(int(source_file.id)) is not None:
            return
        clone = KnowledgeFile(**source_file.model_dump())
        async with get_async_db_session() as session:
            session.add(clone)
            await session.commit()

    async def restore_source(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> list[str]:
        errors: list[str] = []
        file_id = int(source_file.id)
        snapshot = self.snapshots[file_id]
        try:
            await self._ensure_source_record(source_file)
        except Exception as exc:
            errors.append(f"restore source database record: {type(exc).__name__}: {exc}")
        try:
            await asyncio.to_thread(delete_vector_files, [file_id], self._source_space(source_file))
            await asyncio.to_thread(
                _copy_with_es_timeout,
                copy_vector,
                target.space,
                self._source_space(source_file),
                int(target_file.id),
                file_id,
            )
        except Exception as exc:
            errors.append(f"restore source indexes: {type(exc).__name__}: {exc}")

        source_objects = _storage_object_names(source_file)
        target_objects = _storage_object_names(target_file)
        for key, existed in snapshot.storage_exists.items():
            if not existed:
                continue
            try:
                await asyncio.to_thread(_copy_object_if_present, target_objects[key], source_objects[key])
            except Exception as exc:
                errors.append(f"restore source object {key}: {type(exc).__name__}: {exc}")
        try:
            await _restore_tag_links(
                file_id,
                int(source_file.user_id or target.owner.user_id),
                self.tenant_id,
                snapshot.tags,
            )
        except Exception as exc:
            errors.append(f"restore source tags: {type(exc).__name__}: {exc}")
        try:
            await _replace_permission_tuples(file_id, snapshot.permissions)
        except Exception as exc:
            errors.append(f"restore source permissions: {type(exc).__name__}: {exc}")
        return errors

    async def delete_source(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None:
        try:
            await asyncio.to_thread(
                delete_vector_files,
                [int(source_file.id)],
                self._source_space(source_file),
            )
            await asyncio.to_thread(delete_minio_files, source_file)
            await _clear_tag_links(
                int(source_file.id),
                int(source_file.user_id or target.owner.user_id),
                self.tenant_id,
            )
            await _replace_permission_tuples(int(source_file.id), ())
            await asyncio.to_thread(KnowledgeFileDao.delete_batch, [int(source_file.id)])
        except Exception as exc:
            restore_errors = await self.restore_source(source_file, target_file, target)
            detail = f"source deletion failed: {type(exc).__name__}: {exc}"
            if restore_errors:
                detail += f"; source restore errors={restore_errors}"
            raise RuntimeError(detail) from exc

        for space in (self._source_space(source_file), target.space):
            try:
                await KnowledgeDao.async_update_knowledge_update_time_by_id(int(space.id))
            except Exception:
                # Timestamp refresh is non-critical after the source row is deleted.
                logger.exception("Failed to refresh knowledge-space update time: %s", space.id)

    async def cleanup_target(self, target_file: KnowledgeFile, target: TargetContext) -> list[str]:
        if int(target_file.id) in self.failed_copy_target_ids:
            reason = (
                f"target file {target_file.id} preserved: copy failed with uncertain storage outcome; "
                "inspect pending writes and indexes before cleanup"
            )
            logger.error(reason)
            return [reason]
        errors: list[str] = []

        async def attempt(label: str, func: Callable[[], Any]) -> None:
            try:
                value = func()
                if asyncio.iscoroutine(value):
                    await value
            except Exception as exc:
                logger.exception("Target compensation failed: %s", label)
                errors.append(f"{label}: {type(exc).__name__}: {exc}")

        await attempt(
            "target indexes",
            lambda: asyncio.to_thread(delete_vector_files, [int(target_file.id)], target.space),
        )
        await attempt("target objects", lambda: asyncio.to_thread(delete_minio_files, target_file))
        await attempt(
            "target tags",
            lambda: _clear_tag_links(
                int(target_file.id),
                int(target.owner.user_id),
                self.tenant_id,
            ),
        )
        await attempt("target permissions", lambda: _replace_permission_tuples(int(target_file.id), ()))
        await attempt(
            "target database record",
            lambda: asyncio.to_thread(KnowledgeFileDao.delete_batch, [int(target_file.id)]),
        )
        return errors

    @staticmethod
    def _model_fingerprint(model: Any) -> dict[str, Any]:
        payload = _model_payload(model)
        if payload is None:
            raise OverwritePreconditionError("overwrite snapshot model is missing")
        return payload

    async def revalidate_overwrite_target(
        self,
        overwrite: OverwriteTarget,
        target: TargetContext,
    ) -> None:
        expected_file_ids = sorted(int(file.id or 0) for file in overwrite.files)
        if not expected_file_ids or any(file_id <= 0 for file_id in expected_file_ids):
            raise OverwritePreconditionError("overwrite target contains an invalid file ID")
        async with get_async_db_session() as session:
            current_files = list(
                (await session.exec(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(expected_file_ids)))).all()
            )
            current_versions_by_file = list(
                (
                    await session.exec(
                        select(KnowledgeDocumentVersion).where(
                            col(KnowledgeDocumentVersion.knowledge_file_id).in_(expected_file_ids)
                        )
                    )
                ).all()
            )
            current_document: KnowledgeDocument | None = None
            current_versions: list[KnowledgeDocumentVersion] = []
            if overwrite.document is not None:
                document_id = int(overwrite.document.id or 0)
                current_document = (
                    await session.exec(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
                ).first()
                current_versions = list(
                    (
                        await session.exec(
                            select(KnowledgeDocumentVersion)
                            .where(KnowledgeDocumentVersion.document_id == document_id)
                            .order_by(col(KnowledgeDocumentVersion.version_no))
                        )
                    ).all()
                )

        expected_files = {int(file.id or 0): self._model_fingerprint(file) for file in overwrite.files}
        actual_files = {int(file.id or 0): self._model_fingerprint(file) for file in current_files}
        if expected_files != actual_files:
            raise OverwritePreconditionError(
                f"overwrite target files changed after planning: expected={expected_file_ids} "
                f"actual={sorted(actual_files)}"
            )
        if any(int(file.knowledge_id) != int(target.space.id or 0) for file in current_files):
            raise OverwritePreconditionError("overwrite target file moved to another knowledge space")

        if overwrite.document is None:
            if current_versions_by_file:
                raise OverwritePreconditionError("legacy overwrite target joined a version chain after planning")
            return

        if current_document is None:
            raise OverwritePreconditionError("overwrite target document no longer exists")
        if self._model_fingerprint(overwrite.document) != self._model_fingerprint(current_document):
            raise OverwritePreconditionError("overwrite target document changed after planning")
        expected_versions = [self._model_fingerprint(version) for version in overwrite.versions]
        actual_versions = [self._model_fingerprint(version) for version in current_versions]
        if expected_versions != actual_versions:
            raise OverwritePreconditionError("overwrite target version graph changed after planning")
        if len(current_versions_by_file) != len(expected_file_ids):
            raise OverwritePreconditionError("overwrite target files have inconsistent version links")

    async def snapshot_overwrite_target(
        self,
        overwrite: OverwriteTarget,
        target: TargetContext,
    ) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for file in overwrite.files:
            file_id = int(file.id or 0)
            snapshots.append(
                {
                    "record": _model_payload(file),
                    "storage_object_names": list(_overwrite_object_names(file)),
                    "storage_exists": await asyncio.to_thread(_storage_exists, file),
                    "indexes": asdict(await asyncio.to_thread(_index_snapshot, target.space, file_id)),
                    "tags": asdict(await _tag_snapshot(file_id, self.tenant_id)),
                    "permissions": list(await _read_permission_tuples(file_id)),
                }
            )
        return snapshots

    async def delete_overwrite_target(
        self,
        overwrite: OverwriteTarget,
        target: TargetContext,
    ) -> list[OverwriteDeletionStep]:
        steps: list[OverwriteDeletionStep] = []
        file_ids = [int(file.id or 0) for file in overwrite.files]

        async def attempt(
            component: str,
            operation: Callable[[], Any],
            *,
            target_file_id: int | None = None,
            detail: dict[str, Any] | None = None,
        ) -> bool:
            try:
                value = operation()
                if asyncio.iscoroutine(value):
                    value = await value
                step_detail = dict(detail or {})
                if isinstance(value, dict):
                    step_detail.update(value)
                steps.append(
                    OverwriteDeletionStep(
                        component=component,
                        status="success",
                        target_file_id=target_file_id,
                        detail=step_detail,
                    )
                )
                return True
            except Exception as exc:
                logger.exception(
                    "Overwrite target cleanup failed: component=%s target_file_id=%s",
                    component,
                    target_file_id,
                )
                steps.append(
                    OverwriteDeletionStep(
                        component=component,
                        status="failed",
                        target_file_id=target_file_id,
                        detail=dict(detail or {}),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                return False

        def delete_indexes(file_id: int) -> dict[str, Any]:
            delete_vector_files([file_id], target.space)
            remaining = _index_snapshot(target.space, file_id)
            if remaining.es_count:
                # 删除接口未强制刷新，先消除可见性延迟，再判断是否真实残留。
                _refresh_es_after_delete(target.space)
                remaining = replace(remaining, es_count=_count_es_records(target.space, file_id))
            if remaining.milvus_count or remaining.es_count:
                raise RuntimeError(f"index records remain after deletion: {asdict(remaining)}")
            return {"remaining": asdict(remaining)}

        def delete_objects(file: KnowledgeFile) -> dict[str, Any]:
            object_names = _overwrite_object_names(file)
            client = get_minio_storage_sync()
            for object_name in object_names:
                client.remove_object_sync(bucket_name=client.bucket, object_name=object_name)
            remaining = [
                object_name for object_name in object_names if client.object_exists_sync(client.bucket, object_name)
            ]
            if remaining:
                raise RuntimeError(f"MinIO objects remain after deletion: {remaining}")
            return {"object_names": list(object_names), "remaining": remaining}

        async def clear_tags(file: KnowledgeFile) -> dict[str, Any]:
            file_id = int(file.id or 0)
            await _clear_tag_links(
                file_id,
                int(file.user_id or target.owner.user_id),
                self.tenant_id,
            )
            remaining = await _tag_snapshot(file_id, self.tenant_id)
            if remaining.approved_ids or remaining.pending_review_ids:
                raise RuntimeError(f"tag links remain after deletion: {asdict(remaining)}")
            return {"remaining": asdict(remaining)}

        async def clear_permissions(file_id: int) -> dict[str, Any]:
            await _replace_permission_tuples(file_id, ())
            remaining = await _read_permission_tuples(file_id)
            if remaining:
                raise RuntimeError(f"permission tuples remain after deletion: {remaining}")
            return {"remaining": list(remaining)}

        async def delete_associations() -> dict[str, Any]:
            resource_ids = [str(file_id) for file_id in file_ids]
            conditions = [
                col(KnowledgeFileSimilarityCandidate.source_file_id).in_(file_ids),
                col(KnowledgeFileSimilarityCandidate.candidate_file_id).in_(file_ids),
            ]
            if overwrite.document is not None:
                conditions.append(
                    KnowledgeFileSimilarityCandidate.candidate_document_id == int(overwrite.document.id or 0)
                )
            async with get_async_db_session() as session:
                try:
                    await session.exec(delete(KnowledgeFileSimilarityCandidate).where(or_(*conditions)))
                    await session.exec(
                        delete(PortalRecommendationFileProjection).where(
                            col(PortalRecommendationFileProjection.file_id).in_(file_ids)
                        )
                    )
                    await session.exec(
                        delete(ShareLink).where(
                            ShareLink.resource_type == ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
                            col(ShareLink.resource_id).in_(resource_ids),
                        )
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
            return {"file_ids": file_ids}

        async def delete_version_graph() -> dict[str, Any]:
            if overwrite.document is None:
                return {"document_id": None, "version_ids": []}
            document_id = int(overwrite.document.id or 0)
            version_ids = [int(version.id or 0) for version in overwrite.versions]
            async with get_async_db_session() as session:
                try:
                    await session.exec(
                        delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == document_id)
                    )
                    await session.exec(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
            return {"document_id": document_id, "version_ids": version_ids}

        async def delete_file_record(file_id: int) -> dict[str, Any]:
            await KnowledgeFileDao.adelete_batch([file_id])
            if await KnowledgeFileDao.query_by_id(file_id) is not None:
                raise RuntimeError(f"target file record {file_id} remains after deletion")
            return {"file_id": file_id}

        for file in overwrite.files:
            file_id = int(file.id or 0)
            if not await attempt(
                "indexes",
                lambda file_id=file_id: asyncio.to_thread(delete_indexes, file_id),
                target_file_id=file_id,
            ):
                return steps
        # 整条版本链索引均清理成功后才继续；失败后保留尚未清理的旧目标数据。
        for file in overwrite.files:
            file_id = int(file.id or 0)
            if not await attempt(
                "objects",
                lambda file=file: asyncio.to_thread(delete_objects, file),
                target_file_id=file_id,
            ):
                return steps
            if not await attempt("tags", lambda file=file: clear_tags(file), target_file_id=file_id):
                return steps
            if not await attempt(
                "permissions",
                lambda file_id=file_id: clear_permissions(file_id),
                target_file_id=file_id,
            ):
                return steps
        if not await attempt("associations", delete_associations, detail={"file_ids": file_ids}):
            return steps
        if not await attempt("version_graph", delete_version_graph):
            return steps
        for file_id in file_ids:
            if not await attempt(
                "database_record",
                lambda file_id=file_id: delete_file_record(file_id),
                target_file_id=file_id,
            ):
                return steps
        try:
            await KnowledgeDao.async_update_knowledge_update_time_by_id(int(target.space.id or 0))
        except Exception:
            logger.exception("Failed to refresh overwritten target knowledge-space update time")
        return steps


def _model_payload(model: Any | None) -> dict[str, Any] | None:
    if model is None:
        return None
    model_dump = getattr(model, "model_dump", None)
    if not callable(model_dump):
        raise TypeError(f"{type(model).__name__} does not support model_dump")
    return model_dump(mode="json")


def _source_folder_id(file_level_path: str | None) -> int | None:
    parts = [part for part in (file_level_path or "").split("/") if part.isdigit()]
    return int(parts[-1]) if parts else None


def _target_context_payload(target: TargetContext) -> dict[str, Any]:
    return {
        "tenant_id": target.tenant_id,
        "space": _model_payload(target.space),
        "folder": _model_payload(target.folder),
        "owner": {
            "user_id": int(target.owner.user_id),
            "user_name": target.owner.user_name,
            "delete": int(target.owner.delete or 0),
        },
        "file_level_path": target.file_level_path,
        "level": target.level,
    }


def _unit_folder_mappings_payload(operations: Any, unit_id: str) -> list[dict[str, Any]]:
    getter = getattr(operations, "get_unit_folder_mappings", None)
    if not callable(getter):
        return []
    return [asdict(mapping) for mapping in getter(unit_id)]


def build_unit_started_payload(
    unit: MigrationUnit,
    operations: BishengMoveOperations,
) -> dict[str, Any]:
    source_files: list[dict[str, Any]] = []
    for source_file in unit.source_files:
        source_file_id = int(source_file.id or 0)
        snapshot = operations.snapshots.get(source_file_id)
        if snapshot is None:
            raise PreflightError(f"source snapshot is missing before migration: {source_file_id}")
        source_space = operations.source_spaces[int(source_file.knowledge_id)]
        source_files.append(
            {
                "record": _model_payload(source_file),
                "source_space": _model_payload(source_space),
                "source_folder_id": _source_folder_id(source_file.file_level_path),
                "file_level_path": source_file.file_level_path or "",
                "storage_object_names": _storage_object_names(source_file),
                "snapshot": asdict(snapshot),
            }
        )
    return {
        "unit_id": unit.unit_id,
        "unit_type": unit.unit_type,
        "classification": {
            "category_code": unit.category_code,
            "category_label": unit.category_label,
            "subcategory_code": unit.subcategory_code,
            "subcategory_label": unit.subcategory_label,
        },
        "source_files": source_files,
        "source_document": _model_payload(unit.source_document),
        "source_versions": [_model_payload(version) for version in unit.source_versions],
        "source_folder_chain": [asdict(folder) for folder in unit.source_folder_chain],
        "target_base": _target_context_payload(unit.target),
    }


def build_unit_succeeded_payload(
    unit: MigrationUnit,
    results: Sequence[FileMoveResult],
    operations: BishengMoveOperations,
    *,
    target_graph: dict[str, Any] | None,
) -> dict[str, Any]:
    target_files: list[dict[str, Any]] = []
    for source_file in unit.source_files:
        source_file_id = int(source_file.id or 0)
        target_file = operations.target_files_by_source_id.get(source_file_id)
        snapshot = operations.snapshots.get(source_file_id)
        if target_file is None or snapshot is None:
            raise RuntimeError(f"target or source snapshot is missing after migration: {source_file_id}")
        target_files.append(
            {
                "source_file_id": source_file_id,
                "record": _model_payload(target_file),
                "storage_object_names": _storage_object_names(target_file),
                "storage_exists": dict(snapshot.storage_exists),
                "tags": asdict(snapshot.tags),
                "indexes": asdict(snapshot.indexes),
                "permissions": list(_target_permission_rows(target_file, unit.target)),
            }
        )
    return {
        "unit_id": unit.unit_id,
        "unit_type": unit.unit_type,
        "results": [asdict(result) for result in results],
        "target": _target_context_payload(unit.target),
        "folder_mappings": _unit_folder_mappings_payload(operations, unit.unit_id),
        "target_files": target_files,
        "target_graph": target_graph,
    }


class DatabaseVersionGraphStore:
    def __init__(self) -> None:
        self.target_graphs: dict[int, dict[str, Any]] = {}

    async def create_target_graph(
        self,
        unit: MigrationUnit,
        target_files: Sequence[KnowledgeFile],
    ) -> int:
        if unit.source_document is None or len(unit.source_versions) != len(target_files):
            raise RuntimeError("invalid version-chain migration unit")
        target_by_source = {
            int(source.id): target for source, target in zip(unit.source_files, target_files, strict=True)
        }
        async with get_async_db_session() as session:
            try:
                target_document = KnowledgeDocument(
                    knowledge_id=int(unit.target.space.id),
                    file_level_path=unit.target.file_level_path,
                    level=unit.target.level,
                    primary_version_id=None,
                    create_time=unit.source_document.create_time,
                )
                session.add(target_document)
                await session.flush()
                target_versions: list[KnowledgeDocumentVersion] = []
                primary_target_version: KnowledgeDocumentVersion | None = None
                for source_version in unit.source_versions:
                    target_file = target_by_source[int(source_version.knowledge_file_id)]
                    target_version = KnowledgeDocumentVersion(
                        document_id=int(target_document.id),
                        knowledge_file_id=int(target_file.id),
                        version_no=int(source_version.version_no),
                        is_primary=bool(source_version.is_primary),
                        create_time=source_version.create_time,
                    )
                    session.add(target_version)
                    target_versions.append(target_version)
                    if target_version.is_primary:
                        primary_target_version = target_version
                await session.flush()
                if primary_target_version is None or primary_target_version.id is None:
                    raise RuntimeError("source version chain has no primary version")
                target_document.primary_version_id = int(primary_target_version.id)
                session.add(target_document)
                await session.commit()
                await session.refresh(target_document)
                target_document_id = int(target_document.id)
                self.target_graphs[target_document_id] = {
                    "document": _model_payload(target_document),
                    "versions": [_model_payload(version) for version in target_versions],
                }
                return target_document_id
            except Exception:
                await session.rollback()
                raise

    def get_target_graph_payload(self, target_document_id: int) -> dict[str, Any] | None:
        return self.target_graphs.get(target_document_id)

    async def verify_target_graph(
        self,
        unit: MigrationUnit,
        target_document_id: int,
        target_files: Sequence[KnowledgeFile],
    ) -> None:
        target_by_source = {
            int(source.id): int(target.id) for source, target in zip(unit.source_files, target_files, strict=True)
        }
        expected = {
            (
                int(version.version_no),
                bool(version.is_primary),
                target_by_source[int(version.knowledge_file_id)],
            )
            for version in unit.source_versions
        }
        async with get_async_db_session() as session:
            document = (
                await session.exec(select(KnowledgeDocument).where(KnowledgeDocument.id == target_document_id))
            ).first()
            rows = (
                await session.exec(
                    select(KnowledgeDocumentVersion)
                    .where(KnowledgeDocumentVersion.document_id == target_document_id)
                    .order_by(col(KnowledgeDocumentVersion.version_no))
                )
            ).all()
        actual = {(int(row.version_no), bool(row.is_primary), int(row.knowledge_file_id)) for row in rows}
        primary_rows = [row for row in rows if row.is_primary]
        if document is None or actual != expected or len(primary_rows) != 1:
            raise RuntimeError("target version graph does not match the source chain")
        if int(document.primary_version_id or 0) != int(primary_rows[0].id or 0):
            raise RuntimeError("target document primary_version_id is inconsistent")

    async def delete_source_graph(self, unit: MigrationUnit) -> None:
        if unit.source_document is None or unit.source_document.id is None:
            raise RuntimeError("source version document is missing")
        document_id = int(unit.source_document.id)
        async with get_async_db_session() as session:
            try:
                await session.exec(
                    delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == document_id)
                )
                await session.exec(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def restore_source_graph(self, unit: MigrationUnit) -> list[str]:
        if unit.source_document is None or unit.source_document.id is None:
            return ["restore source graph: source document snapshot is missing"]
        document_id = int(unit.source_document.id)
        async with get_async_db_session() as session:
            try:
                existing = (
                    await session.exec(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
                ).first()
                if existing is not None:
                    return []
                session.add(KnowledgeDocument(**unit.source_document.model_dump()))
                session.add_all([KnowledgeDocumentVersion(**version.model_dump()) for version in unit.source_versions])
                await session.commit()
                return []
            except Exception as exc:
                await session.rollback()
                return [f"restore source graph: {type(exc).__name__}: {exc}"]

    async def delete_target_graph(self, target_document_id: int) -> list[str]:
        async with get_async_db_session() as session:
            try:
                await session.exec(
                    delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == target_document_id)
                )
                await session.exec(delete(KnowledgeDocument).where(KnowledgeDocument.id == target_document_id))
                await session.commit()
                return []
            except Exception as exc:
                await session.rollback()
                return [f"delete target graph: {type(exc).__name__}: {exc}"]


def _result_for_source(
    source_file: KnowledgeFile,
    target: TargetContext,
    *,
    status: Literal["ready", "success", "failed"],
    unit: MigrationUnit | None = None,
) -> FileMoveResult:
    version_number = None
    if unit is not None:
        version_number = _version_no_by_file(unit.source_versions).get(int(source_file.id or 0))
    return FileMoveResult(
        source_file_id=int(source_file.id or 0),
        source_space_id=int(source_file.knowledge_id),
        source_file_name=source_file.file_name,
        status=status,
        unit_id=unit.unit_id if unit else f"file:{source_file.id}",
        unit_type=unit.unit_type if unit else "file",
        source_document_id=(
            int(unit.source_document.id) if unit and unit.source_document and unit.source_document.id else None
        ),
        version_no=version_number,
        target_space_id=int(target.space.id),
        target_folder_id=int(target.folder.id) if target.folder else None,
        category_code=unit.category_code
        if unit
        else _normalize_code(parse_shougang_file_encoding_codes(source_file)[0]),
        category_label=unit.category_label if unit else "",
        subcategory_code=unit.subcategory_code if unit else _normalize_code(source_file.file_subcategory_code),
        subcategory_label=unit.subcategory_label if unit else "",
    )


async def move_one_file(
    source_file: KnowledgeFile,
    target: TargetContext,
    operations: MoveOperations,
    *,
    before_source_delete: Callable[[], Awaitable[list[str]]] | None = None,
) -> FileMoveResult:
    result = _result_for_source(source_file, target, status="failed")
    target_file: KnowledgeFile | None = None
    try:
        target_file = await operations.copy_file(source_file, target)
        result.target_file_id = int(target_file.id)
        await operations.copy_tags(source_file, target_file, target)
        await operations.write_permissions(target_file, target)
        await operations.verify_target(source_file, target_file, target)
        overwrite_cleanup_errors = await before_source_delete() if before_source_delete is not None else []
        await operations.delete_source(source_file, target_file, target)
        result.status = "success"
        result.source_deleted = True
        if overwrite_cleanup_errors:
            result.reason_code = "overwrite_cleanup_failed"
            result.overwrite_cleanup_errors = list(overwrite_cleanup_errors)
        return result
    except TargetCopyError as exc:
        target_file = exc.target_file
        result.error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    if target_file is not None:
        result.target_file_id = int(target_file.id)
        result.cleanup_errors = await operations.cleanup_target(target_file, target)
        result.target_cleanup_succeeded = not result.cleanup_errors
    return result


async def move_version_chain(
    unit: MigrationUnit,
    operations: MoveOperations,
    graph_store: VersionGraphStore,
    *,
    before_source_delete: Callable[[], Awaitable[list[str]]] | None = None,
) -> list[FileMoveResult]:
    if unit.unit_type != "version_chain" or unit.source_document is None:
        raise ValueError("move_version_chain requires a version_chain unit")
    target_files: list[KnowledgeFile] = []
    target_document_id: int | None = None
    target_graph_payload: dict[str, Any] | None = None
    source_graph_deleted = False
    cleanup_errors: list[str] = []
    try:
        for source_file in unit.source_files:
            try:
                target_file = await operations.copy_file(source_file, unit.target)
            except TargetCopyError as exc:
                if exc.target_file is not None and exc.target_file.id is not None:
                    target_files.append(exc.target_file)
                raise
            target_files.append(target_file)
            await operations.copy_tags(source_file, target_file, unit.target)
            await operations.write_permissions(target_file, unit.target)
            await operations.verify_target(source_file, target_file, unit.target)
        target_document_id = await graph_store.create_target_graph(unit, target_files)
        await graph_store.verify_target_graph(unit, target_document_id, target_files)
        get_target_graph_payload = getattr(graph_store, "get_target_graph_payload", None)
        if callable(get_target_graph_payload):
            target_graph_payload = get_target_graph_payload(target_document_id)
        overwrite_cleanup_errors = await before_source_delete() if before_source_delete is not None else []
        await graph_store.delete_source_graph(unit)
        source_graph_deleted = True
        for source_file, target_file in zip(unit.source_files, target_files, strict=True):
            await operations.delete_source(source_file, target_file, unit.target)
    except Exception as exc:
        if source_graph_deleted:
            cleanup_errors.extend(await graph_store.restore_source_graph(unit))
            for source_file, target_file in zip(unit.source_files, target_files, strict=False):
                cleanup_errors.extend(await operations.restore_source(source_file, target_file, unit.target))
        if target_document_id is not None:
            cleanup_errors.extend(await graph_store.delete_target_graph(target_document_id))
        for target_file in target_files:
            cleanup_errors.extend(await operations.cleanup_target(target_file, unit.target))
        error = f"{type(exc).__name__}: {exc}"
        results: list[FileMoveResult] = []
        target_by_source = {
            int(source.id): target for source, target in zip(unit.source_files, target_files, strict=False)
        }
        target_version_ids = {
            int(version["knowledge_file_id"]): int(version["id"])
            for version in (target_graph_payload or {}).get("versions", [])
            if version.get("knowledge_file_id") is not None and version.get("id") is not None
        }
        for source_file in unit.source_files:
            result = _result_for_source(source_file, unit.target, status="failed", unit=unit)
            target_file = target_by_source.get(int(source_file.id))
            result.target_file_id = int(target_file.id) if target_file else None
            result.target_document_id = target_document_id
            result.target_version_id = target_version_ids.get(int(target_file.id)) if target_file else None
            result.target_cleanup_succeeded = not cleanup_errors
            result.error = error
            result.cleanup_errors = list(cleanup_errors)
            results.append(result)
        return results

    results = []
    target_version_ids = {
        int(version["knowledge_file_id"]): int(version["id"])
        for version in (target_graph_payload or {}).get("versions", [])
        if version.get("knowledge_file_id") is not None and version.get("id") is not None
    }
    for source_file, target_file in zip(unit.source_files, target_files, strict=True):
        result = _result_for_source(source_file, unit.target, status="success", unit=unit)
        result.target_file_id = int(target_file.id)
        result.target_document_id = target_document_id
        result.target_version_id = target_version_ids.get(int(target_file.id))
        result.source_deleted = True
        if overwrite_cleanup_errors:
            result.reason_code = "overwrite_cleanup_failed"
            result.overwrite_cleanup_errors = list(overwrite_cleanup_errors)
        results.append(result)
    return results


async def compensate_completed_migration(
    completed: CompletedMigration,
    operations: BishengMoveOperations,
    graph_store: VersionGraphStore,
    *,
    reason: str,
) -> list[str]:
    errors: list[str] = []
    target_files: list[KnowledgeFile] = []
    restored_source_ids: set[int] = set()
    for source_file in completed.unit.source_files:
        target_file = operations.target_files_by_source_id.get(int(source_file.id or 0))
        if target_file is None:
            errors.append(f"target file snapshot is missing for source file {source_file.id}")
            continue
        target_files.append(target_file)
        try:
            restore_errors = await operations.restore_source(source_file, target_file, completed.unit.target)
            errors.extend(restore_errors)
            if not restore_errors:
                restored_source_ids.add(int(source_file.id or 0))
        except Exception as exc:
            errors.append(f"restore source file {source_file.id}: {type(exc).__name__}: {exc}")

    can_cleanup_targets = len(restored_source_ids) == len(completed.unit.source_files)
    if completed.unit.unit_type == "version_chain":
        try:
            graph_restore_errors = await graph_store.restore_source_graph(completed.unit)
            errors.extend(graph_restore_errors)
            can_cleanup_targets = can_cleanup_targets and not graph_restore_errors
        except Exception as exc:
            errors.append(f"restore source graph: {type(exc).__name__}: {exc}")
            can_cleanup_targets = False
        target_document_id = next(
            (result.target_document_id for result in completed.results if result.target_document_id is not None),
            None,
        )
        if target_document_id is not None and can_cleanup_targets:
            try:
                graph_cleanup_errors = await graph_store.delete_target_graph(int(target_document_id))
                errors.extend(graph_cleanup_errors)
                can_cleanup_targets = not graph_cleanup_errors
            except Exception as exc:
                errors.append(f"delete target graph: {type(exc).__name__}: {exc}")
                can_cleanup_targets = False

    cleanup_candidates = target_files if can_cleanup_targets else []
    if target_files and not cleanup_candidates:
        errors.append("target data was preserved because source restoration was incomplete")
    for target_file in cleanup_candidates:
        try:
            errors.extend(await operations.cleanup_target(target_file, completed.unit.target))
        except Exception as exc:
            errors.append(f"cleanup target file {target_file.id}: {type(exc).__name__}: {exc}")

    errors.extend(await _cleanup_unit_folder_mappings(operations, completed.unit.unit_id))

    for result in completed.results:
        result.status = "failed"
        result.source_deleted = False
        result.reason_code = "rollback_record_write_failed"
        result.error = reason
        result.cleanup_errors = list(errors)
        result.target_cleanup_succeeded = not errors
    return errors


async def _cleanup_unit_folder_mappings(operations: Any, unit_id: str) -> list[str]:
    cleanup = getattr(operations, "cleanup_unit_folders", None)
    if not callable(cleanup):
        return []
    try:
        return list(await cleanup(unit_id))
    except Exception as exc:
        return [f"cleanup target folders for {unit_id}: {type(exc).__name__}: {exc}"]


@dataclass
class Snapshot:
    tenant_id: int
    spaces: list[Knowledge] = field(default_factory=list)
    scopes: list[KnowledgeSpaceScope] = field(default_factory=list)
    files: list[KnowledgeFile] = field(default_factory=list)
    users: list[User] = field(default_factory=list)
    member_ids: set[int] = field(default_factory=set)
    documents: list[KnowledgeDocument] = field(default_factory=list)
    versions: list[KnowledgeDocumentVersion] = field(default_factory=list)
    locked_document_ids: set[int] = field(default_factory=set)
    locked_file_ids: set[int] = field(default_factory=set)
    referenced_file_ids: set[int] = field(default_factory=set)
    referenced_document_ids: set[int] = field(default_factory=set)
    approvals: list[Any] = field(default_factory=list)


class PlanningIndex:
    def __init__(self, snapshot: Snapshot) -> None:
        self.files = {f.id: f for f in snapshot.files if f.tenant_id == snapshot.tenant_id}
        self.documents = {d.id: d for d in snapshot.documents if d.tenant_id == snapshot.tenant_id}
        self.by_file: dict[int, list] = defaultdict(list)
        self.by_doc: dict[int, list] = defaultdict(list)
        self.by_space: dict[int, list] = defaultdict(list)
        self.by_name: dict[tuple, list] = defaultdict(list)
        self.referenced_docs = set(snapshot.referenced_document_ids)
        self.referenced_files = set(snapshot.referenced_file_ids)
        for version in snapshot.versions:
            self.by_file[version.knowledge_file_id].append(version)
            self.by_doc[version.document_id].append(version)
        for record in self.files.values():
            self.by_space[record.knowledge_id].append(record)
            self.by_name[(record.knowledge_id, record.file_level_path or "", record.file_name)].append(record)
            if record.reference_document_id:
                self.referenced_docs.add(record.reference_document_id)
            self.referenced_files.update(
                fid for fid in (record.share_source_file_id, record.predecessor_logic_file_id) if fid
            )
        self.referenced_files.update(
            d.predecessor_logic_file_id for d in self.documents.values() if d.predecessor_logic_file_id
        )


@dataclass
class Candidate:
    unit_id: str
    files: tuple[KnowledgeFile, ...]
    owner: User
    folders: tuple[KnowledgeFile, ...]
    source_space: Knowledge
    target_space: Knowledge | None = None
    document: KnowledgeDocument | None = None
    versions: tuple[KnowledgeDocumentVersion, ...] = ()
    missing_folders: tuple[str, ...] = ()
    personal_space_candidate_ids: tuple[int, ...] = ()
    overwrites: tuple[OverwriteTarget, ...] = ()
    replaces_planned_unit_ids: tuple[str, ...] = ()
    preparation_issues: list[str] = field(default_factory=list)

    @property
    def folder_names(self) -> tuple[str, ...]:
        return tuple(f.file_name for f in self.folders)

    def preview(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "source_space_id": self.source_space.id,
            "source_file_ids": [f.id for f in self.files],
            "user_id": self.owner.user_id,
            "target_space_id": self.target_space.id if self.target_space else None,
            "personal_space_candidate_ids": list(self.personal_space_candidate_ids),
            "overwrite_targets": [
                {
                    "logical_id": o.logical_id,
                    "file_ids": [f.id for f in o.files],
                    "document_id": o.document.id if o.document else None,
                    "version_ids": [v.id for v in o.versions],
                }
                for o in self.overwrites
            ],
            "replaces_planned_unit_ids": list(self.replaces_planned_unit_ids),
            "target_space_name": f"{self.owner.user_name}的知识库",
            "target_folder": "/".join(self.folder_names),
            "file_names": [f.file_name for f in self.files],
            "create_personal_space": self.target_space is None,
            "create_folders": list(self.missing_folders),
            "pending_checks": ["created_space_model_and_permissions"] if self.target_space is None else [],
        }

    def fingerprint(self) -> str:
        # 比较全部源记录，避免预览后上传人、版本、路径或状态变化仍按旧快照执行。
        return json.dumps(
            {
                "files": [f.model_dump() for f in self.files],
                "folders": [f.model_dump() for f in self.folders],
                "document": self.document.model_dump() if self.document else None,
                "versions": [v.model_dump() for v in self.versions],
                "owner": (self.owner.user_id, self.owner.user_name, self.owner.delete),
                "source": (
                    self.source_space.id,
                    self.source_space.model,
                    self.source_space.collection_name,
                    self.source_space.index_name,
                ),
            },
            sort_keys=True,
            default=str,
        )


def path_ids(path: str | None) -> tuple[int, ...]:
    if not path:
        return ()
    if not path.startswith("/") or any(not p.isdecimal() or int(p) <= 0 for p in path[1:].split("/")):
        raise PreflightError("invalid_source_path")
    ids = tuple(int(p) for p in path[1:].split("/"))
    if len(ids) != len(set(ids)):
        raise PreflightError("invalid_source_path")
    return ids


def resolve_overwrites(
    candidate: Candidate, snapshot: Snapshot, path: str, index: PlanningIndex | None = None
) -> tuple[OverwriteTarget, ...]:
    index = index or PlanningIndex(snapshot)
    target = candidate.target_space
    target_names = {f.file_name for f in candidate.files}
    matches = [f for name in target_names for f in index.by_name.get((target.id, path, name), [])]
    by_file, by_doc = index.by_file, index.by_doc
    all_files, documents = index.files, index.documents
    protected_docs, protected_files = index.referenced_docs, index.referenced_files
    result = {}
    for match in sorted(matches, key=lambda f: f.id):
        links = by_file.get(match.id, [])
        if len(links) > 1:
            raise PreflightError("overwrite_invalid_version_chain")
        doc = None
        versions = ()
        members = (match,)
        logical_id = f"file:{match.id}"
        if links:
            doc = documents.get(links[0].document_id)
            versions = tuple(sorted(by_doc[links[0].document_id], key=lambda v: (v.version_no, v.id)))
            members = tuple(all_files.get(v.knowledge_file_id) for v in versions)
            if (
                doc is None
                or any(f is None for f in members)
                or not TargetConflictIndex._valid_version_graph(doc, versions)
                or any(len(by_file[f.id]) != 1 for f in members)
                or doc.knowledge_id != target.id
                or doc.tenant_id != snapshot.tenant_id
                or (doc.file_level_path or "") != path
            ):
                raise PreflightError("overwrite_invalid_version_chain")
            if (
                doc.id in protected_docs
                or doc.id in snapshot.locked_document_ids
                or doc.predecessor_logic_file_id
                or doc.lifecycle_status != "active"
            ):
                raise PreflightError("overwrite_protected_document")
            logical_id = f"document:{doc.id}"
        if any(
            f.file_type != 1
            or f.status not in {2, 3, 6}
            or f.knowledge_id != target.id
            or f.tenant_id != snapshot.tenant_id
            or (f.file_level_path or "") != path
            for f in members
        ):
            raise PreflightError("overwrite_ineligible_target")
        if any(
            f.reference_document_id
            or f.entry_type in {"publish", "share", "projection_tombstone"}
            or f.entry_status not in {None, "active"}
            or f.predecessor_logic_file_id
            or f.share_source_file_id
            or f.id in protected_files
            or f.id in snapshot.locked_file_ids
            for f in members
        ):
            raise PreflightError("overwrite_protected_document")
        result[logical_id] = OverwriteTarget(
            logical_id=logical_id,
            files=members,
            document=doc,
            versions=versions,
            matched_file_ids=tuple(f.id for f in members if f.file_name in target_names),
            match_reasons=("name",),
        )
    return tuple(result.values())


def overwrite_fingerprint(overwrites: tuple[OverwriteTarget, ...]) -> str:
    return json.dumps(
        [
            {
                "files": [f.model_dump() for f in o.files],
                "document": o.document.model_dump() if o.document else None,
                "versions": [v.model_dump() for v in o.versions],
            }
            for o in overwrites
        ],
        sort_keys=True,
        default=str,
    )


def check_target(
    candidate: Candidate, files: list[KnowledgeFile], snapshot: Snapshot, index: PlanningIndex | None = None
) -> None:
    index = index or PlanningIndex(snapshot)
    candidate.overwrites = ()
    if candidate.target_space is None:
        candidate.missing_folders = tuple(
            "/".join(candidate.folder_names[: i + 1]) for i in range(len(candidate.folders))
        )
        return
    target = candidate.target_space
    if (
        target.user_id != candidate.owner.user_id
        or target.is_favorite
        or target.tenant_id != candidate.source_space.tenant_id
    ):
        raise PreflightError("invalid_personal_space")
    path: str | None = ""
    missing = []
    for i, name in enumerate(candidate.folder_names):
        matches = index.by_name.get((target.id, path, name), []) if path is not None else []
        if len(matches) > 1 or any(f.file_type != 0 or f.status != 2 or f.level != i for f in matches):
            raise PreflightError("target_folder_conflict")
        if matches:
            path = f"{path}/{matches[0].id}"
        else:
            missing.append("/".join(candidate.folder_names[: i + 1]))
            path = None
    if path is not None:
        candidate.overwrites = resolve_overwrites(candidate, snapshot, path, index)
    candidate.missing_folders = tuple(missing)


def resolve_tenant(args: argparse.Namespace, enabled: bool) -> int:
    if enabled and args.tenant_id is None:
        raise PreflightError("多租户开启时必须指定 --tenant-id")
    if not enabled and args.tenant_id not in {None, 1}:
        raise PreflightError("单租户模式只允许默认租户 1")
    return args.tenant_id or 1


async def rows_by_ids(session: Any, model: Any, column: Any, values: Any) -> list:
    ids = sorted(set(values))
    result = []
    for offset in range(0, len(ids), 400):
        result.extend((await session.exec(select(model).where(col(column).in_(ids[offset : offset + 400])))).all())
    return result


async def versions_for_ids(session: Any, document_ids: Any, file_ids: Any) -> list:
    documents, files = sorted(set(document_ids)), sorted(set(file_ids))
    result = []
    for offset in range(0, max(len(documents), len(files)), 400):
        statement = select(KnowledgeDocumentVersion).where(
            or_(
                col(KnowledgeDocumentVersion.document_id).in_(documents[offset : offset + 400]),
                col(KnowledgeDocumentVersion.knowledge_file_id).in_(files[offset : offset + 400]),
            )
        )
        result.extend((await session.exec(statement)).all())
    return result


async def load_reference_guards(session: Any, snapshot: Snapshot) -> None:
    files = sorted({f.id for f in snapshot.files})
    docs = sorted({d.id for d in snapshot.documents})
    for offset in range(0, max(len(files), len(docs)), 400):
        file_batch, doc_batch = files[offset : offset + 400], docs[offset : offset + 400]
        rows = (
            await session.exec(
                select(
                    KnowledgeFile.reference_document_id,
                    KnowledgeFile.share_source_file_id,
                    KnowledgeFile.predecessor_logic_file_id,
                ).where(
                    or_(
                        col(KnowledgeFile.reference_document_id).in_(doc_batch),
                        col(KnowledgeFile.share_source_file_id).in_(file_batch),
                        col(KnowledgeFile.predecessor_logic_file_id).in_(file_batch),
                    )
                )
            )
        ).all()
        for document_id, share_id, predecessor_id in rows:
            if document_id:
                snapshot.referenced_document_ids.add(document_id)
            snapshot.referenced_file_ids.update(fid for fid in (share_id, predecessor_id) if fid)
        snapshot.referenced_file_ids.update(
            (
                await session.exec(
                    select(KnowledgeDocument.predecessor_logic_file_id).where(
                        col(KnowledgeDocument.predecessor_logic_file_id).in_(file_batch)
                    )
                )
            ).all()
        )


class MigrationBackend:
    def plan_for_snapshot(self, snapshot: Snapshot, folder_name: str, unit_id: str | None = None) -> Plan:
        return build_plan(snapshot, only_unit_id=unit_id)

    async def load(
        self,
        tenant_id: int,
        *,
        user_id: int | None = None,
        candidate: Candidate | None = None,
        metadata_only: bool = False,
    ) -> Snapshot:
        async with get_async_db_session() as session:
            if settings.multi_tenant.enabled:
                tenant = await session.get(Tenant, tenant_id)
                if tenant is None or tenant.status != "active":
                    raise PreflightError("tenant_unavailable")
            statement = (
                select(Knowledge)
                .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
                .where(
                    Knowledge.type == 3,
                    or_(col(Knowledge.is_favorite).is_(False), col(Knowledge.is_favorite).is_(None)),
                    KnowledgeSpaceScope.level == "personal",
                    KnowledgeSpaceScope.owner_type == "user",
                )
            )
            if user_id is not None:
                statement = statement.where(KnowledgeSpaceScope.owner_id == user_id)
            spaces = list({s.id: s for s in (await session.exec(statement)).all()}.values())
            space_ids = [s.id for s in spaces]
            snapshot = Snapshot(tenant_id, spaces=spaces)
            snapshot.scopes = await rows_by_ids(session, KnowledgeSpaceScope, KnowledgeSpaceScope.space_id, space_ids)
            owner_ids = {s.owner_id for s in snapshot.scopes if s.owner_type == "user"}
            snapshot.users = await rows_by_ids(session, User, User.user_id, owner_ids)
            if settings.multi_tenant.enabled:
                memberships = await rows_by_ids(session, UserTenant, UserTenant.user_id, owner_ids)
                snapshot.member_ids = {
                    row.user_id
                    for row in memberships
                    if row.tenant_id == tenant_id and row.status == "active" and row.is_active == 1
                }
            else:
                snapshot.member_ids = {u.user_id for u in snapshot.users}
            if metadata_only or not space_ids:
                return snapshot
            groups, _ = find_groups(snapshot, user_id)
            space_ids = sorted({s.id for group in groups for s in (group.target, *group.sources)})
            if not space_ids:
                return snapshot

            if candidate is None:
                snapshot.files = await rows_by_ids(session, KnowledgeFile, KnowledgeFile.knowledge_id, space_ids)
                snapshot.documents = await rows_by_ids(
                    session, KnowledgeDocument, KnowledgeDocument.knowledge_id, space_ids
                )
            else:
                ids = {f.id for f in (*candidate.files, *candidate.folders)}
                snapshot.files = await rows_by_ids(session, KnowledgeFile, KnowledgeFile.id, ids)
                target_rows = []
                if candidate.folder_names:
                    target_rows = list(
                        (
                            await session.exec(
                                select(KnowledgeFile).where(
                                    KnowledgeFile.knowledge_id == candidate.target_space.id,
                                    col(KnowledgeFile.file_name).in_(candidate.folder_names),
                                )
                            )
                        ).all()
                    )
                path = ""
                for name in candidate.folder_names:
                    matches = [f for f in target_rows if f.file_name == name and (f.file_level_path or "") == path]
                    if len(matches) != 1 or matches[0].file_type != 0:
                        path = None
                        break
                    path = f"{path}/{matches[0].id}"
                if path is not None and candidate.files:
                    path_filter = KnowledgeFile.file_level_path == path
                    if not path:
                        path_filter = or_(path_filter, col(KnowledgeFile.file_level_path).is_(None))
                    target_rows.extend(
                        (
                            await session.exec(
                                select(KnowledgeFile).where(
                                    KnowledgeFile.knowledge_id == candidate.target_space.id,
                                    path_filter,
                                    col(KnowledgeFile.file_name).in_({f.file_name for f in candidate.files}),
                                )
                            )
                        ).all()
                    )
                snapshot.files = list({f.id: f for f in [*snapshot.files, *target_rows]}.values())
                if candidate.document is not None:
                    snapshot.documents = await rows_by_ids(
                        session, KnowledgeDocument, KnowledgeDocument.id, [candidate.document.id]
                    )

            files = {f.id: f for f in snapshot.files}
            documents = {d.id: d for d in snapshot.documents}
            versions = await versions_for_ids(session, documents, files)
            linked_doc_ids = {v.document_id for v in versions} - documents.keys()
            documents.update(
                (d.id, d) for d in await rows_by_ids(session, KnowledgeDocument, KnowledgeDocument.id, linked_doc_ids)
            )
            versions.extend(await versions_for_ids(session, {v.document_id for v in versions}, []))
            member_ids = {v.knowledge_file_id for v in versions} - files.keys()
            files.update((f.id, f) for f in await rows_by_ids(session, KnowledgeFile, KnowledgeFile.id, member_ids))
            # 补查整链成员的所有链接, 多文档关联仍按损坏版本图拒绝。
            versions.extend(await versions_for_ids(session, [], member_ids))
            snapshot.files = list(files.values())
            snapshot.documents = list(documents.values())
            snapshot.versions = list({v.id: v for v in versions}.values())
            await load_reference_guards(session, snapshot)

            snapshot.approvals = list(
                (
                    await session.exec(
                        select(ApprovalInstance).where(
                            col(ApprovalInstance.status).in_(["pending", "exception", "execute_failed"])
                        )
                    )
                ).all()
            )
            for approval in snapshot.approvals:
                if approval.tenant_id != tenant_id:
                    continue
                first = str(approval.business_resource_id or "").split(":", 1)[0]
                if not first.isdecimal():
                    continue
                if approval.scenario_code == "knowledge_space_file_publish_request":
                    snapshot.locked_document_ids.add(int(first))
                if approval.business_resource_type in {"knowledge_file", "file"} or "file" in approval.scenario_code:
                    snapshot.locked_file_ids.add(int(first))
                    snapshot.locked_document_ids.add(int(first))
            if candidate is None:
                # 整库清理仍需查其他用户/其他类型库是否共用集合, 只读匹配项。
                collections = {s.collection_name for s in spaces if s.collection_name}
                indexes = {s.index_name for s in spaces if s.index_name}
                if collections or indexes:
                    shared = (
                        await session.exec(
                            select(Knowledge).where(
                                or_(
                                    col(Knowledge.collection_name).in_(collections),
                                    col(Knowledge.index_name).in_(indexes),
                                )
                            )
                        )
                    ).all()
                    snapshot.spaces = list({s.id: s for s in [*spaces, *shared]}.values())
            return snapshot

    async def read_files(self, file_ids: list[int]) -> dict[int, KnowledgeFile]:
        async with get_async_db_session() as session:
            return {f.id: f for f in await rows_by_ids(session, KnowledgeFile, KnowledgeFile.id, file_ids)}

    async def source_has_rows(self, space_id: int) -> bool:
        async with get_async_db_session() as session:
            for model, column in (
                (Knowledge, Knowledge.id),
                (KnowledgeSpaceScope, KnowledgeSpaceScope.space_id),
                (KnowledgeFile, KnowledgeFile.knowledge_id),
                (KnowledgeDocument, KnowledgeDocument.knowledge_id),
            ):
                if (await session.exec(select(model).where(column == space_id).limit(1))).first() is not None:
                    return True
        return False

    async def initialize_apply(self) -> None:
        await initialize_app_context(config=settings)

    async def service_for(self, candidate: Candidate) -> Any:
        from bisheng.common.dependencies.user_deps import UserPayload
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        owner = await asyncio.to_thread(
            UserPayload,
            user_id=candidate.owner.user_id,
            user_name=candidate.owner.user_name,
            tenant_id=candidate.source_space.tenant_id,
        )
        return KnowledgeSpaceService(request=None, login_user=owner)

    async def ensure_space(self, candidate: Candidate, journal: RollbackJournal) -> tuple[Any, Knowledge]:
        service = await self.service_for(candidate)
        target = candidate.target_space
        if target is None:
            raise PreflightError("missing_merge_target")
        candidate.target_space = target
        latest = await self.load(candidate.source_space.tenant_id, user_id=candidate.owner.user_id, candidate=candidate)
        target_scopes = [s for s in latest.scopes if s.space_id == target.id]
        if (
            target.id is None
            or target.type != KnowledgeTypeEnum.SPACE.value
            or len(target_scopes) != 1
            or target_scopes[0].level != "personal"
            or target_scopes[0].owner_type != "user"
            or target_scopes[0].owner_id != candidate.owner.user_id
            or target_scopes[0].tenant_id != candidate.source_space.tenant_id
        ):
            raise PreflightError("invalid_personal_space")
        check_target(candidate, latest.files, latest)
        required = {
            "user": f"user:{candidate.owner.user_id}",
            "relation": "owner",
            "object": f"knowledge_space:{target.id}",
        }
        await self.verify_space_owner(candidate, required)
        return service, target

    async def verify_space_owner(self, candidate: Candidate, required: dict[str, str]) -> None:
        if required not in await _read_resource_permission_tuples(required["object"]):
            raise RuntimeError("个人知识库 owner 权限未生效")

    async def prepare_folders(
        self,
        candidate: Candidate,
        service: Any,
        journal: RollbackJournal,
        created: list[KnowledgeFile],
        mappings: list[dict[str, Any]],
    ) -> TargetContext:
        target = candidate.target_space
        parent: KnowledgeFile | None = None
        path = ""
        for source_folder in candidate.folders:
            async with get_async_db_session() as session:
                records = (
                    await session.exec(
                        select(KnowledgeFile).where(
                            KnowledgeFile.knowledge_id == target.id,
                            KnowledgeFile.file_name == source_folder.file_name,
                        )
                    )
                ).all()
            matches = [f for f in records if (f.file_level_path or "") == path]
            if len(matches) > 1 or any(f.file_type != 0 or f.status != 2 for f in matches):
                raise PreflightError("target_folder_conflict")
            if matches:
                folder = matches[0]
                action = "reused"
            else:
                record_event(
                    journal,
                    "folder_create_started",
                    {
                        "unit_id": candidate.unit_id,
                        "space_id": target.id,
                        "parent_path": path,
                        "name": source_folder.file_name,
                    },
                )
                folder = await service.add_folder(target.id, source_folder.file_name, parent.id if parent else None)
                created.append(folder)
                action = "created"
            if (
                folder.id is None
                or folder.knowledge_id != target.id
                or folder.tenant_id != target.tenant_id
                or (folder.file_level_path or "") != path
                or folder.level != len(mappings)
            ):
                raise RuntimeError("目标目录归属或层级不一致")
            mapping = {
                "source_folder_id": source_folder.id,
                "target_folder_id": folder.id,
                "name": folder.file_name,
                "parent_path": path,
                "action": action,
            }
            mappings.append(mapping)
            record_event(journal, "folder_prepared", {"unit_id": candidate.unit_id, **mapping})
            parent = folder
            path = f"{path}/{folder.id}"
        return TargetContext(
            candidate.source_space.tenant_id, target, parent, candidate.owner, path, len(candidate.folders)
        )

    async def verify_completed(
        self, unit: MigrationUnit, operations: GuardedOperations, results: list[FileMoveResult]
    ) -> None:
        async with get_async_db_session() as session:
            for source in unit.source_files:
                if await session.get(KnowledgeFile, source.id) is not None:
                    raise RuntimeError(f"来源文件记录仍存在: {source.id}")
            if unit.source_document and await session.get(KnowledgeDocument, unit.source_document.id) is not None:
                raise RuntimeError("来源版本文档仍存在")
            if unit.source_document:
                remaining = (
                    await session.exec(
                        select(KnowledgeDocumentVersion).where(
                            KnowledgeDocumentVersion.document_id == unit.source_document.id
                        )
                    )
                ).first()
                if remaining is not None:
                    raise RuntimeError("来源版本记录仍存在")
        for source in unit.source_files:
            target = operations.target_files_by_source_id[source.id]
            await operations.verify_target(source, target, unit.target)
            if any((await asyncio.to_thread(_storage_exists, source)).values()):
                raise RuntimeError(f"来源对象仍存在: {source.id}")
            await _verify_source_indexes_deleted(operations.source_spaces[source.knowledge_id], source.id)
            tags = await _tag_snapshot(source.id, unit.target.tenant_id)
            if tags.approved_ids or tags.pending_review_ids:
                raise RuntimeError(f"来源标签关系仍存在: {source.id}")

    async def execute(self, candidate: Candidate, journal: RollbackJournal, folder_name: str) -> dict[str, Any]:
        operations = GuardedOperations(
            candidate.source_space.tenant_id, {candidate.source_space.id: candidate.source_space}
        )
        graphs = GuardedGraphStore(operations)
        created: list[KnowledgeFile] = []
        mappings: list[dict[str, Any]] = []
        results: list[FileMoveResult] = []
        unit: MigrationUnit | None = None
        completed = False
        overwrite_steps: list[dict[str, Any]] = []
        audit_failed = False

        def write_event(kind: str, payload: dict[str, Any]) -> None:
            nonlocal audit_failed
            try:
                record_event(journal, kind, payload)
            except Exception:
                audit_failed = True
                raise

        try:
            service, _ = await self.ensure_space(candidate, journal)
            target = await self.prepare_folders(candidate, service, journal, created, mappings)
            unit = MigrationUnit(
                candidate.unit_id,
                "version_chain" if candidate.document else "file",
                candidate.files,
                target,
                "",
                "",
                "",
                "",
                source_document=candidate.document,
                source_versions=candidate.versions,
            )
            await operations.snapshot_unit(unit)
            write_event(
                "unit_started",
                {**build_unit_started_payload(unit, operations), "folder_mappings": mappings},
            )

            async def before_delete() -> list[str]:
                # 验证复制结果已由底座执行；持久保存目标 ID 后才允许删除来源。
                latest = await self.load(
                    candidate.source_space.tenant_id, user_id=candidate.owner.user_id, candidate=candidate
                )
                own_target_ids = {f.id for f in operations.target_files_by_source_id.values()}
                latest.files = [f for f in latest.files if f.id not in own_target_ids]
                current = next(
                    (
                        c
                        for c in self.plan_for_snapshot(latest, folder_name, candidate.unit_id).candidates
                        if c.unit_id == candidate.unit_id
                    ),
                    None,
                )
                if (
                    current is None
                    or current.fingerprint() != candidate.fingerprint()
                    or current.target_space is None
                    or current.target_space.id != target.space.id
                    or overwrite_fingerprint(current.overwrites) != overwrite_fingerprint(candidate.overwrites)
                ):
                    raise PreflightError("source_or_target_changed_before_delete")
                write_event(
                    "before_source_delete",
                    {
                        "unit_id": candidate.unit_id,
                        "target_files": [_model_payload(f) for f in operations.target_files_by_source_id.values()],
                        "target_graphs": graphs.target_graphs,
                        "folder_mappings": mappings,
                        "overwrite_targets": candidate.preview()["overwrite_targets"],
                    },
                )
                overwrite_steps.extend(await self.replace_existing(candidate, target, operations, journal))
                return []

            if candidate.document:
                results = await move_version_chain(unit, operations, graphs, before_source_delete=before_delete)
            else:
                results = [
                    await move_one_file(candidate.files[0], target, operations, before_source_delete=before_delete)
                ]
            if any(r.status == "failed" for r in results):
                raise RuntimeError("; ".join(r.error or r.reason_code for r in results if r.status == "failed"))
            completed = True
            await self.verify_completed(unit, operations, results)
            payload = build_unit_succeeded_payload(
                unit, results, operations, target_graph=next(iter(graphs.target_graphs.values()), None)
            )
            payload["folder_mappings"] = mappings
            payload["overwrite_steps"] = overwrite_steps
            write_event("unit_succeeded", payload)
            return {
                "unit_id": candidate.unit_id,
                "status": "success",
                "results": [asdict(r) for r in results],
                "folder_mappings": mappings,
                "overwrite_targets": candidate.preview()["overwrite_targets"],
                "overwrite_steps": overwrite_steps,
                "replaces_planned_unit_ids": list(candidate.replaces_planned_unit_ids),
            }
        except Exception as exc:
            errors: list[str] = []
            if completed and unit is not None and not operations.irreversible_overwrite_started:
                errors.extend(
                    await compensate_completed_migration(
                        CompletedMigration(unit, results), operations, graphs, reason=str(exc)
                    )
                )
            errors.extend(await cleanup_created_folders(created))
            for result in results:
                errors.extend(result.cleanup_errors)
            outcome = {
                "unit_id": candidate.unit_id,
                "status": "skipped"
                if isinstance(exc, PreflightError)
                and not results
                and not errors
                and (
                    isinstance(exc, SourceIndexMismatch)
                    or str(exc)
                    in {
                        "invalid_personal_space",
                        "embedding_model_mismatch",
                        "target_folder_conflict",
                        "target_name_conflict",
                    }
                )
                else "failed",
                "reason": str(exc),
                "results": [asdict(r) for r in results],
                "cleanup_errors": errors,
                "folder_mappings": mappings,
                "target_space_id": candidate.target_space.id if candidate.target_space else None,
                "irreversible_overwrite_started": operations.irreversible_overwrite_started,
                "overwrite_steps": operations.overwrite_steps,
                "overwrite_targets": candidate.preview()["overwrite_targets"],
            }
            outcome["recoverable"] = (
                bool(results)
                and not errors
                and not audit_failed
                and not getattr(journal, "failed", False)
                and not operations.irreversible_overwrite_started
                and all(not result.source_deleted for result in results)
            )
            if outcome["status"] == "skipped" or outcome["recoverable"]:
                logger.warning("迁移单元保留来源: %s; %s", candidate.unit_id, exc)
            else:
                logger.exception("迁移单元未完成: %s", candidate.unit_id)
            # 主报告也保存返回值；日志损坏时禁止尝试下一个单元。
            try:
                write_event("unit_skipped" if outcome["status"] == "skipped" else "unit_failed", outcome)
            except Exception as journal_error:
                outcome["status"] = "failed"
                outcome["journal_error"] = str(journal_error)
                outcome["recoverable"] = False
            return outcome

    async def replace_existing(
        self,
        candidate: Candidate,
        target: TargetContext,
        operations: GuardedOperations,
        journal: RollbackJournal,
    ) -> list[dict[str, Any]]:
        if not candidate.overwrites:
            return []
        snapshots = []
        for overwrite in candidate.overwrites:
            await operations.revalidate_overwrite_target(overwrite, target)
            snapshots.append(
                {
                    "logical_id": overwrite.logical_id,
                    "files": await operations.snapshot_overwrite_target(overwrite, target),
                    "document": _model_payload(overwrite.document),
                    "versions": [_model_payload(v) for v in overwrite.versions],
                }
            )
        record_event(
            journal,
            "overwrite_started",
            {"unit_id": candidate.unit_id, "targets": snapshots, "warning": "旧目标内容永久删除，普通来源补偿无法恢复"},
        )
        # 一旦开始删除旧内容，新副本必须保留，即使后来删除来源或写日志失败。
        operations.irreversible_overwrite_started = True
        operations.preserve_targets = True
        for overwrite in candidate.overwrites:
            steps = await operations.delete_overwrite_target(overwrite, target)
            item = {"logical_id": overwrite.logical_id, "steps": [asdict(step) for step in steps]}
            operations.overwrite_steps.append(item)
            record_event(journal, "overwrite_finished", {"unit_id": candidate.unit_id, **item})
            if any(step.status != "success" for step in steps):
                raise RuntimeError(f"覆盖旧目标失败，已停止并保留新副本: {overwrite.logical_id}")
        return list(operations.overwrite_steps)


class GuardedOperations(BishengMoveOperations):
    """来源恢复不完整时，禁止底座清理目标唯一副本。"""

    preserve_targets = False

    def __init__(self, tenant_id: int, source_spaces: dict[int, Knowledge]) -> None:
        super().__init__(tenant_id, source_spaces)
        self.irreversible_overwrite_started = False
        self.overwrite_steps: list[dict[str, Any]] = []

    async def restore_source(
        self, source_file: KnowledgeFile, target_file: KnowledgeFile, target: TargetContext
    ) -> list[str]:
        try:
            errors = await super().restore_source(source_file, target_file, target)
        except Exception as exc:
            self.preserve_targets = True
            logger.exception("来源恢复失败，保留目标副本")
            return [f"恢复来源 {source_file.id} 失败: {exc}"]
        self.preserve_targets = self.preserve_targets or bool(errors)
        return errors

    async def cleanup_target(self, target_file: KnowledgeFile, target: TargetContext) -> list[str]:
        if self.preserve_targets:
            return [f"来源未完全恢复或旧目标覆盖已开始，保留目标文件 {target_file.id}"]
        return await super().cleanup_target(target_file, target)


class GuardedGraphStore(DatabaseVersionGraphStore):
    def __init__(self, operations: GuardedOperations) -> None:
        super().__init__()
        self.operations = operations

    async def restore_source_graph(self, unit: MigrationUnit) -> list[str]:
        try:
            errors = await super().restore_source_graph(unit)
        except Exception as exc:
            self.operations.preserve_targets = True
            logger.exception("来源版本链恢复失败，保留目标版本链")
            return [f"恢复来源版本链 {unit.unit_id} 失败: {exc}"]
        self.operations.preserve_targets = self.operations.preserve_targets or bool(errors)
        return errors

    async def delete_target_graph(self, target_document_id: int) -> list[str]:
        if self.operations.preserve_targets:
            return [f"来源未完全恢复或旧目标覆盖已开始，保留目标版本链 {target_document_id}"]
        return await super().delete_target_graph(target_document_id)


async def cleanup_created_folders(created: list[KnowledgeFile]) -> list[str]:
    errors = []
    store = DatabaseTargetFolderStore()
    preserve_ancestors = False
    for folder in reversed(created):
        if preserve_ancestors:
            errors.append(f"后代目录仍存在，保留目录 {folder.id}")
            continue
        try:
            if await store.is_folder_empty(folder):
                await store.delete_folder(folder)
            else:
                preserve_ancestors = True
                errors.append(f"保留非空目录 {folder.id}")
        except Exception as exc:
            preserve_ancestors = True
            logger.exception("清理新目录失败: %s", folder.id)
            errors.append(f"目录 {folder.id}: {exc}")
    return errors


def record_event(journal: RollbackJournal, kind: str, payload: dict[str, Any]) -> None:
    try:
        journal.append_event(kind, payload)
        journal.flush()
    except Exception:
        journal.failed = True
        raise


def save_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@dataclass
class MergeSnapshot(Snapshot):
    space_blockers: dict[int, list[str]] = field(default_factory=dict)
    shared_storage: bool = False


@dataclass
class Group:
    owner: Any
    target: Any
    sources: tuple[Any, ...]

    def preview(self) -> dict[str, Any]:
        return {
            "user_id": self.owner.user_id,
            "user_name": self.owner.user_name,
            "target_space_id": self.target.id,
            "source_space_ids": [s.id for s in self.sources],
        }


@dataclass
class Plan:
    groups: list[Group] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)


def space_identity(space: Any) -> tuple:
    return tuple(
        getattr(space, name)
        for name in (
            "id",
            "tenant_id",
            "user_id",
            "name",
            "type",
            "model",
            "collection_name",
            "index_name",
            "state",
            "is_favorite",
            "is_released",
            "is_shared",
            "auth_type",
        )
    )


def folders_for(record: Any, files: dict[int, Any], *, include_self: bool = False) -> tuple:
    ids = path_ids(record.file_level_path)
    if include_self:
        ids += (record.id,)
    if len(ids) > 11 or len(ids) != len(set(ids)):
        raise PreflightError("invalid_source_path")
    folders = []
    for index, fid in enumerate(ids):
        folder = files.get(fid)
        if (
            folder is None
            or folder.knowledge_id != record.knowledge_id
            or folder.tenant_id != record.tenant_id
            or folder.file_type != 0
            or folder.status != 2
            or folder.level != index
            or path_ids(folder.file_level_path) != ids[:index]
            or not folder.file_name
            or "/" in folder.file_name
            or "\\" in folder.file_name
        ):
            raise PreflightError("invalid_source_path")
        folders.append(folder)
    return tuple(folders)


def find_groups(snapshot: Snapshot, user_id: int | None = None) -> tuple[list[Group], list[dict]]:
    users = {u.user_id: u for u in snapshot.users}
    scopes: dict[int, list] = defaultdict(list)
    for scope in snapshot.scopes:
        if scope.tenant_id == snapshot.tenant_id:
            scopes[scope.space_id].append(scope)
    by_owner: dict[int, list] = defaultdict(list)
    skipped = []
    for space in snapshot.spaces:
        if space.tenant_id != snapshot.tenant_id or space.type != 3 or space.is_favorite:
            continue
        entries = scopes.get(space.id, [])
        if not any(s.level == "personal" and s.owner_type == "user" for s in entries):
            continue
        owner_id = entries[0].owner_id
        if user_id is not None and user_id != owner_id:
            continue
        owner = users.get(owner_id)
        if len(entries) != 1 or owner is None or space.user_id != owner_id:
            skipped.append({"source_space_id": space.id, "reason": "invalid_personal_owner"})
            continue
        if space.name.strip() != f"{owner.user_name}的知识库".strip():
            continue
        by_owner[owner_id].append(space)
    groups = []
    for uid, spaces in sorted(by_owner.items()):
        if len(spaces) < 2:
            continue
        owner = users[uid]
        if owner.delete or uid not in snapshot.member_ids:
            skipped.extend({"source_space_id": s.id, "reason": "owner_unavailable"} for s in spaces)
            continue
        spaces.sort(key=lambda s: s.id)
        groups.append(Group(owner, spaces[0], tuple(spaces[1:])))
    return groups, skipped


def build_plan(snapshot: Snapshot, user_id: int | None = None, *, only_unit_id: str | None = None) -> Plan:
    groups, skipped = find_groups(snapshot, user_id)
    plan = Plan(groups=groups, skipped=skipped)
    index = PlanningIndex(snapshot)
    files, documents = index.files, index.documents
    by_file, by_doc = index.by_file, index.by_doc
    referenced_docs, referenced_files = index.referenced_docs, index.referenced_files
    handled = set()
    reserved = {}
    reserved_by_unit = {}
    for group in groups:
        for source in group.sources:
            blockers = getattr(snapshot, "space_blockers", {})
            reason = next(iter(blockers.get(source.id, []) + blockers.get(group.target.id, [])), None)
            if reason is None and (source.state != 1 or group.target.state != 1):
                reason = "space_not_ready"
            if reason is None and (
                source.is_shared or source.is_released or group.target.is_shared or group.target.is_released
            ):
                reason = "shared_or_released_space"
            if reason:
                plan.skipped.append({"source_space_id": source.id, "reason": reason})
                continue
            records = sorted(
                index.by_space.get(source.id, []),
                key=lambda f: (f.file_type != 0, (f.file_level_path or "").count("/") if f.file_type == 0 else 0, f.id),
            )
            for record in records:
                links = by_file.get(record.id, [])
                did = links[0].document_id if links else None
                unit_id = (
                    f"document:{did}"
                    if did is not None
                    else f"{'folder' if record.file_type == 0 else 'file'}:{record.id}"
                )
                if only_unit_id is not None and unit_id != only_unit_id:
                    continue
                if unit_id in handled:
                    continue
                handled.add(unit_id)
                members = (record,)
                try:
                    doc = documents.get(did)
                    versions = tuple(sorted(by_doc[did], key=lambda v: (v.version_no, v.id))) if did is not None else ()
                    if versions:
                        members = tuple(files.get(v.knowledge_file_id) for v in versions)
                        if (
                            doc is None
                            or any(f is None for f in members)
                            or not TargetConflictIndex._valid_version_graph(doc, versions)
                            or any(len(by_file[f.id]) != 1 for f in members)
                            or doc.knowledge_id != source.id
                        ):
                            raise PreflightError("invalid_version_chain")
                        if (
                            doc.id in referenced_docs
                            or doc.id in snapshot.locked_document_ids
                            or doc.predecessor_logic_file_id
                            or doc.lifecycle_status != "active"
                        ):
                            raise PreflightError("shared_or_locked_document")
                    if any(
                        f is None
                        or f.file_type not in {0, 1}
                        or f.status not in ({2} if f.file_type == 0 else {2, 3, 6})
                        for f in members
                    ):
                        raise PreflightError("file_ineligible")
                    if any(f.knowledge_id != source.id for f in members):
                        raise PreflightError("version_out_of_scope")
                    if any(
                        f.reference_document_id
                        or f.share_source_file_id
                        or f.predecessor_logic_file_id
                        or f.entry_type in {"publish", "share", "projection_tombstone"}
                        or f.entry_status not in {None, "active"}
                        or f.id in referenced_files
                        or f.id in snapshot.locked_file_ids
                        for f in members
                    ):
                        raise PreflightError("shared_or_locked_file")
                    is_folder = record.file_type == 0
                    if versions and any(f.file_type != 1 for f in members):
                        raise PreflightError("invalid_version_chain")
                    folders = folders_for(record, files, include_self=is_folder)
                    if not is_folder and any(folders_for(f, files) != folders for f in members):
                        raise PreflightError("version_path_mismatch")
                    if doc is not None and (doc.file_level_path or "") != (record.file_level_path or ""):
                        raise PreflightError("version_path_mismatch")
                    candidate = Candidate(
                        unit_id,
                        () if is_folder else members,
                        group.owner,
                        folders,
                        source,
                        group.target,
                        doc,
                        versions,
                        personal_space_candidate_ids=tuple(s.id for s in (group.target, *group.sources)),
                    )
                    check_target(candidate, snapshot.files, snapshot, index)
                    names = {(group.owner.user_id, candidate.folder_names, f.file_name) for f in candidate.files}
                    replaced = {reserved[name] for name in names if name in reserved}
                    candidate.replaces_planned_unit_ids = tuple(sorted(replaced))
                    for previous in replaced:
                        for name in reserved_by_unit.pop(previous, set()):
                            reserved.pop(name, None)
                    reserved.update(dict.fromkeys(names, unit_id))
                    reserved_by_unit[unit_id] = names
                    plan.candidates.append(candidate)
                except PreflightError as exc:
                    plan.skipped.append(
                        {
                            "unit_id": unit_id,
                            "source_space_id": source.id,
                            "source_file_ids": [f.id for f in members if f is not None],
                            "reason": str(exc),
                        }
                    )
    return plan


def file_identity(record: Any) -> tuple:
    return tuple(getattr(record, key) for key in ("knowledge_id", "user_id", "file_name", "file_level_path", "status"))


def cleanup_reason(
    snapshot: Snapshot, group: Group, source: Any, mappings: list[dict], expected_files: dict | None = None
) -> str | None:
    groups, _ = find_groups(snapshot, group.owner.user_id)
    current = next(
        (g for g in groups if g.target.id == group.target.id and any(s.id == source.id for s in g.sources)), None
    )
    if current is None or space_identity(current.target) != space_identity(group.target):
        return "personal_group_changed"
    fresh_source = next(s for s in current.sources if s.id == source.id)
    if space_identity(fresh_source) != space_identity(source):
        return "source_space_changed"
    blockers = getattr(snapshot, "space_blockers", {})
    if blockers.get(source.id) or blockers.get(group.target.id):
        return "space_has_active_binding_or_approval"
    source_files = [f for f in snapshot.files if f.knowledge_id == source.id]
    if any(f.file_type != 0 for f in source_files):
        return "source_not_empty"
    if any(d.knowledge_id == source.id for d in snapshot.documents):
        return "source_documents_remain"
    mapped = {m["source_folder_id"]: m for m in mappings}
    all_files = {f.id: f for f in snapshot.files}
    for fid, identity in (expected_files or {}).items():
        if fid not in all_files or file_identity(all_files[fid]) != identity:
            return "migrated_target_changed"
    for folder in source_files:
        mapping = mapped.get(folder.id)
        target = all_files.get(mapping["target_folder_id"]) if mapping else None
        if (
            target is None
            or target.knowledge_id != group.target.id
            or target.file_type != 0
            or target.file_name != folder.file_name
            or target.status != 2
            or (target.file_level_path or "") != mapping["parent_path"]
            or folder.file_name != mapping["name"]
            or folder.status != 2
            or (folder.file_level_path or "") != mapping.get("source_parent_path")
            or target.level != len(path_ids(mapping["parent_path"]))
        ):
            return "source_folder_not_preserved"
    if not getattr(snapshot, "shared_storage", False):
        for other in snapshot.spaces:
            if other.id == source.id:
                continue
            if (source.collection_name and source.collection_name == other.collection_name) or (
                source.index_name and source.index_name == other.index_name
            ):
                return "storage_used_by_another_space"
    return None


async def uses_shared_storage(tenant_id: int) -> bool:
    module_name = "bisheng.knowledge.rag.shared_space_storage"
    try:
        storage = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        # 旧部署没有共享路由模块时仍检查索引共用, 不能放宽整库删除保护。
        logger.debug("Optional shared storage module absent; using conservative per-space cleanup checks")
        return False
    return await storage.aresolve_space_shared_routing(tenant_id, 3) is not None


class Backend(MigrationBackend):
    async def verify_space_owner(self, candidate: Candidate, required: dict[str, str]) -> None:
        try:
            await super().verify_space_owner(candidate, required)
        except Exception as exc:
            # 个人库用户与租户归属已经过数据库验证; 权限系统异常记录为待修复项。
            issue = f"space owner permissions: {type(exc).__name__}: {exc}"
            candidate.preparation_issues.append(issue)
            logger.warning("Personal space permission check degraded: %s", issue)

    def plan_for_snapshot(self, snapshot: Snapshot, folder_name: str = "", unit_id: str | None = None) -> Plan:
        return build_plan(snapshot, only_unit_id=unit_id)

    async def load(self, tenant_id: int, **kwargs: Any) -> MergeSnapshot:
        from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync

        snapshot = MergeSnapshot(**vars(await super().load(tenant_id, **kwargs)))
        if kwargs.get("metadata_only") or not snapshot.spaces:
            return snapshot
        owner_ids = {s.owner_id for s in snapshot.scopes if s.level == "personal" and s.owner_type == "user"}
        missing = sorted(owner_ids - {u.user_id for u in snapshot.users})
        async with get_async_db_session() as session:
            for offset in range(0, len(missing), 500):
                batch = missing[offset : offset + 500]
                snapshot.users.extend((await session.exec(select(User).where(col(User.user_id).in_(batch)))).all())
                if settings.multi_tenant.enabled:
                    memberships = (
                        await session.exec(select(UserTenant).where(col(UserTenant.user_id).in_(batch)))
                    ).all()
                    snapshot.member_ids.update(
                        m.user_id
                        for m in memberships
                        if m.tenant_id == tenant_id and m.status == "active" and m.is_active == 1
                    )
            if not settings.multi_tenant.enabled:
                snapshot.member_ids = {u.user_id for u in snapshot.users}
            for sid in (
                await session.exec(
                    select(ChannelKnowledgeSync.knowledge_space_id).where(
                        col(ChannelKnowledgeSync.knowledge_space_id).in_([str(s.id) for s in snapshot.spaces])
                    )
                )
            ).all():
                if str(sid).isdecimal():
                    snapshot.space_blockers.setdefault(int(sid), []).append("channel_sync_binding")
            for approval in snapshot.approvals:
                if approval.business_resource_type in {"knowledge", "knowledge_space", "space"}:
                    sid = str(approval.business_resource_id or "").split(":", 1)[0]
                    if sid.isdecimal():
                        snapshot.space_blockers.setdefault(int(sid), []).append("active_space_approval")
        snapshot.shared_storage = await uses_shared_storage(tenant_id)
        return snapshot

    async def execute(self, candidate: Candidate, journal: RollbackJournal, folder_name: str = "") -> dict:
        if candidate.files:
            result = await self.execute_records(candidate, journal)
            self.annotate_mappings(candidate, result)
            return result
        created, mappings = [], []
        try:
            service, _ = await self.ensure_space(candidate, journal)
            await self.prepare_folders(candidate, service, journal, created, mappings)
            result = {"unit_id": candidate.unit_id, "status": "success", "folder_mappings": mappings}
            self.annotate_mappings(candidate, result)
            record_event(journal, "folder_unit_succeeded", result)
            return result
        except Exception as exc:
            logger.exception("Folder merge failed unit_id=%s", candidate.unit_id)
            errors = await cleanup_created_folders(created)
            return {
                "unit_id": candidate.unit_id,
                "status": "failed",
                "reason": str(exc),
                "cleanup_errors": errors,
                "folder_mappings": mappings,
            }

    async def execute_records(self, candidate: Candidate, journal: RollbackJournal) -> dict:
        created, mappings = [], []
        # 每一步留存审计; 数据库提交异常直接向外抛出, 不删除来源原文件或进行反向补偿。
        service, _ = await self.ensure_space(candidate, journal)
        target = await self.prepare_folders(candidate, service, journal, created, mappings)
        record_event(
            journal,
            "record_merge_started",
            {
                "unit_id": candidate.unit_id,
                "source_space_id": candidate.source_space.id,
                "target_space_id": target.space.id,
                "files": [f.model_dump() for f in candidate.files],
                "document": candidate.document.model_dump() if candidate.document else None,
                "versions": [v.model_dump() for v in candidate.versions],
                "overwrites": json.loads(overwrite_fingerprint(candidate.overwrites)),
            },
        )
        transfers = {}
        for file in candidate.files:
            try:
                info = await asyncio.to_thread(_transfer_record_indexes, file, candidate.source_space, target.space)
            except Exception as exc:
                # 索引属于可重建数据; 保留失败明细, 继续迁移原始记录。
                info = {
                    "via": "none",
                    "milvus_count": 0,
                    "es_count": 0,
                    "issues": [f"indexes: {type(exc).__name__}: {exc}"],
                }
            info["issues"] = [*info["issues"], *candidate.preparation_issues]
            transfers[int(file.id)] = info
        record_event(journal, "record_merge_indexes_ready", {"unit_id": candidate.unit_id, "transfers": transfers})
        moved = await _rehome_file_records(candidate, target, transfers)
        record_event(
            journal,
            "record_merge_committed",
            {
                "unit_id": candidate.unit_id,
                "target_space_id": target.space.id,
                "file_ids": [f.id for f in moved],
            },
        )

        async def best_effort(label: str, action: Callable[[], Awaitable[Any]]) -> list[str]:
            try:
                return await action() or []
            except Exception as exc:
                logger.warning("Merged records retained; %s failed: %s", label, exc)
                return [f"{label}: {type(exc).__name__}: {exc}"]

        overwrite_issues = []
        for overwrite in candidate.overwrites:
            for old in overwrite.files:
                overwrite_issues.extend(
                    await best_effort(
                        "overwrite indexes",
                        lambda old=old: asyncio.to_thread(
                            _cleanup_record_indexes, target.space, target.space, int(old.id)
                        ),
                    )
                )
                overwrite_issues.extend(
                    await best_effort(
                        "overwrite permissions", lambda old=old: _replace_permission_tuples(int(old.id), ())
                    )
                )
                overwrite_issues.extend(
                    await best_effort(
                        "overwrite tags",
                        lambda old=old: _clear_tag_links(
                            int(old.id), int(old.user_id or candidate.owner.user_id), target.tenant_id
                        ),
                    )
                )
        # 原文件对象可能被其他版本复用, 本模式不删除 MinIO 对象; 被覆盖记录的对象清单写入审计供后续回收。
        if candidate.overwrites:
            record_event(
                journal,
                "overwritten_objects_retained",
                {
                    "unit_id": candidate.unit_id,
                    "files": [
                        {"file_id": f.id, "objects": _overwrite_object_names(f)}
                        for o in candidate.overwrites
                        for f in o.files
                    ],
                },
            )
        results = []
        for file in moved:
            issues = list(overwrite_issues)
            issues.extend(
                await best_effort(
                    "source indexes",
                    lambda file=file: asyncio.to_thread(
                        _cleanup_record_indexes, candidate.source_space, target.space, int(file.id)
                    ),
                )
            )
            issues.extend(
                await best_effort(
                    "target permissions",
                    lambda file=file: _replace_permission_tuples(int(file.id), _target_permission_rows(file, target)),
                )
            )
            await _mark_record_for_reparse(int(file.id), issues)
            info = transfers[int(file.id)]
            info["issues"] = list(dict.fromkeys([*info["issues"], *issues]))
            results.append(
                {
                    "source_file_id": file.id,
                    "target_file_id": file.id,
                    "status": "success",
                    "source_deleted": False,
                    "source_rehomed": True,
                    "requires_reparse": bool(info["issues"]),
                    "index_transfer": info,
                }
            )
            if info["issues"]:
                logger.warning("File merged with parse failure file_id=%s issues=%s", file.id, info["issues"])
        projection_issues = await best_effort(
            "file projections", lambda: _refresh_merge_projections([int(f.id) for f in moved], int(target.space.id))
        )
        if projection_issues:
            for result in results:
                await _mark_record_for_reparse(result["target_file_id"], projection_issues)
                result["requires_reparse"] = True
                result["index_transfer"]["issues"].extend(projection_issues)
        result = {
            "unit_id": candidate.unit_id,
            "status": "success",
            "mode": "rehome_records",
            "results": results,
            "folder_mappings": mappings,
            "requires_reparse": any(r["requires_reparse"] for r in results),
            "overwrite_targets": [
                {"logical_id": o.logical_id, "file_ids": [f.id for f in o.files]} for o in candidate.overwrites
            ],
        }
        record_event(journal, "record_merge_succeeded", result)
        return result

    @staticmethod
    def annotate_mappings(candidate: Candidate, result: dict) -> None:
        source_paths = {f.id: f.file_level_path or "" for f in candidate.folders}
        for mapping in result.get("folder_mappings", []):
            mapping["source_parent_path"] = source_paths[mapping["source_folder_id"]]

    async def delete_empty_source(
        self,
        group: Group,
        source: Any,
        mappings: list[dict],
        journal: RollbackJournal,
        expected_files: dict | None = None,
    ) -> list[str]:
        from bisheng.common.models.space_channel_member import SpaceChannelMemberDao

        latest = await self.load(source.tenant_id, user_id=group.owner.user_id)
        reason = cleanup_reason(latest, group, source, mappings, expected_files)
        if reason:
            raise PreflightError(reason)
        candidate = Candidate(f"space:{source.id}", (), group.owner, (), source, group.target)
        service = await self.service_for(candidate)
        service.request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        record_event(
            journal,
            "source_space_delete_started",
            {
                "user_id": group.owner.user_id,
                "source_space": source.model_dump(),
                "target_space_id": group.target.id,
                "folder_mappings": mappings,
            },
        )
        issues = []
        try:
            await service.delete_space(source.id, force=True)
        except Exception as exc:
            # 文件已迁出; 外部索引/权限异常不应阻止移除空库, 仍须重新验证并提交数据库删除。
            issues.append(f"space service cleanup: {type(exc).__name__}: {exc}")
            logger.warning("Empty space cleanup degraded space_id=%s: %s", source.id, exc)
        await _delete_empty_space_records(int(source.id))
        try:
            await SpaceChannelMemberDao.clean_space_member(source.id)
        except Exception as exc:
            issues.append(f"space members cleanup: {type(exc).__name__}: {exc}")
        for object_ref in [
            f"knowledge_space:{source.id}",
            *(f"folder:{f.id}" for f in latest.files if f.knowledge_id == source.id and f.file_type == 0),
        ]:
            try:
                await _replace_resource_permission_tuples(object_ref, ())
            except Exception as exc:
                issues.append(f"{object_ref} permissions cleanup: {type(exc).__name__}: {exc}")
        if await self.source_has_rows(source.id):
            raise RuntimeError("旧库数据库记录仍有残留")
        if issues:
            record_event(
                journal,
                "source_space_cleanup_pending",
                {"source_space_id": source.id, "issues": issues, "source_space": source.model_dump()},
            )
            for fid in expected_files or {}:
                await _mark_record_for_reparse(fid, issues)
        record_event(
            journal,
            "source_space_deleted",
            {"source_space_id": source.id, "target_space_id": group.target.id, "cleanup_issues": issues},
        )
        return issues


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all-users", action="store_true", help="扫描当前租户全部用户")
    scope.add_argument("--user-id", type=_positive_int, help="仅处理指定用户")
    parser.add_argument("--tenant-id", type=_positive_int)
    parser.add_argument("--apply", action="store_true", help="执行迁移、覆盖及空旧库清理；默认只读")
    parser.add_argument(
        "--stop-on-error", action="store_true", help="单个文件失败也停止；默认在来源保全且清理完成后继续"
    )
    parser.add_argument("--report-dir", type=Path, default=Path("migration_reports/merge_personal_spaces"))
    return parser.parse_args(argv)


async def apply_plan(args: argparse.Namespace, backend: Backend, plan: Plan, report: dict, report_path: Path) -> int:
    journal = RollbackJournal(path=report_path.with_suffix(".jsonl"), run_id=report["run_id"])
    report.update(status="running", journal_path=str(journal.path.resolve()))
    controller = StopController()
    code = 0
    last_report_time = time.monotonic()
    try:
        journal.open()
        record_event(
            journal,
            "merge_started",
            {"tenant_id": report["tenant_id"], "groups": report["groups"], "planned": report["planned"]},
        )
        await backend.initialize_apply()
        with _sigint_stop_scope(controller, enabled=True):
            for group in plan.groups:
                for source in group.sources:
                    if controller.requested:
                        raise InterruptedError("合并已中断，未继续删除旧库")
                    retained = any(s.get("source_space_id") == source.id for s in plan.skipped)
                    mappings = []
                    source_cleanup_issues = []
                    expected_files = {}
                    for candidate in (c for c in plan.candidates if c.source_space.id == source.id):
                        if controller.requested:
                            raise InterruptedError("合并已中断，未继续删除旧库")
                        latest = build_plan(
                            await backend.load(report["tenant_id"], user_id=group.owner.user_id, candidate=candidate),
                            group.owner.user_id,
                            only_unit_id=candidate.unit_id,
                        )
                        fresh = next((c for c in latest.candidates if c.unit_id == candidate.unit_id), None)
                        if (
                            fresh is None
                            or fresh.fingerprint() != candidate.fingerprint()
                            or fresh.target_space.id != group.target.id
                        ):
                            outcome = {"unit_id": candidate.unit_id, "status": "skipped", "reason": "preflight_changed"}
                        else:
                            outcome = await backend.execute(fresh, journal)
                        outcome["source_space_id"] = source.id
                        report["results"].append(outcome)
                        report["pending"] -= 1
                        mappings.extend(outcome.get("folder_mappings", []))
                        retained = retained or outcome["status"] != "success"
                        record_event(journal, "merge_unit_finished", outcome)
                        if len(report["results"]) % 20 == 0 or time.monotonic() - last_report_time >= 10:
                            save_report(report_path, report)
                            last_report_time = time.monotonic()
                        if outcome["status"] == "failed":
                            if getattr(args, "stop_on_error", False) or not outcome.get("recoverable", False):
                                raise RuntimeError(f"迁移失败，已停止: {candidate.unit_id}")
                            save_report(report_path, report)
                            last_report_time = time.monotonic()
                            print(f"[保留来源并继续] {candidate.unit_id}: {outcome.get('reason', '')}")
                            continue
                        if outcome["status"] == "skipped":
                            print(f"[跳过] {candidate.unit_id}: {outcome.get('reason', '')}")
                        if outcome["status"] == "success":
                            for overwrite in outcome.get("overwrite_targets", []):
                                for fid in overwrite["file_ids"]:
                                    expected_files.pop(fid, None)
                            moved_ids = [r["target_file_id"] for r in outcome.get("results", [])]
                            current_files = await backend.read_files(moved_ids) if moved_ids else {}
                            for moved in outcome.get("results", []):
                                fid = moved["target_file_id"]
                                if fid not in current_files:
                                    raise RuntimeError(f"迁入文件丢失: {fid}")
                                expected_files[fid] = file_identity(current_files[fid])
                    if controller.requested:
                        raise InterruptedError("合并已中断，未继续删除旧库")
                    reason = (
                        "source_has_skipped_units"
                        if retained
                        else cleanup_reason(
                            await backend.load(report["tenant_id"], user_id=group.owner.user_id),
                            group,
                            source,
                            mappings,
                            expected_files,
                        )
                    )
                    if reason is None:
                        try:
                            source_cleanup_issues = (
                                await backend.delete_empty_source(group, source, mappings, journal, expected_files)
                                or []
                            )
                            if source_cleanup_issues:
                                for outcome in report["results"]:
                                    if outcome.get("source_space_id") == source.id and outcome["status"] == "success":
                                        outcome["requires_reparse"] = True
                                        outcome["space_cleanup_issues"] = source_cleanup_issues
                        except PreflightError as exc:
                            reason = str(exc)
                        except Exception as exc:
                            failed_source = {
                                "source_space_id": source.id,
                                "target_space_id": group.target.id,
                                "status": "failed",
                                "reason": str(exc),
                            }
                            report["source_results"].append(failed_source)
                            record_event(journal, "source_merge_failed", failed_source)
                            raise
                    result = {
                        "source_space_id": source.id,
                        "target_space_id": group.target.id,
                        "status": "retained" if reason else "deleted",
                        "reason": reason,
                        "cleanup_issues": source_cleanup_issues,
                    }
                    report["source_results"].append(result)
                    report["pending_sources"] -= 1
                    record_event(journal, "source_merge_finished", result)
                    save_report(report_path, report)
                    print(f"[{result['status']}] {source.id} -> {group.target.id}: {reason or ''}")
        report["status"] = (
            "completed_with_errors"
            if any(r["status"] == "failed" for r in report["results"])
            else "completed_with_skips"
            if plan.skipped or any(r["status"] == "retained" for r in report["source_results"])
            else "completed_with_reparse"
            if any(r.get("requires_reparse") for r in report["results"])
            or any(r.get("cleanup_issues") for r in report["source_results"])
            else "completed"
        )
        if report["status"] == "completed_with_errors":
            code = 3
    except InterruptedError as exc:
        report.update(status="interrupted", error=str(exc))
        code = 130
    except Exception as exc:
        logger.exception("Personal space merge stopped")
        report.update(status="failed", error=str(exc))
        code = 3
    finally:
        try:
            record_event(
                journal,
                "merge_finished",
                {
                    "status": report["status"],
                    "pending": report["pending"],
                    "pending_sources": report["pending_sources"],
                },
            )
        except Exception as exc:
            report.update(status="failed", journal_error=str(exc))
            code = 3
        try:
            journal.close(flush=False)
        except Exception as exc:
            report.update(status="failed", journal_close_error=str(exc))
            code = 3
        report["result_counts"] = dict(Counter(r["status"] for r in report["results"]))
        report["source_counts"] = dict(Counter(r["status"] for r in report["source_results"]))
        report["reparse_file_ids"] = sorted(
            {
                r["target_file_id"]
                for outcome in report["results"]
                for r in outcome.get("results", [])
                if r.get("requires_reparse") or outcome.get("space_cleanup_issues")
            }
            - {
                fid
                for outcome in report["results"]
                if outcome["status"] == "success"
                for overwrite in outcome.get("overwrite_targets", [])
                for fid in overwrite["file_ids"]
            }
        )
        save_report(report_path, report)
        print(
            f"[结束] status={report['status']} success={report['result_counts'].get('success', 0)} "
            f"failed={report['result_counts'].get('failed', 0)} "
            f"reparse={len(report['reparse_file_ids'])} "
            f"skipped={len(plan.skipped) + report['result_counts'].get('skipped', 0)} "
            f"pending={report['pending']} 报告={report_path.resolve()}"
        )
    return code


async def run(args: argparse.Namespace, *, backend: Backend | None = None) -> int:
    backend = backend or Backend()
    tenant_id = resolve_tenant(args, bool(settings.multi_tenant.enabled))
    run_id = uuid.uuid4().hex
    report_path = args.report_dir / f"merge-{run_id}.json"
    with _tenant_scope(tenant_id):
        discovery = await backend.load(tenant_id, user_id=args.user_id, metadata_only=True)
        groups, skipped = find_groups(discovery, args.user_id)
        print(f"[扫描] 重复用户={len(groups)}，开始按用户读取文件并生成计划")
        plan = Plan(skipped=skipped)
        for group in groups:
            current = build_plan(await backend.load(tenant_id, user_id=group.owner.user_id), group.owner.user_id)
            plan.groups.extend(current.groups)
            plan.candidates.extend(current.candidates)
            plan.skipped.extend(current.skipped)
            print(f"[预览] user_id={group.owner.user_id} 单元={len(current.candidates)} 跳过={len(current.skipped)}")
        report = {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "mode": "apply" if args.apply else "dry-run",
            "status": "preview",
            "groups": [g.preview() for g in plan.groups],
            "group_count": len(plan.groups),
            "planned": [c.preview() for c in plan.candidates],
            "skipped": plan.skipped,
            "pending": len(plan.candidates),
            "pending_sources": sum(len(g.sources) for g in plan.groups),
            "results": [],
            "source_results": [],
        }
        save_report(report_path, report)
        print(
            f"重复用户={len(plan.groups)} 待合并旧库={report['pending_sources']} 单元={len(plan.candidates)} 跳过={len(plan.skipped)} 报告={report_path.resolve()}"
        )
        return await apply_plan(args, backend, plan, report, report_path) if args.apply else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    async def entry() -> int:
        try:
            return await run(args)
        finally:
            await close_app_context()

    try:
        return asyncio.run(entry())
    except KeyboardInterrupt:
        return 130
    except Exception:
        logger.exception("个人库合并中止，请核对报告")
        return 2


if __name__ == "__main__":
    sys.exit(main())
