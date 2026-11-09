"""Receipt-bound logical ready facts, written in the issuer's current transaction."""

import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import select, update

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.move_cutover_repository import MoveLogicalReceipt
from bisheng.knowledge.domain.repositories.move_job_repository import MoveJobRepository
from bisheng.knowledge.domain.schemas.processing_job import JobAccepted
from bisheng.knowledge.domain.schemas.processing_job_acceptance import JobLease, _digest

_JOB_KEYS = frozenset(
    (
        "move_schema job_id plan_id request_hash after_scope_digest projection_evidence_digest "
        "index_item_count ready_claim_generation"
    ).split()
)
_TARGET = ("file_id", "document_id", "version_id", "expected_space_id", "expected_parent_id")
_ITEM_KEYS = frozenset(("move_schema", "job_id", "job_marker_digest", "processing_snapshot_digest", *_TARGET))


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _fail(reason):
    raise KnowledgeOperationPlanConflictError(reason=reason)


def _checksum(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


class MoveJobReadyRepository:
    def __init__(self, *, move_jobs: MoveJobRepository, clock=_now):
        if not isinstance(move_jobs, MoveJobRepository):
            raise TypeError("move ready requires the original acceptance repository and issuer")
        self.move_jobs, self.cutover, self.clock = move_jobs, move_jobs.cutover, clock

    @staticmethod
    def require_job_ready(job):
        if get_current_tenant_id() != job.tenant_id or is_tenant_filter_bypassed():
            _fail("move_ready_context_changed")
        marker = job.move_logical_marker
        p = job.parameters
        if (
            type(marker) is not dict
            or set(marker) != _JOB_KEYS
            or not isinstance(p, Mapping)
            or type(marker["move_schema"]) is not int
            or marker["move_schema"] != 1
            or marker["job_id"] != job.id
            or marker["plan_id"] != p.get("confirmation_id")
            or marker["request_hash"] != job.request_hash
            or any(
                not _checksum(marker[name])
                for name in ("request_hash", "after_scope_digest", "projection_evidence_digest")
            )
            or type(marker["index_item_count"]) is not int
            or marker["index_item_count"] < 0
            or marker["index_item_count"] != job.total_count
            or marker["index_item_count"] != p.get("index_item_count")
            or type(marker["ready_claim_generation"]) is not int
            or marker["ready_claim_generation"] <= 0
            or marker["ready_claim_generation"] > job.claim_generation
        ):
            _fail("move_logical_ready_required")
        return marker

    @staticmethod
    def _item_marker(job_id, marker, target):
        return {
            "move_schema": 1,
            "job_id": job_id,
            "job_marker_digest": _digest(marker),
            **{name: target[name] for name in _TARGET},
            "processing_snapshot_digest": target["processing_snapshot_digest"],
        }

    def require_item_ready(self, job, item):
        marker = self.require_job_ready(job)
        stored = item.checkpoint.get("logical_move") if isinstance(item.checkpoint, Mapping) else None
        if type(stored) is not dict or set(stored) != _ITEM_KEYS:
            _fail("move_item_ready_required")
        expected = {name: getattr(item, name) for name in _TARGET}
        expected["processing_snapshot_digest"] = _digest(item.processing_snapshot)
        if _digest(stored) != _digest(self._item_marker(job.id, marker, expected)):
            _fail("move_item_ready_changed")

    @staticmethod
    def preserve_checkpoint(item, incoming):
        protected = item.checkpoint["logical_move"]
        if "logical_move" in incoming and _digest(incoming["logical_move"]) != _digest(protected):
            _fail("move_item_ready_is_private")
        incoming["logical_move"] = deepcopy(protected)
        return incoming

    async def _verified_job(self, session, receipt, lease):
        native = await self.cutover._job(session, receipt.job_id, lease)
        if (
            receipt.claim_generation != lease.claim_generation
            or receipt.lease_token != lease.lease_token
            or receipt.request_hash != native["request_hash"]
        ):
            _fail("move_ready_lease_changed")
        table = KnowledgeProcessingJob.__table__
        rows = await self.move_jobs._rows(
            session,
            select(table.c.idempotency_key, table.c.parameters, table.c.actor_user_id, table.c.actor_reference).where(
                table.c.id == receipt.job_id
            ),
        )
        if len(rows) != 1:
            _fail("move_ready_job_missing")
        row, p = rows[0], rows[0]["parameters"]
        result = await self.move_jobs.aget_move_request(
            session,
            source_space_id=p["source_space_id"],
            confirmation_id=p["confirmation_id"],
            plan_digest=p["plan_digest"],
            idempotency_key=row["idempotency_key"],
            actor_user_id=row["actor_user_id"],
            actor_reference=row["actor_reference"],
        )
        if result is None:
            _fail("move_ready_acceptance_missing")
        job = result.job
        if (
            receipt.plan_id != p["confirmation_id"]
            or receipt.request_hash != job.request_hash
            or receipt.index_item_count != job.total_count
            or receipt._prepared.plan_digest != p["plan_digest"]
            or receipt._prepared.scope.scope_digest != p["scope_digest"]
            or receipt._prepared.scope.changes_digest != p["changes_digest"]
        ):
            _fail("move_ready_acceptance_changed")
        return job

    async def _item_pages(self, session, job):
        root, item = KnowledgeProcessingJob.__table__, KnowledgeProcessingItem.__table__
        fields = ("id", "tenant_id", "job_id", *_TARGET, "processing_snapshot", "checkpoint")
        after = None
        while True:
            # Anchor raw child facts on the already verified Job. A foreign child
            # must be rejected, rather than becoming invisible through C3.
            query = (
                select(root.c.tenant_id.label("root_tenant_id"), item.c.id, item.c.tenant_id)
                .select_from(root.join(item, item.c.job_id == root.c.id))
                .where(root.c.id == job.id)
            )
            if after is not None:
                query = query.where(item.c.id > after)
            ids = await self.move_jobs._rows(session, query.order_by(item.c.id).limit(200))
            if not ids:
                return
            if any(row["root_tenant_id"] != job.tenant_id or row["tenant_id"] != job.tenant_id for row in ids):
                _fail("move_ready_item_tenant")
            rows = await self.move_jobs._rows(
                session,
                select(*(item.c[name] for name in fields))
                .where(item.c.id.in_([row["id"] for row in ids]))
                .order_by(item.c.id)
                .limit(200)
                .with_for_update(),
            )
            if [row["id"] for row in rows] != [row["id"] for row in ids]:
                _fail("move_ready_items_changed")
            yield rows
            after = ids[-1]["id"]

    async def amark_move_ready(self, session, *, logical_receipt: MoveLogicalReceipt, lease: JobLease) -> JobAccepted:
        tenant = self.move_jobs._context(session)
        self.cutover._clean(session)
        # Receipt and its prepared/P1 proof are bound to this exact current TX.
        # Starting a SAVEPOINT here would invalidate that original authority.
        self.cutover.assert_logical_current(logical_receipt, session)
        job = await self._verified_job(session, logical_receipt, lease)
        scope = logical_receipt._prepared.scope
        await self.cutover._configuration(session, scope)
        if await self.cutover._position(session, scope) != "after":
            _fail("move_ready_after_required")
        reused = job.move_logical_marker is not None
        if reused:
            marker = self.require_job_ready(job)
            if marker["after_scope_digest"] != logical_receipt.after_scope_digest:
                _fail("move_ready_after_changed")
        else:
            marker = {
                "move_schema": 1,
                "job_id": job.id,
                "plan_id": logical_receipt.plan_id,
                "request_hash": logical_receipt.request_hash,
                "after_scope_digest": logical_receipt.after_scope_digest,
                "projection_evidence_digest": logical_receipt.projection_evidence_digest,
                "index_item_count": logical_receipt.index_item_count,
                "ready_claim_generation": logical_receipt.claim_generation,
            }
            # This detached acceptance object is only a validation input. No Job
            # marker is written until all actual Item markers have been flushed.
            job.move_logical_marker = marker
            self.require_job_ready(job)
        expected = {(row["file_id"], row["version_id"]): row for row in job.scope_manifest}
        if len(expected) != job.total_count:
            _fail("move_ready_scope_incomplete")
        seen = set()
        table = KnowledgeProcessingItem.__table__
        async for rows in self._item_pages(session, job):
            for row in rows:
                key = row["file_id"], row["version_id"]
                target = expected.get(key)
                if (
                    target is None
                    or key in seen
                    or row["tenant_id"] != tenant
                    or row["job_id"] != job.id
                    or any(row[name] != target[name] for name in _TARGET)
                    or _digest(row["processing_snapshot"]) != target["processing_snapshot_digest"]
                    or not isinstance(row["checkpoint"], Mapping)
                ):
                    _fail("move_ready_item_changed")
                seen.add(key)
                item_marker = self._item_marker(job.id, marker, target)
                if reused:
                    if _digest(row["checkpoint"].get("logical_move")) != _digest(item_marker):
                        _fail("move_ready_item_marker_changed")
                    continue
                checkpoint = deepcopy(dict(row["checkpoint"]))
                checkpoint["logical_move"] = item_marker
                if self.move_jobs._context(session) != tenant:
                    _fail("move_ready_context_changed")
                result = await session.execute(
                    update(table)
                    .where(table.c.id == row["id"], table.c.job_id == job.id, table.c.tenant_id == tenant)
                    .values(checkpoint=checkpoint)
                )
                if result.rowcount != 1:
                    _fail("move_ready_item_missing")
            await session.flush()
        if seen != expected.keys():
            _fail("move_ready_scope_incomplete")
        await self.cutover._job(session, job.id, lease)
        self.cutover.assert_logical_current(logical_receipt, session)
        if self.move_jobs._context(session) != tenant:
            _fail("move_ready_context_changed")
        self.cutover.consume_logical(logical_receipt, session)
        if not reused:
            now = self.clock()
            now = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
            values = {
                "move_logical_marker": marker,
                "revision": KnowledgeProcessingJob.revision + 1,
                "update_time": now,
            }
            if not job.total_count:
                values.update(
                    state="succeeded",
                    finished_at=now,
                    pending_dispatch=False,
                    lease_until=None,
                    total_count=0,
                    succeeded_count=0,
                    failed_count=0,
                    pending_count=0,
                )
            result = await session.execute(
                update(KnowledgeProcessingJob.__table__)
                .where(KnowledgeProcessingJob.id == job.id, KnowledgeProcessingJob.tenant_id == tenant)
                .values(**values)
            )
            if result.rowcount != 1:
                _fail("move_ready_job_missing")
            await session.flush()
        return JobAccepted(job_id=job.id, state="succeeded" if not job.total_count else "running", reused=reused)
