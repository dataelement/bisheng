"""Bounded scalar move item pages; caller owns identity and visibility checks."""

from sqlalchemy import and_, or_, select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.schemas.processing_job import ItemState
from bisheng.resource_reference.application.contracts import TransactionIdentity


class MoveQueryRepository:
    async def alist_items(self, session, *, job_id, after=None, state=None):
        tenant = get_current_tenant_id()
        transaction = TransactionIdentity.capture(session)
        if (
            type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or session.new
            or session.dirty
            or session.deleted
        ):
            raise KnowledgeOperationPlanConflictError(reason="move_query_native_context_required")
        table, job = Item.__table__, Job.__table__
        names = ("id", "tenant_id", "file_id", "document_id", "version_id", "step", "state", "attempt", "error_code")
        query = (
            select(*(table.c[name] for name in names))
            .select_from(Knowledge)
            .join(job, job.c.space_id == Knowledge.id)
            .join(table, table.c.job_id == job.c.id)
            .where(
                Knowledge.tenant_id == tenant, job.c.tenant_id == tenant, job.c.id == job_id, job.c.kind == "move_index"
            )
        )
        if state is not None:
            query = query.where(table.c.state == ItemState(state).value)
        if after is not None:
            file_id, version_id, ident = after
            query = query.where(
                or_(
                    table.c.file_id > file_id,
                    and_(table.c.file_id == file_id, table.c.version_id > version_id),
                    and_(table.c.file_id == file_id, table.c.version_id == version_id, table.c.id > ident),
                )
            )
        query = query.order_by(table.c.file_id, table.c.version_id, table.c.id).limit(200)
        with session.no_autoflush, strict_tenant_filter():
            rows = (await session.execute(query)).mappings().all()
        transaction.assert_current(session)
        if (
            get_current_tenant_id() != tenant
            or is_tenant_filter_bypassed()
            or any(row["tenant_id"] != tenant for row in rows)
        ):
            raise KnowledgeOperationPlanConflictError(reason="move_query_scope_changed")
        return tuple(dict(row) for row in rows)
