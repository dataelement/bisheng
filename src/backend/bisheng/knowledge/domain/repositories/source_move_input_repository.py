"""Protect actual asynchronous move/copy input until the native task ACK."""

from sqlalchemy import and_, case, func, or_, select

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
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
    def _query(tenant, space_id, after):
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
                    item.c.state != "succeeded",
                    item.c.step
                    != case((plan.c.operation == "space_copy", "copy_completed"), else_="move_source_cleaned"),
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
            )
            .select_from(plan.outerjoin(job, and_(job.c.id == plan.c.operation_id, job.c.tenant_id == tenant)))
            .where(
                plan.c.tenant_id == tenant,
                plan.c.space_id == space_id,
                plan.c.operation.in_(("move", "space_copy")),
                plan.c.consumed_at.is_not(None),
            )
            .order_by(plan.c.id)
            .limit(200)
        )
        return query if after is None else query.where(plan.c.id > after)

    @staticmethod
    def _check(row, space_id):
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

    async def arequire_released(self, session, *, space_id):
        tenant, transaction = self._context(session, space_id)
        after = None
        while True:
            with session.no_autoflush, strict_tenant_filter():
                page = (await session.execute(self._query(tenant, space_id, after))).mappings().all()
            self._current(session, tenant, transaction)
            for row in page:
                self._check(row, space_id)
            if len(page) < 200:
                return
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
