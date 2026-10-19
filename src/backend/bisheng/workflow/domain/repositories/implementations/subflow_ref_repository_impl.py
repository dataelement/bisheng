"""SubflowRefRepository implementation."""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.workflow.domain.models.subflow_ref import WorkflowSubflowRef
from bisheng.workflow.domain.repositories.interfaces.subflow_ref_repository import SubflowRefRepository


class SubflowRefRepositoryImpl(BaseRepositoryImpl[WorkflowSubflowRef, int], SubflowRefRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session, WorkflowSubflowRef)

    async def _rows_for_parent(self, parent_flow_id: str) -> list[WorkflowSubflowRef]:
        result = await self.session.exec(
            select(WorkflowSubflowRef).where(WorkflowSubflowRef.parent_flow_id == parent_flow_id)
        )
        return list(result.all())

    async def replace_for_parent(self, parent_flow_id: str, child_flow_ids: list[str]) -> None:
        # Rows are loaded first and deleted one by one: bulk DELETE statements
        # skip the tenant auto-filter, loaded rows have already passed it.
        wanted = list(dict.fromkeys(child_flow_ids))
        existing = await self._rows_for_parent(parent_flow_id)
        existing_ids = {row.child_flow_id for row in existing}
        for row in existing:
            if row.child_flow_id not in wanted:
                await self.session.delete(row)
        for child_flow_id in wanted:
            if child_flow_id not in existing_ids:
                self.session.add(WorkflowSubflowRef(parent_flow_id=parent_flow_id, child_flow_id=child_flow_id))
        await self.session.commit()

    async def delete_for_parent(self, parent_flow_id: str) -> None:
        await self.replace_for_parent(parent_flow_id, [])

    async def list_referrer_ids(self, child_flow_id: str) -> list[str]:
        result = await self.session.exec(
            select(WorkflowSubflowRef.parent_flow_id)
            .where(WorkflowSubflowRef.child_flow_id == child_flow_id)
            .order_by(WorkflowSubflowRef.create_time, WorkflowSubflowRef.id)
        )
        return list(result.all())
