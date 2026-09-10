#!/usr/bin/env python3
# ruff: noqa: E402, RUF001, RUF003
"""部门指定目录按 user_id 迁入个人知识库, 独立单文件部署。

默认预览, --apply 才执行。保留文件 ID、原文件地址和版本链, 同名后迁入覆盖旧数据库记录。
Milvus 不可读时尝试 ES; 索引失败仍迁入并标记解析失败。权限切换、数据库或审计失败停止。
必须停写并串行执行。旧目标对象暂留审计待回收; 不删除部门库或来源目录。
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
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import col, delete, or_, select

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
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTagDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeDao,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
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

logger = logging.getLogger(__name__)
ROLLBACK_RECORD_SCHEMA_VERSION = 1


class RollbackRecordError(RuntimeError):
    """审计文件不可用时必须停止。"""


class PreflightError(RuntimeError):
    """Raised when validation must stop the whole batch before any write."""


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

    return KnowledgeFileFailedError(exception=RuntimeError("迁移完成，需重新解析: " + "; ".join(issues))).to_json_str()


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
                    "department_to_personal": {"source_space_id": candidate.source_space.id, **info},
                }
                session.add(current)
            await session.flush()
            for current in moving:
                await session.refresh(current)
            result = [KnowledgeFile(**current.model_dump()) for current in moving]
            await session.commit()
            return result
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
        detail = dict(metadata.get("department_to_personal") or {})
        detail["issues"] = list(dict.fromkeys([*detail.get("issues", []), *issues]))
        metadata["department_to_personal"] = detail
        record.user_metadata, record.status = metadata, 3
        record.remark = _merge_failure_remark(detail["issues"])
        session.add(record)
        await session.commit()


async def _refresh_merge_projections(file_ids: list[int], space_id: int) -> None:
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
    from bisheng.worker.knowledge.portal_recommendation import enqueue_portal_recommendation_projection_refresh

    await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)
    if not await KnowledgeSpaceContentStat.enqueue_file_stat_async(file_ids):
        raise RuntimeError("content statistics refresh enqueue failed")
    for file_id in file_ids:
        await asyncio.to_thread(enqueue_portal_recommendation_projection_refresh, file_id=file_id)


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


@dataclass
class StopController:
    requested: bool = False

    def request_stop(self) -> None:
        self.requested = True


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


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


def record_event(journal: RollbackJournal, kind: str, payload: dict[str, Any]) -> None:
    try:
        journal.append_event(kind, payload)
        journal.flush()
    except Exception:
        journal.failed = True
        raise


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
    referenced_file_ids: set[int] = field(default_factory=set)
    referenced_document_ids: set[int] = field(default_factory=set)
    locked_file_ids: set[int] = field(default_factory=set)


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
    preparation_issues: list[str] = field(default_factory=list)
    replaces_planned_unit_ids: tuple[str, ...] = ()

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


@dataclass
class Plan:
    candidates: list[Candidate] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    department_count: int = 0
    matched_space_count: int = 0


def path_ids(path: str | None) -> tuple[int, ...]:
    if not path:
        return ()
    if not path.startswith("/") or any(not p.isdecimal() or int(p) <= 0 for p in path[1:].split("/")):
        raise PreflightError("invalid_source_path")
    ids = tuple(int(p) for p in path[1:].split("/"))
    if len(ids) != len(set(ids)):
        raise PreflightError("invalid_source_path")
    return ids


def source_folders(
    record: KnowledgeFile, root: KnowledgeFile, files: dict[int, KnowledgeFile]
) -> tuple[KnowledgeFile, ...]:
    ids = path_ids(record.file_level_path)
    if not ids or ids[0] != root.id:
        raise PreflightError("version_out_of_scope")
    result = []
    for i, fid in enumerate(ids):
        folder = files.get(fid)
        if (
            folder is None
            or folder.file_type != 0
            or folder.knowledge_id != record.knowledge_id
            or path_ids(folder.file_level_path) != ids[:i]
            or folder.status != 2
            or folder.level != i
            or not folder.file_name
            or "/" in folder.file_name
        ):
            raise PreflightError("invalid_source_path")
        result.append(folder)
    if len(result) > 11:
        raise PreflightError("target_depth_exceeded")
    return tuple(result)


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
                or not _valid_version_graph(doc, versions)
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


def build_plan(snapshot: Snapshot, folder_name: str) -> Plan:
    plan = Plan()
    index = PlanningIndex(snapshot)
    tid = snapshot.tenant_id
    spaces = {s.id: s for s in snapshot.spaces if s.tenant_id == tid and s.type == KnowledgeTypeEnum.SPACE.value}
    scopes = {s.space_id: s for s in snapshot.scopes if s.tenant_id == tid}
    departments = {sid: s for sid, s in spaces.items() if sid in scopes and scopes[sid].level == "department"}
    plan.department_count = len(departments)
    files = {f.id: f for f in snapshot.files if f.tenant_id == tid}
    users = {u.user_id: u for u in snapshot.users if not u.delete and u.user_id in snapshot.member_ids}
    targets_by_owner: dict[int, list[Knowledge]] = defaultdict(list)
    for sid, target in spaces.items():
        scope = scopes.get(sid)
        owner = users.get(scope.owner_id) if scope is not None else None
        if (
            scope is not None
            and scope.level == "personal"
            and scope.owner_type == "user"
            and owner is not None
            and not target.is_favorite
            and target.name.strip() == f"{owner.user_name}的知识库".strip()
        ):
            targets_by_owner[owner.user_id].append(target)
    for targets in targets_by_owner.values():
        targets.sort(key=lambda target: target.id)
    documents = {d.id: d for d in snapshot.documents if d.tenant_id == tid}
    by_file: dict[int, list[KnowledgeDocumentVersion]] = defaultdict(list)
    by_doc: dict[int, list[KnowledgeDocumentVersion]] = defaultdict(list)
    for v in snapshot.versions:
        if v.document_id in documents or v.knowledge_file_id in files:
            by_file[v.knowledge_file_id].append(v)
            by_doc[v.document_id].append(v)
    references = index.referenced_docs
    referenced_files = {
        fid for f in files.values() for fid in (f.predecessor_logic_file_id, f.share_source_file_id) if fid
    }
    referenced_files.update(d.predecessor_logic_file_id for d in documents.values() if d.predecessor_logic_file_id)
    referenced_files.update(index.referenced_files)
    roots: dict[int, KnowledgeFile] = {}
    for sid in departments:
        matches = [f for f in index.by_name.get((sid, "", folder_name), []) if f.file_type == 0]
        if len(matches) == 1:
            roots[sid] = matches[0]
        elif matches:
            plan.skipped.append({"source_space_id": sid, "reason": "ambiguous_source_root"})
    plan.matched_space_count = len(roots)
    selected = [
        f
        for f in files.values()
        if f.file_type == 1
        and f.knowledge_id in roots
        and (
            (f.file_level_path or "") == f"/{roots[f.knowledge_id].id}"
            or (f.file_level_path or "").startswith(f"/{roots[f.knowledge_id].id}/")
        )
    ]
    handled: set[str] = set()
    reserved: dict[tuple[int, tuple[str, ...], str], str] = {}
    reserved_by_unit = {}
    for record in sorted(selected, key=lambda f: (f.knowledge_id, f.id)):
        versions = by_file.get(record.id, [])
        did = versions[0].document_id if versions else None
        key = f"document:{did}" if did is not None else f"file:{record.id}"
        if key in handled:
            continue
        handled.add(key)
        chain = tuple(sorted(by_doc[did], key=lambda v: (v.version_no, v.id))) if did is not None else ()
        members = tuple(files.get(v.knowledge_file_id) for v in chain) if chain else (record,)
        try:
            doc = documents.get(did)
            if did is not None:
                if (
                    doc is None
                    or any(f is None for f in members)
                    or not _valid_version_graph(doc, chain)
                    or any(len(by_file[f.id]) != 1 for f in members if f is not None)
                    or doc.knowledge_id != record.knowledge_id
                ):
                    raise PreflightError("invalid_version_chain")
                if (
                    did in references
                    or doc.predecessor_logic_file_id
                    or doc.lifecycle_status != "active"
                    or did in snapshot.locked_document_ids
                ):
                    raise PreflightError("shared_or_locked_document")
            if any(f is None or f.status not in {2, 3, 6} or f.file_type != 1 for f in members):
                raise PreflightError("file_ineligible")
            if any(f.knowledge_id != record.knowledge_id for f in members):
                raise PreflightError("version_out_of_scope")
            if any(
                f.reference_document_id
                or f.entry_type in {"publish", "share", "projection_tombstone"}
                or f.entry_status not in {None, "active"}
                or f.predecessor_logic_file_id
                or f.share_source_file_id
                or f.id in referenced_files
                for f in members
            ):
                raise PreflightError("shared_relationship")
            if any(f.id in snapshot.locked_file_ids for f in members):
                raise PreflightError("active_approval")
            owner = users.get(record.user_id)
            if owner is None or not owner.user_name:
                raise PreflightError("owner_unavailable")
            if any(f.user_id != owner.user_id for f in members):
                raise PreflightError("version_owner_mismatch")
            folders = source_folders(record, roots[record.knowledge_id], files)
            if any(source_folders(f, roots[record.knowledge_id], files) != folders for f in members):
                raise PreflightError("version_path_mismatch")
            if doc is not None and (doc.file_level_path or "") != (record.file_level_path or ""):
                raise PreflightError("version_path_mismatch")
            targets = targets_by_owner.get(owner.user_id, [])
            candidate = Candidate(
                key,
                members,
                owner,
                folders,
                departments[record.knowledge_id],
                targets[0] if targets else None,
                doc,
                chain,
                personal_space_candidate_ids=tuple(s.id for s in targets),
            )
            check_target(candidate, snapshot.files, snapshot, index)
            names = {(owner.user_id, candidate.folder_names, f.file_name) for f in members}
            replaced = {reserved[name] for name in names if name in reserved}
            candidate.replaces_planned_unit_ids = tuple(sorted(replaced))
            for previous in replaced:
                for name in reserved_by_unit.pop(previous, set()):
                    reserved.pop(name, None)
            reserved_by_unit[candidate.unit_id] = names
            reserved.update(dict.fromkeys(names, candidate.unit_id))
            plan.candidates.append(candidate)
        except PreflightError as exc:
            plan.skipped.append(
                {
                    "unit_id": key,
                    "source_space_id": record.knowledge_id,
                    "source_file_ids": [f.id for f in members if f is not None],
                    "reason": str(exc),
                }
            )
    return plan


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder-name", required=True, help="部门知识库根目录下的目录名称，精确匹配")
    parser.add_argument("--tenant-id", type=_positive_int)
    parser.add_argument("--report-dir", type=Path, default=Path("migration_reports/department_to_personal"))
    parser.add_argument("--apply", action="store_true", help="实际创建资源并迁移；默认只读预览")
    args = parser.parse_args(argv)
    if not args.folder_name.strip() or "/" in args.folder_name or "\\" in args.folder_name:
        parser.error("--folder-name 必须为非空的单个目录名称")
    return args


def resolve_tenant(args: argparse.Namespace, enabled: bool) -> int:
    if enabled and args.tenant_id is None:
        raise PreflightError("多租户开启时必须指定 --tenant-id")
    if not enabled and args.tenant_id not in {None, 1}:
        raise PreflightError("单租户模式只允许默认租户 1")
    return args.tenant_id or 1


class Backend:
    async def load(
        self,
        tenant_id: int,
        *,
        folder_name: str = "",
        source_space_id: int | None = None,
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
                .where(Knowledge.type == 3, KnowledgeSpaceScope.level == "department")
            )
            sid = candidate.source_space.id if candidate else source_space_id
            if sid is not None:
                statement = statement.where(Knowledge.id == sid)
            spaces = list({s.id: s for s in (await session.exec(statement)).all()}.values())
            state = Snapshot(tenant_id, spaces=spaces)
            state.scopes = await rows_by_ids(
                session, KnowledgeSpaceScope, KnowledgeSpaceScope.space_id, [s.id for s in spaces]
            )
            if metadata_only or not spaces:
                return state
            if candidate is not None:
                state.files = await rows_by_ids(
                    session, KnowledgeFile, KnowledgeFile.id, [f.id for f in (*candidate.files, *candidate.folders)]
                )
            else:
                for source in spaces:
                    roots = list(
                        (
                            await session.exec(
                                select(KnowledgeFile).where(
                                    KnowledgeFile.knowledge_id == source.id,
                                    KnowledgeFile.file_type == 0,
                                    KnowledgeFile.file_name == folder_name,
                                    or_(
                                        KnowledgeFile.file_level_path == "",
                                        col(KnowledgeFile.file_level_path).is_(None),
                                    ),
                                )
                            )
                        ).all()
                    )
                    state.files.extend(roots)
                    if len(roots) == 1:
                        path = f"/{roots[0].id}"
                        state.files.extend(
                            (
                                await session.exec(
                                    select(KnowledgeFile).where(
                                        KnowledgeFile.knowledge_id == source.id,
                                        or_(
                                            KnowledgeFile.file_level_path == path,
                                            col(KnowledgeFile.file_level_path).like(path + "/%"),
                                        ),
                                    )
                                )
                            ).all()
                        )
            owner_ids = {f.user_id for f in state.files if f.file_type == 1 and f.user_id}
            state.users = await rows_by_ids(session, User, User.user_id, owner_ids)
            if settings.multi_tenant.enabled:
                memberships = await rows_by_ids(session, UserTenant, UserTenant.user_id, owner_ids)
                state.member_ids = {
                    u.user_id
                    for u in memberships
                    if u.tenant_id == tenant_id and u.status == "active" and u.is_active == 1
                }
            else:
                state.member_ids = {u.user_id for u in state.users}
            # 只读取候选上传人的默认个人库及当前路径所需记录。
            users = {u.user_id: u for u in state.users}
            personal_spaces = []
            for offset in range(0, len(owner_ids), 400):
                batch = sorted(owner_ids)[offset : offset + 400]
                personal_spaces.extend(
                    (
                        await session.exec(
                            select(Knowledge)
                            .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
                            .where(
                                Knowledge.type == 3,
                                KnowledgeSpaceScope.level == "personal",
                                KnowledgeSpaceScope.owner_type == "user",
                                col(KnowledgeSpaceScope.owner_id).in_(batch),
                                or_(col(Knowledge.is_favorite).is_(False), col(Knowledge.is_favorite).is_(None)),
                            )
                        )
                    ).all()
                )
            personal_scopes = await rows_by_ids(
                session, KnowledgeSpaceScope, KnowledgeSpaceScope.space_id, [s.id for s in personal_spaces]
            )
            owner_by_space = {s.space_id: s.owner_id for s in personal_scopes}
            personal_spaces = list(
                {
                    s.id: s
                    for s in personal_spaces
                    if owner_by_space.get(s.id) in users
                    and s.name.strip() == f"{users[owner_by_space[s.id]].user_name}的知识库".strip()
                }.values()
            )
            state.spaces.extend(personal_spaces)
            selected_ids = {s.id for s in personal_spaces}
            state.scopes.extend(s for s in personal_scopes if s.space_id in selected_ids)
            by_owner = defaultdict(list)
            for target in personal_spaces:
                by_owner[owner_by_space[target.id]].append(target)
            source_files = {f.id: f for f in state.files}
            names_by_owner = defaultdict(set)
            for source_file in state.files:
                if source_file.file_type != 1:
                    continue
                names_by_owner[source_file.user_id].add(source_file.file_name)
                # 路径合法性由规划逐文件报告, 预加载不因单个坏路径中断整库。
                for folder_id in (
                    int(part) for part in (source_file.file_level_path or "").split("/") if part.isdecimal()
                ):
                    if folder_id in source_files:
                        names_by_owner[source_file.user_id].add(source_files[folder_id].file_name)
            for owner_id, targets in by_owner.items():
                names = sorted(names_by_owner[owner_id])
                target = min(targets, key=lambda s: s.id)
                for offset in range(0, len(names), 400):
                    state.files.extend(
                        (
                            await session.exec(
                                select(KnowledgeFile).where(
                                    KnowledgeFile.knowledge_id == target.id,
                                    col(KnowledgeFile.file_name).in_(names[offset : offset + 400]),
                                )
                            )
                        ).all()
                    )
            files = {f.id: f for f in state.files}
            documents = {}
            versions = await versions_for_ids(session, [], files)
            documents.update(
                (d.id, d)
                for d in await rows_by_ids(
                    session, KnowledgeDocument, KnowledgeDocument.id, {v.document_id for v in versions}
                )
            )
            versions.extend(await versions_for_ids(session, documents, []))
            member_ids = {v.knowledge_file_id for v in versions} - files.keys()
            files.update((f.id, f) for f in await rows_by_ids(session, KnowledgeFile, KnowledgeFile.id, member_ids))
            versions.extend(await versions_for_ids(session, [], member_ids))
            # 额外链接对应的文档也必须加载, 防止断链被误认为无版本文件。
            documents.update(
                (d.id, d)
                for d in await rows_by_ids(
                    session,
                    KnowledgeDocument,
                    KnowledgeDocument.id,
                    {v.document_id for v in versions} - documents.keys(),
                )
            )
            state.files, state.documents, state.versions = (
                list(files.values()),
                list(documents.values()),
                list({v.id: v for v in versions}.values()),
            )
            await load_reference_guards(session, state)
            approvals = (
                await session.exec(
                    select(ApprovalInstance).where(
                        col(ApprovalInstance.status).in_(["pending", "exception", "execute_failed"])
                    )
                )
            ).all()
            for approval in approvals:
                if approval.tenant_id != tenant_id:
                    continue
                first = str(approval.business_resource_id or "").split(":", 1)[0]
                if not first.isdecimal():
                    continue
                if approval.scenario_code == "knowledge_space_file_publish_request":
                    state.locked_document_ids.add(int(first))
                if approval.business_resource_type in {"knowledge_file", "file"} or "file" in approval.scenario_code:
                    state.locked_file_ids.add(int(first))
                    state.locked_document_ids.add(int(first))
            return state

    async def rehome_with_permissions(
        self, candidate: Candidate, target: TargetContext, transfers: dict[int, dict], journal: RollbackJournal
    ) -> list[KnowledgeFile]:
        latest = build_plan(
            await self.load(candidate.source_space.tenant_id, candidate=candidate), candidate.folder_names[0]
        )
        fresh = next((c for c in latest.candidates if c.unit_id == candidate.unit_id), None)
        if (
            fresh is None
            or fresh.fingerprint() != candidate.fingerprint()
            or fresh.target_space is None
            or fresh.target_space.id != target.space.id
            or overwrite_fingerprint(fresh.overwrites) != overwrite_fingerprint(candidate.overwrites)
        ):
            raise PreflightError("source_or_target_changed_before_commit")
        previous = {}
        try:
            for file in candidate.files:
                fid = int(file.id)
                previous[fid] = await _read_permission_tuples(fid)
                desired = _target_permission_rows(file, target)
                record_event(
                    journal,
                    "permission_transfer_started",
                    {"file_id": fid, "previous": previous[fid], "desired": desired},
                )
                await _replace_permission_tuples(fid, desired)
                actual = await _read_permission_tuples(fid)
                if {tuple(sorted(row.items())) for row in actual} != {tuple(sorted(row.items())) for row in desired}:
                    raise RuntimeError(f"target permissions not confirmed: {fid}")
            return await _rehome_file_records(candidate, target, transfers)
        except Exception:
            # 提交响应丢失时先查归属; 不能把已迁入个人库的文件重新授权给旧部门。
            async with get_async_db_session() as session:
                current = await rows_by_ids(session, KnowledgeFile, KnowledgeFile.id, previous)
            unchanged = {f.id for f in current if f.knowledge_id == candidate.source_space.id}
            for fid, rows in previous.items():
                if fid in unchanged:
                    try:
                        await _replace_permission_tuples(fid, rows)
                    except Exception as exc:
                        record_event(
                            journal, "permission_restore_failed", {"file_id": fid, "previous": rows, "error": str(exc)}
                        )
                        logger.exception("Permission restoration failed file_id=%s", fid)
            raise

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
            record_event(journal, "personal_space_create_started", candidate.preview())
            target = await service.ensure_personal_default_space_for_owner(service.login_user)
            record_event(
                journal,
                "personal_space_created",
                {
                    "user_id": candidate.owner.user_id,
                    "space_id": target.id,
                    "name": target.name,
                    "retained_on_failure": True,
                },
            )
        candidate.target_space = target
        latest = await self.load(candidate.source_space.tenant_id, candidate=candidate)
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
        if required not in await _read_resource_permission_tuples(required["object"]):
            raise RuntimeError("个人知识库 owner 权限未生效")
        return service, target

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

    async def execute(self, candidate: Candidate, journal: RollbackJournal, folder_name: str = "") -> dict:
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
        moved = await self.rehome_with_permissions(candidate, target, transfers, journal)
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


def save_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


async def apply_plan(args: argparse.Namespace, backend: Backend, plan: Plan, report: dict, report_path: Path) -> int:
    journal = RollbackJournal(path=report_path.with_suffix(".jsonl"), run_id=report["run_id"])
    controller = StopController()
    report.update(status="running", journal_path=str(journal.path.resolve()))
    exit_code, last_save = 0, time.monotonic()
    try:
        journal.open()
        record_event(
            journal,
            "run_started",
            {"tenant_id": report["tenant_id"], "folder_name": args.folder_name, "planned": report["planned"]},
        )
        await backend.initialize_apply()
        with _sigint_stop_scope(controller, enabled=True):
            for index, candidate in enumerate(plan.candidates):
                if controller.requested:
                    raise InterruptedError("迁移已中断")
                latest = build_plan(await backend.load(report["tenant_id"], candidate=candidate), args.folder_name)
                fresh = next((c for c in latest.candidates if c.unit_id == candidate.unit_id), None)
                if fresh is None or fresh.fingerprint() != candidate.fingerprint():
                    outcome = {"unit_id": candidate.unit_id, "status": "skipped", "reason": "preflight_changed"}
                else:
                    try:
                        outcome = await backend.execute(fresh, journal, args.folder_name)
                    except Exception as exc:
                        outcome = {
                            "unit_id": candidate.unit_id,
                            "status": "failed",
                            "reason": f"{type(exc).__name__}: {exc}",
                        }
                report["results"].append(outcome)
                report["pending"] = len(plan.candidates) - index - 1
                record_event(journal, "unit_finished", outcome)
                if len(report["results"]) % 20 == 0 or time.monotonic() - last_save >= 10:
                    save_report(report_path, report)
                    last_save = time.monotonic()
                print(f"[{outcome['status']}] {candidate.unit_id}: {outcome.get('reason', '')}")
                if outcome["status"] == "failed":
                    raise RuntimeError(f"迁移中止: {candidate.unit_id}: {outcome['reason']}")
        report["status"] = (
            "completed_with_skips"
            if plan.skipped or any(r["status"] == "skipped" for r in report["results"])
            else "completed_with_reparse"
            if any(r.get("requires_reparse") for r in report["results"])
            else "completed"
        )
    except InterruptedError as exc:
        report.update(status="interrupted", error=str(exc))
        exit_code = 130
    except Exception as exc:
        logger.exception("部门迁移中止")
        report.update(status="failed", error=str(exc))
        exit_code = 3
    finally:
        try:
            record_event(journal, "run_finished", {"status": report["status"], "pending": report["pending"]})
        except Exception as exc:
            report.update(status="failed", journal_error=str(exc))
            exit_code = 3
        try:
            journal.close(flush=False)
        except Exception as exc:
            report.update(status="failed", journal_close_error=str(exc))
            exit_code = 3
        report["result_counts"] = dict(Counter(r["status"] for r in report["results"]))
        report["reparse_file_ids"] = sorted(
            {r["target_file_id"] for o in report["results"] for r in o.get("results", []) if r.get("requires_reparse")}
            - {
                fid
                for o in report["results"]
                if o["status"] == "success"
                for overwrite in o.get("overwrite_targets", [])
                for fid in overwrite["file_ids"]
            }
        )
        save_report(report_path, report)
        print(
            f"[结束] status={report['status']} reparse={len(report['reparse_file_ids'])} pending={report['pending']} 报告={report_path.resolve()}"
        )
    return exit_code


async def run(args: argparse.Namespace, *, backend: Backend | None = None) -> int:
    backend = backend or Backend()
    tenant_id = resolve_tenant(args, bool(settings.multi_tenant.enabled))
    run_id = uuid.uuid4().hex
    report_path = args.report_dir / f"move-{run_id}.json"
    with _tenant_scope(tenant_id):
        discovery = await backend.load(tenant_id, folder_name=args.folder_name, metadata_only=True)
        plan = Plan(department_count=len(discovery.spaces))
        for source in sorted(discovery.spaces, key=lambda s: s.id):
            current = build_plan(
                await backend.load(tenant_id, folder_name=args.folder_name, source_space_id=source.id), args.folder_name
            )
            plan.candidates.extend(current.candidates)
            plan.skipped.extend(current.skipped)
            plan.matched_space_count += current.matched_space_count
        # 跨来源库同名关系在分库加载完成后一次建立, 不反复遍历全量文件。
        reserved, by_unit = {}, {}
        for candidate in plan.candidates:
            names = {(candidate.owner.user_id, candidate.folder_names, f.file_name) for f in candidate.files}
            replaced = {reserved[n] for n in names if n in reserved}
            candidate.replaces_planned_unit_ids = tuple(sorted(replaced))
            for previous in replaced:
                for name in by_unit.pop(previous, set()):
                    reserved.pop(name, None)
            reserved.update(dict.fromkeys(names, candidate.unit_id))
            by_unit[candidate.unit_id] = names
        report = {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "mode": "apply" if args.apply else "dry-run",
            "status": "preview",
            "department_count": plan.department_count,
            "matched_space_count": plan.matched_space_count,
            "planned": [c.preview() for c in plan.candidates],
            "skipped": plan.skipped,
            "pending": len(plan.candidates),
            "results": [],
        }
        save_report(report_path, report)
        print(
            f"部门库={plan.department_count} 命中={plan.matched_space_count} 单元={len(plan.candidates)} 跳过={len(plan.skipped)} 报告={report_path.resolve()}"
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
        logger.exception("迁移中止，请核对报告和操作记录")
        return 2


if __name__ == "__main__":
    sys.exit(main())
