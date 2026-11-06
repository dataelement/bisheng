"""Operational, global task facts. No dispatch, authorization or mutation."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.knowledge.domain.repositories.unification_inventory_repository import InventoryPage


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"migration_tasks_{reason}")


def task_digest(value):
    def scalar(item):
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        raise TypeError("unsupported task scalar")

    try:
        raw = json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=scalar
        )
        return hashlib.sha256(raw.encode()).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise KnowledgeOperationPlanConflictError(reason="migration_tasks_invalid_original_value") from error


def _scope(session):
    tenant = get_current_tenant_id()
    if (
        not isinstance(session, AsyncSession)
        or not session.in_transaction()
        or type(tenant) is not int
        or tenant <= 0
        or is_tenant_filter_bypassed()
    ):
        _blocked("native_transaction_required")


@dataclass(frozen=True, slots=True)
class TaskFact:
    tenant_id: int
    task_kind: str
    task_id: str
    space_id: int | None
    file_id: int | None
    document_id: int | None
    version_id: int | None
    state: str
    configuration_digest: str
    record_digest: str


@dataclass(frozen=True, slots=True)
class QueuedFileFact:
    file_id: int
    exists: bool
    tenant_id: int | None
    space_id: int | None
    space_exists: bool
    file_type: int | None
    status: int | None
    document_id: int | None
    version_id: int | None
    configuration_digest: str
    record_digest: str


class UnificationTaskRepository:
    @staticmethod
    async def _read(session, query):
        _scope(session)
        # These explicit operational facts must also expose foreign/orphan rows;
        # the caller checks every real tenant against the complete run set.
        with session.no_autoflush, bypass_tenant_filter():
            try:
                return tuple((await session.execute(query)).mappings())
            except (ValueError, TypeError) as error:
                raise KnowledgeOperationPlanConflictError(reason="migration_tasks_invalid_original_value") from error

    async def _page(self, session, model, kind, configuration, after_id, limit):
        _scope(session)
        if (
            type(limit) is not int
            or not 1 <= limit <= 200
            or (
                after_id is not None
                and (type(after_id) is not str or not after_id or len(after_id) > 36 or "\x00" in after_id)
            )
        ):
            _blocked("invalid_seek")
        table = model.__table__
        query = select(*table.c)
        if model is KnowledgeProcessingItem:
            parent = KnowledgeProcessingJob.__table__.alias("task_parent")
            query = select(
                *table.c, parent.c.id.label("parent_id"), parent.c.tenant_id.label("parent_tenant")
            ).outerjoin(parent, parent.c.id == table.c.job_id)
        if after_id is not None:
            query = query.where(table.c.id > after_id)
        rows = await self._read(session, query.order_by(table.c.id).limit(limit + 1))
        facts = []
        for row in rows[:limit]:
            if (
                type(row["tenant_id"]) is not int
                or row["tenant_id"] <= 0
                or type(row["id"]) is not str
                or not row["id"]
                or type(row["state"]) is not str
                or not row["state"]
            ):
                _blocked("invalid_task_identity")
            if model is KnowledgeProcessingItem and (
                row["parent_id"] is None or row["parent_tenant"] != row["tenant_id"]
            ):
                _blocked("item_parent_invalid")
            facts.append(
                TaskFact(
                    row["tenant_id"],
                    kind,
                    row["id"],
                    row["expected_space_id"] if model is KnowledgeProcessingItem else row["space_id"],
                    row.get("file_id"),
                    row.get("document_id"),
                    row.get("version_id"),
                    row["state"],
                    task_digest({name: row[name] for name in configuration}),
                    task_digest(dict(row)),
                )
            )
        return InventoryPage(tuple(facts), rows[limit - 1]["id"] if len(rows) > limit else None)

    async def alist_jobs(self, session, *, after_id=None, limit=200):
        return await self._page(
            session,
            KnowledgeProcessingJob,
            "processing_job",
            (
                "kind",
                "actor_reference",
                "parameters",
                "scope_manifest",
                "request_hash",
                "accepted_model_config_revision",
                "expected_model_config_revision",
                "expected_index_generation",
                "space_config_version",
            ),
            after_id,
            limit,
        )

    async def alist_items(self, session, *, after_id=None, limit=200):
        return await self._page(session, KnowledgeProcessingItem, "item", ("processing_snapshot",), after_id, limit)

    async def alist_delete_jobs(self, session, *, after_id=None, limit=200):
        return await self._page(session, KnowledgeSpaceDeleteJob, "delete_job", ("manifest",), after_id, limit)

    async def aget_file_facts(self, session, *, file_ids: tuple[int, ...]):
        _scope(session)
        if (
            type(file_ids) is not tuple
            or len(file_ids) > 200
            or any(type(ident) is not int or ident <= 0 for ident in file_ids)
        ):
            _blocked("invalid_file_batch")
        ids = tuple(dict.fromkeys(file_ids))
        if not ids:
            return ()
        file, space = KnowledgeFile.__table__.alias("queued_file"), Knowledge.__table__.alias("queued_space")
        original = await self._read(
            session,
            select(
                file.c.id,
                file.c.tenant_id,
                file.c.knowledge_id,
                file.c.file_type,
                file.c.status,
                file.c.split_rule,
                file.c.update_time,
                space.c.id.label("space_exists"),
                space.c.tenant_id.label("space_tenant"),
            )
            .outerjoin(space, space.c.id == file.c.knowledge_id)
            .where(file.c.id.in_(ids)),
        )
        files = {row["id"]: row for row in original}
        version = KnowledgeDocumentVersion.__table__
        counts = await self._read(
            session,
            select(
                version.c.knowledge_file_id,
                func.count().label("count"),
                func.min(version.c.id).label("version_id"),
            )
            .where(version.c.knowledge_file_id.in_(ids))
            .group_by(version.c.knowledge_file_id),
        )
        if any(row["count"] != 1 or row["knowledge_file_id"] not in files for row in counts):
            _blocked("file_version_duplicate_or_dangling")
        document, doc_space = (
            KnowledgeDocument.__table__.alias("queued_document"),
            Knowledge.__table__.alias("queued_document_space"),
        )
        primary = version.alias("queued_primary")
        primary_file = KnowledgeFile.__table__.alias("queued_primary_file")
        versions = (
            await self._read(
                session,
                select(
                    version.c.id,
                    version.c.document_id,
                    version.c.knowledge_file_id,
                    version.c.version_no,
                    version.c.is_primary,
                    document.c.id.label("document_exists"),
                    document.c.knowledge_id.label("document_space"),
                    document.c.primary_version_id,
                    doc_space.c.tenant_id.label("document_tenant"),
                    primary.c.document_id.label("primary_document"),
                    primary.c.is_primary.label("primary_flag"),
                    primary_file.c.id.label("primary_file_exists"),
                    primary_file.c.knowledge_id.label("primary_space"),
                    primary_file.c.tenant_id.label("primary_tenant"),
                    primary_file.c.file_type.label("primary_file_type"),
                )
                .outerjoin(document, document.c.id == version.c.document_id)
                .outerjoin(doc_space, doc_space.c.id == document.c.knowledge_id)
                .outerjoin(primary, primary.c.id == document.c.primary_version_id)
                .outerjoin(primary_file, primary_file.c.id == primary.c.knowledge_file_id)
                .where(version.c.id.in_(tuple(row["version_id"] for row in counts))),
            )
            if counts
            else ()
        )
        by_file = {}
        for row in versions:
            actual = files[row["knowledge_file_id"]]
            if (
                row["document_exists"] is None
                or row["document_space"] != actual["knowledge_id"]
                or row["document_tenant"] != actual["tenant_id"]
                or actual["file_type"] != 1
                or row["version_no"] <= 0
                or row["primary_version_id"] is None
                or row["primary_document"] != row["document_id"]
                or row["primary_flag"] is not True
                or row["primary_file_exists"] is None
                or row["primary_space"] != actual["knowledge_id"]
                or row["primary_tenant"] != actual["tenant_id"]
                or row["primary_file_type"] != 1
                or row["is_primary"] != (row["id"] == row["primary_version_id"])
            ):
                _blocked("file_version_chain_invalid")
            by_file[row["knowledge_file_id"]] = row
        result = []
        for ident in ids:
            row, link = files.get(ident), by_file.get(ident)
            if row is None:
                result.append(
                    QueuedFileFact(
                        ident,
                        False,
                        None,
                        None,
                        False,
                        None,
                        None,
                        None,
                        None,
                        task_digest(None),
                        task_digest({"file_id": ident, "exists": False}),
                    )
                )
                continue
            if row["space_exists"] is not None and row["space_tenant"] != row["tenant_id"]:
                _blocked("file_space_tenant_mismatch")
            result.append(
                QueuedFileFact(
                    ident,
                    True,
                    row["tenant_id"],
                    row["knowledge_id"],
                    row["space_exists"] is not None,
                    row["file_type"],
                    row["status"],
                    link["document_id"] if link else None,
                    link["id"] if link else None,
                    task_digest(row["split_rule"]),
                    task_digest({"file": dict(row), "version": dict(link) if link else None}),
                )
            )
        return tuple(result)
