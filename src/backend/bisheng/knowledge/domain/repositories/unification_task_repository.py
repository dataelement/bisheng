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
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, QAKnowledge
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


@dataclass(frozen=True, slots=True)
class BrokerTargetFact:
    """Execution target facts; J1 existence requires its real Root as well.

    The separate all-state TaskFact stream retains every physical ledger row.
    A delete ledger remains authoritative after its Root was formally deleted.
    """

    target_id: int | str
    exists: bool
    tenant_id: int | None
    space_id: int | None
    knowledge_type: int | None
    revision: int | None
    index_generation: str | None
    operation_id: str | None
    state: str | int | None
    kind: str
    record_digest: str


class UnificationTaskRepository:
    @staticmethod
    def _validate_delete_phase(row):
        from bisheng.knowledge.domain.repositories.knowledge_deletion_execution_repository import OPERATIONS

        operation, phase = row["operation_type"], row["business_phase"]
        if operation is None and phase is None:
            return
        if operation not in OPERATIONS or phase != "finalized":
            raise KnowledgeOperationPlanConflictError(
                reason="migration_tasks_business_delete_not_finalized", job_id=row["id"], business_phase=phase
            )

    async def avalidate_migration_idle(self, session):
        """Check committed business deletion phases/tombstones, never a queue.

        Stopping all services does not finalize a prepared SQL deletion. These
        facts prevent migration of half-completed business cutovers; they say
        nothing about Celery workers, message counts or consumption activity.
        """
        from sqlalchemy import and_, or_

        from bisheng.knowledge.domain.repositories.knowledge_deletion_execution_repository import OPERATIONS
        from bisheng.resource_reference.application.contracts import TransactionIdentity
        from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

        _scope(session)
        tenant, transaction = get_current_tenant_id(), TransactionIdentity.capture(session)

        def current():
            _scope(session)
            transaction.assert_current(session)
            if get_current_tenant_id() != tenant:
                _blocked("migration_idle_context_changed")

        table = KnowledgeSpaceDeleteJob.__table__
        rows = await self._read(
            session,
            select(table.c.id, table.c.operation_type, table.c.business_phase)
            .where(
                or_(
                    and_(table.c.operation_type.is_(None), table.c.business_phase.is_not(None)),
                    and_(
                        table.c.operation_type.is_not(None),
                        or_(
                            table.c.operation_type.not_in(tuple(OPERATIONS)),
                            table.c.business_phase.is_(None),
                            table.c.business_phase != "finalized",
                        ),
                    ),
                )
            )
            .order_by(table.c.id)
            .limit(1),
        )
        current()
        for row in rows:
            self._validate_delete_phase(row)
        tombstones = ResourceReferenceTombstone.__table__
        deleting = await self._read(session, select(tombstones.c.id).where(tombstones.c.stage == "deleting").limit(1))
        current()
        if deleting:
            _blocked("target_deletion_not_finalized")

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
            if model is KnowledgeSpaceDeleteJob:
                self._validate_delete_phase(row)
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
            configuration_digest = task_digest({name: row[name] for name in configuration})
            # Bind the full configuration once, then compose its digest with
            # the remaining original state; large manifests are not re-encoded.
            state = {name: value for name, value in row.items() if name not in configuration}
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
                    configuration_digest,
                    task_digest({"configuration_digest": configuration_digest, "state": state}),
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

    async def _broker_targets(self, session, ids, kind):
        _scope(session)
        numeric = kind in {"space", "qa"}
        if (
            type(ids) is not tuple
            or len(ids) > 200
            or any(
                (type(ident) is not int or ident <= 0)
                if numeric
                else (type(ident) is not str or not ident or len(ident) > 36 or "\x00" in ident)
                for ident in ids
            )
        ):
            _blocked("invalid_broker_target_batch")
        ids = tuple(dict.fromkeys(ids))
        if not ids:
            return ()
        model, names = {
            "space": (
                Knowledge,
                (
                    "id",
                    "tenant_id",
                    "type",
                    "state",
                    "model_config_revision",
                    "index_generation",
                    "model_transition",
                    "update_time",
                ),
            ),
            "job": (
                KnowledgeProcessingJob,
                (
                    "id",
                    "tenant_id",
                    "space_id",
                    "kind",
                    "state",
                    "revision",
                    "request_hash",
                    "expected_model_config_revision",
                    "accepted_model_config_revision",
                    "expected_index_generation",
                    "claim_generation",
                    "update_time",
                ),
            ),
            "delete_job": (
                KnowledgeSpaceDeleteJob,
                ("id", "tenant_id", "space_id", "state", "attempts", "completed_steps", "lease_until", "update_time"),
            ),
            "qa": (QAKnowledge, ("id", "tenant_id", "knowledge_id", "source", "status", "update_time")),
        }[kind]
        table = model.__table__.alias("broker_target")
        query = select(*(table.c[name] for name in names)).where(table.c.id.in_(ids))
        if kind in {"qa", "job", "delete_job"}:
            space = Knowledge.__table__.alias("broker_target_space")
            query = query.add_columns(
                space.c.id.label("parent_id"),
                space.c.tenant_id.label("parent_tenant"),
                space.c.type.label("knowledge_type"),
            ).outerjoin(space, space.c.id == (table.c.knowledge_id if kind == "qa" else table.c.space_id))
        rows = {row["id"]: row for row in await self._read(session, query)}
        result = []
        for ident in ids:
            row = rows.get(ident)
            if row is not None:
                if type(row["tenant_id"]) is not int or row["tenant_id"] <= 0:
                    _blocked("broker_target_tenant_invalid")
                if (
                    kind in {"job", "delete_job"}
                    and row["parent_id"] is not None
                    and row["parent_tenant"] != row["tenant_id"]
                ):
                    _blocked("broker_ledger_parent_invalid")
            if row is None or (kind == "job" and row["parent_id"] is None):
                result.append(
                    BrokerTargetFact(
                        ident,
                        False,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        kind,
                        task_digest(
                            {
                                "kind": kind,
                                "id": ident,
                                "exists": False,
                                "ledger": dict(row) if row is not None else None,
                            }
                        ),
                    )
                )
                continue
            if kind == "qa" and (row["parent_id"] is None or row["parent_tenant"] != row["tenant_id"]):
                _blocked("qa_parent_invalid")
            transition = row.get("model_transition")
            if transition is not None and type(transition) is not dict:
                _blocked("broker_space_transition_invalid")
            operation = transition.get("operation_id") if transition else None
            if operation is not None and (type(operation) is not str or not operation):
                _blocked("broker_space_transition_invalid")
            result.append(
                BrokerTargetFact(
                    ident,
                    True,
                    row["tenant_id"],
                    row["id"] if kind == "space" else row["knowledge_id"] if kind == "qa" else row["space_id"],
                    row["type"] if kind == "space" else row.get("knowledge_type"),
                    row.get("model_config_revision") if kind == "space" else row.get("revision"),
                    row.get("index_generation") if kind == "space" else row.get("expected_index_generation"),
                    operation,
                    row.get("state") if kind != "qa" else str(row["status"]),
                    row.get("kind", kind),
                    task_digest(dict(row)),
                )
            )
        return tuple(result)

    async def aget_space_facts(self, session, *, space_ids: tuple[int, ...]):
        return await self._broker_targets(session, space_ids, "space")

    async def aget_job_facts(self, session, *, job_ids: tuple[str, ...]):
        return await self._broker_targets(session, job_ids, "job")

    async def aget_delete_job_facts(self, session, *, job_ids: tuple[str, ...]):
        return await self._broker_targets(session, job_ids, "delete_job")

    async def aget_qa_facts(self, session, *, qa_ids: tuple[int, ...]):
        return await self._broker_targets(session, qa_ids, "qa")
