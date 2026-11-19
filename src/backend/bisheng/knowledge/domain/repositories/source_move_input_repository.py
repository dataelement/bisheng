"""Protect actual asynchronous move/copy input until the native task ACK."""

from sqlalchemy import and_, func, or_, select

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.processing_job_acceptance import _digest
from bisheng.resource_reference.application.contracts import TransactionIdentity


class SourceMoveInputRepository:
    @staticmethod
    def _context(session, space_id):
        tenant = get_current_tenant_id()
        if (
            type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or type(space_id) is not int
            or space_id <= 0
            or not session.in_transaction()
        ):
            raise ValueError("source move protection requires the caller's concrete native transaction")
        return tenant, TransactionIdentity.capture(session)

    @staticmethod
    def _query(tenant, space_id, after, *, include_copy=True):
        plan, job, item = (
            model.__table__ for model in (KnowledgeOperationPlan, KnowledgeProcessingJob, KnowledgeProcessingItem)
        )
        count = select(func.count()).where(item.c.job_id == job.c.id).correlate(job).scalar_subquery()
        bad = (
            select(item.c.id)
            .where(
                item.c.job_id == job.c.id,
                or_(
                    item.c.tenant_id != tenant,
                    and_(
                        plan.c.operation == "move",
                        or_(item.c.state != "succeeded", item.c.step != "move_source_cleaned"),
                    ),
                    and_(plan.c.operation == "space_copy", item.c.step.notin_(("copy_input_ready", "copy_completed"))),
                ),
            )
            .correlate(job, plan)
            .exists()
        )
        query = (
            select(
                plan.c.id,
                plan.c.operation,
                job.c.id.label("job_id"),
                job.c.kind,
                job.c.state,
                job.c.space_id,
                job.c.total_count,
                job.c.succeeded_count,
                job.c.failed_count,
                job.c.pending_count,
                job.c.move_logical_marker.is_not(None).label("logical_done"),
                count.label("item_count"),
                bad.label("bad_item"),
                select(Knowledge.__table__.c.id)
                .where(
                    Knowledge.__table__.c.id == job.c.space_id,
                    Knowledge.__table__.c.tenant_id == tenant,
                )
                .correlate(job)
                .exists()
                .label("destination_exists"),
            )
            .select_from(plan.outerjoin(job, and_(job.c.id == plan.c.operation_id, job.c.tenant_id == tenant)))
            .where(
                plan.c.tenant_id == tenant,
                plan.c.space_id == space_id,
                plan.c.operation.in_(("move", "space_copy") if include_copy else ("move",)),
                plan.c.consumed_at.is_not(None),
            )
            .order_by(plan.c.id)
            .limit(200)
        )
        return query if after is None else query.where(plan.c.id > after)

    @staticmethod
    def _check(row, space_id):
        if (
            row["operation"] == "space_copy"
            and row["kind"] == "space_copy"
            and row["space_id"] != space_id
            and row["state"] in {"failed", "partial_failed", "obsolete"}
            and not row["destination_exists"]
        ):
            # A removed target cannot resume its failed copy or consume input.
            return
        if (
            row["operation"] == "space_copy"
            and row["job_id"] is not None
            and row["kind"] == "space_copy"
            and row["space_id"] != space_id
            and not row["bad_item"]
            and row["total_count"] == row["item_count"]
            and (row["total_count"] > 0 or row["state"] == "succeeded")
        ):
            return
        if (
            row["job_id"] is None
            or row["kind"] != ("space_copy" if row["operation"] == "space_copy" else "move_index")
            or row["space_id"] == space_id
            or row["state"] != "succeeded"
            or (row["operation"] == "move" and not row["logical_done"])
            or row["bad_item"]
            or row["failed_count"] != 0
            or row["pending_count"] != 0
            or type(row["total_count"]) is not int
            or row["total_count"] < 0
            or row["total_count"] != row["item_count"]
            or row["succeeded_count"] != row["total_count"]
        ):
            raise KnowledgeProcessingConflictError(reason="source_space_move_input_required")

    @staticmethod
    def _current(session, tenant, transaction):
        transaction.assert_current(session)
        if type(get_current_tenant_id()) is not int or get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
            raise KnowledgeProcessingConflictError(reason="source_space_move_context_changed")

    async def _file_outside_move(self, session, tenant, space_id, row, file_id):
        """Only narrow an unsettled move using its frozen logical scope AND actual index items."""
        if row["job_id"] is None or row["kind"] != "move_index" or row["space_id"] == space_id:
            return False
        plan, job, item = (
            m.__table__ for m in (KnowledgeOperationPlan, KnowledgeProcessingJob, KnowledgeProcessingItem)
        )
        with session.no_autoflush, strict_tenant_filter():
            bound = (
                await session.execute(
                    select(plan.c.parameters, plan.c.target_manifest, job.c.parameters, job.c.scope_manifest)
                    .select_from(plan.join(job, and_(job.c.id == plan.c.operation_id, job.c.tenant_id == tenant)))
                    .where(
                        plan.c.tenant_id == tenant,
                        plan.c.id == row["id"],
                        plan.c.space_id == space_id,
                        job.c.id == row["job_id"],
                        job.c.space_id == row["space_id"],
                    )
                )
            ).one_or_none()
            if bound is None:
                return False
            scope, targets, acceptance, manifest = bound
            if not isinstance(acceptance, dict) or not isinstance(scope, dict) or not isinstance(manifest, list):
                return False
            if (
                acceptance.get("scope_digest") != _digest(scope)
                or acceptance.get("confirmation_id") != row["id"]
                or acceptance.get("operation_id") != row["job_id"]
                or acceptance.get("move_schema") != 1
                or scope.get("move_schema") != 1
                or acceptance.get("source_space_id") != space_id
                or acceptance.get("destination_space_id") != row["space_id"]
                or acceptance.get("index_item_count") != len(manifest)
                or scope.get("source_space_id") != space_id
                or scope.get("destination_space_id") != row["space_id"]
                or not isinstance(scope.get("files"), list)
                or not scope["files"]
                or len(scope["files"]) != acceptance.get("logical_file_count")
                or len(manifest) != row["total_count"]
                or len(manifest) != row["item_count"]
            ):
                return False
            ids = [entry.get("file_id") if isinstance(entry, dict) else None for entry in scope["files"]]
            if any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids) or file_id in ids:
                return False
            logical_ids = set(ids)
            if not isinstance(targets, list) or not isinstance(scope.get("leaves"), list):
                return False
            if len(targets) != len(scope["leaves"]) or any(not isinstance(leaf, dict) for leaf in scope["leaves"]):
                return False
            # The plan manifest is frozen separately from the expanded logical files.
            # Do not rely on one representation if the other contradicts it.
            frozen = {_digest(target) for target in targets}
            leaves = {_digest(leaf.get("target")) for leaf in scope["leaves"]}
            if (
                frozen != leaves
                or len(frozen) != len(targets)
                or any(
                    not isinstance(target, dict)
                    or type(target.get("file_id")) is not int
                    or target["file_id"] not in logical_ids
                    for target in targets
                )
            ):
                return False
            # Logical scope includes skipped versions and folder descendants. An empty
            # or truncated physical ledger alone cannot prove that an input is unrelated.
            projected = set()
            for entry in manifest:
                if not isinstance(entry, dict) or entry.get("expected_space_id") != row["space_id"]:
                    return False
                key = tuple(entry.get(k) for k in ("file_id", "document_id", "version_id"))
                if not all(type(i) is int and i > 0 for i in key) or key in projected or key[0] not in ids:
                    return False
                projected.add(key)
            actual = await session.execute(
                select(item.c.file_id, item.c.document_id, item.c.version_id).where(
                    item.c.job_id == row["job_id"],
                    item.c.tenant_id == tenant,
                    item.c.expected_space_id == row["space_id"],
                )
            )
            return set(actual) == projected

    async def arequire_released(self, session, *, space_id, include_copy=True, file_id=None):
        if file_id is not None and (include_copy or type(file_id) is not int or file_id <= 0):
            raise ValueError("file input protection requires a concrete move-only target")
        tenant, transaction = self._context(session, space_id)
        after = None
        while True:
            with session.no_autoflush, strict_tenant_filter():
                page = (
                    (await session.execute(self._query(tenant, space_id, after, include_copy=include_copy)))
                    .mappings()
                    .all()
                )
            self._current(session, tenant, transaction)
            for row in page:
                try:
                    self._check(row, space_id)
                except KnowledgeProcessingConflictError:
                    if file_id is None:
                        raise
                    outside = await self._file_outside_move(session, tenant, space_id, row, file_id)
                    self._current(session, tenant, transaction)
                    if not outside:
                        raise KnowledgeProcessingConflictError(reason="source_file_move_input_required") from None
            if len(page) < 200:
                return
            after = page[-1]["id"]

    async def ablocking_job_ids(self, session, *, space_id, include_copy=True):
        """Jobs whose source input this space must keep. Same rule as ``arequire_released``."""
        tenant, transaction = self._context(session, space_id)
        after, found = None, []
        while True:
            with session.no_autoflush, strict_tenant_filter():
                page = (
                    (await session.execute(self._query(tenant, space_id, after, include_copy=include_copy)))
                    .mappings()
                    .all()
                )
            self._current(session, tenant, transaction)
            for row in page:
                try:
                    self._check(row, space_id)
                except KnowledgeProcessingConflictError:
                    if row["job_id"] is not None:
                        found.append(row["job_id"])
            if len(page) < 200:
                return tuple(dict.fromkeys(found))
            after = page[-1]["id"]

    def require_released(self, session, *, space_id):
        tenant, transaction = self._context(session, space_id)
        after = None
        while True:
            with session.no_autoflush, strict_tenant_filter():
                page = session.execute(self._query(tenant, space_id, after)).mappings().all()
            self._current(session, tenant, transaction)
            for row in page:
                self._check(row, space_id)
            if len(page) < 200:
                return
            after = page[-1]["id"]
