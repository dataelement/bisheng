"""Exact creation recovery reads; callers already verify actor and target tenant."""

from sqlalchemy import update
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.database.models.flow import Flow


class CreationRepository:
    @staticmethod
    async def readiness_rows(resource_ids):
        # A negative-only state guard. This never grants resource access or exposes row contents.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return list(
                    (await session.exec(select(Flow).where(Flow.id.in_([str(value) for value in resource_ids])))).all()
                )

    @staticmethod
    async def load(tenant_id, resource_id):
        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            async with get_async_db_session() as session:
                return (
                    await session.exec(
                        select(Flow).where(
                            Flow.tenant_id == tenant_id, Flow.id == str(resource_id), Flow.is_delete == 0
                        )
                    )
                ).first()

    @staticmethod
    async def ready(tenant_id, resource_id):
        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.execute(
                    update(Flow)
                    .where(
                        Flow.tenant_id == tenant_id,
                        Flow.id == str(resource_id),
                        Flow.is_delete == 0,
                        Flow.creation_state == "PENDING",
                    )
                    .values(creation_state="READY")
                )
                if result.rowcount != 1:
                    row = await session.get(Flow, str(resource_id))
                    if row is None or row.tenant_id != tenant_id or row.creation_state != "READY":
                        from bisheng.common.errcode.flow import WorkflowCreationPendingError

                        raise WorkflowCreationPendingError()
                await session.commit()
