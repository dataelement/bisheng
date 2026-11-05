"""Read-only workflow column projections in the caller's active transaction.

Candidate reads retain production C3 visibility. They never discover foreign
roots through bypass, load managed business entities, or own transactions.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.database.models.flow import Flow, FlowType
from bisheng.database.models.flow_version import FlowVersion
from bisheng.knowledge.domain.models.knowledge import Knowledge


@dataclass(frozen=True, slots=True)
class WorkflowRootReadFact:
    id: str
    tenant_id: int
    user_id: int | None
    flow_type: int
    status: int
    is_delete: int
    data_json: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class WorkflowVersionReadFact:
    id: int
    flow_id: str
    tenant_id: int
    flow_type: int | None
    is_current: int
    is_delete: int
    data_json: str = field(repr=False)


class WorkflowReferenceSourceRepository:
    @staticmethod
    def _context(session: AsyncSession) -> None:
        current = get_current_tenant_id()
        if is_tenant_filter_bypassed() or type(current) is not int or current <= 0:
            raise ResourceReferenceInvalidError(reason="source_tenant_context_missing")
        if not session.in_transaction():
            raise ResourceReferenceInvalidError(reason="source_read_transaction_required")

    @classmethod
    async def aget_root(cls, session: AsyncSession, root_id: str, *, for_update: bool = False) -> WorkflowRootReadFact:
        cls._context(session)
        query = select(
            Flow.id, Flow.tenant_id, Flow.user_id, Flow.flow_type, Flow.status, Flow.is_delete, Flow.data
        ).where(Flow.id == root_id, Flow.flow_type == FlowType.WORKFLOW.value, Flow.is_delete == 0)
        if for_update:
            query = query.with_for_update()
        with session.no_autoflush:
            row = (await session.execute(query)).one_or_none()
        if row is None or type(row.tenant_id) is not int or row.tenant_id <= 0:
            raise NotFoundError()
        return WorkflowRootReadFact(*row[:6], json.dumps(row.data, ensure_ascii=False, allow_nan=False))

    @classmethod
    async def aget_version(
        cls,
        session: AsyncSession,
        root: WorkflowRootReadFact,
        version_id: int | None,
        *,
        for_update: bool = False,
    ) -> WorkflowVersionReadFact:
        cls._context(session)
        query = select(
            FlowVersion.id,
            FlowVersion.flow_id,
            FlowVersion.tenant_id,
            FlowVersion.flow_type,
            FlowVersion.is_current,
            FlowVersion.is_delete,
            FlowVersion.data,
        ).where(FlowVersion.flow_id == root.id, FlowVersion.is_delete == 0)
        query = (
            query.where(FlowVersion.is_current == 1)
            if version_id is None
            else query.where(FlowVersion.id == version_id)
        )
        if for_update:
            query = query.with_for_update()
        with session.no_autoflush:
            rows = (await session.execute(query)).all()
        if not rows:
            raise NotFoundError()
        if len(rows) != 1:
            raise ReferenceCoverageNotReadyError(reason="workflow_current_version_ambiguous")
        row = rows[0]
        if row.tenant_id != root.tenant_id:
            raise ReferenceCoverageNotReadyError(reason="workflow_version_tenant_mismatch")
        return WorkflowVersionReadFact(*row[:6], json.dumps(row.data, ensure_ascii=False, allow_nan=False))

    @classmethod
    async def aget_knowledge_resource_type(
        cls, session: AsyncSession, target_id: int, *, for_update: bool = False
    ) -> str:
        cls._context(session)
        query = select(Knowledge.type).where(Knowledge.id == target_id)
        if for_update:
            query = query.with_for_update()
        with session.no_autoflush:
            kind = await session.scalar(query)
        if kind not in {0, 1, 3}:
            raise ResourceReferenceInvalidError(reason="preview_knowledge_unavailable")
        return "knowledge_space" if kind == 3 else "knowledge_library"
