"""Legacy form variables retain their parent workflow's verified ownership."""

from sqlmodel import delete, select

from bisheng.common.errcode.flow import WorkFlowInvalidUserInputError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.database import get_async_db_session
from bisheng.database.models.flow import Flow, FlowType, assert_workflow_ready
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.variable_value import Variable


class VariableRepository:
    @staticmethod
    async def parent(flow_id, version_id=None):
        async with get_async_db_session() as session:
            parent = (await session.exec(select(Flow).where(Flow.id == flow_id, Flow.is_delete == 0))).first()
            if parent is None or parent.flow_type != FlowType.WORKFLOW.value:
                raise NotFoundError()
            assert_workflow_ready(parent)
            query = select(FlowVersion).where(
                FlowVersion.flow_id == parent.id, FlowVersion.tenant_id == parent.tenant_id, FlowVersion.is_delete == 0
            )
            query = (
                query.where(FlowVersion.id == version_id)
                if version_id is not None
                else query.where(FlowVersion.is_current == 1)
            )
            version = (await session.exec(query)).first()
            if version is None:
                raise NotFoundError()
            return parent, version

    @staticmethod
    async def by_id(variable_id):
        async with get_async_db_session() as session:
            value = await session.get(Variable, variable_id)
            if value is None:
                raise NotFoundError()
            return value

    @staticmethod
    async def listing(parent, version, node_id, variable_name):
        async with get_async_db_session() as session:
            query = select(Variable).where(
                Variable.tenant_id == parent.tenant_id, Variable.flow_id == parent.id, Variable.version_id == version.id
            )
            if node_id:
                query = query.where(Variable.node_id == node_id)
            if variable_name:
                query = query.where(Variable.variable_name == variable_name)
            return (await session.exec(query.order_by(Variable.id.asc()))).all()

    @staticmethod
    async def mutate(parent, values=(), *, delete_id=None, replace=False):
        async with get_async_db_session() as session:
            current = (
                await session.exec(
                    select(Flow)
                    .where(Flow.id == parent.id, Flow.tenant_id == parent.tenant_id, Flow.is_delete == 0)
                    .with_for_update()
                )
            ).first()
            if current is None:
                raise NotFoundError()
            assert_workflow_ready(current)
            if replace:
                # Bulk DML does not receive the automatic SELECT tenant filter.
                await session.exec(
                    delete(Variable).where(Variable.flow_id == parent.id, Variable.tenant_id == parent.tenant_id)
                )
            if delete_id is not None:
                row = (
                    await session.exec(
                        select(Variable).where(
                            Variable.id == delete_id,
                            Variable.flow_id == parent.id,
                            Variable.tenant_id == parent.tenant_id,
                        )
                    )
                ).first()
                if row is None:
                    raise NotFoundError()
                await session.delete(row)
            saved = None
            for value in values:
                version = (
                    await session.exec(
                        select(FlowVersion).where(
                            FlowVersion.id == value.version_id,
                            FlowVersion.flow_id == parent.id,
                            FlowVersion.tenant_id == parent.tenant_id,
                            FlowVersion.is_delete == 0,
                        )
                    )
                ).first()
                if version is None:
                    raise NotFoundError()
                if getattr(value, "id", None) is not None and not replace:
                    saved = (
                        await session.exec(
                            select(Variable).where(
                                Variable.id == value.id,
                                Variable.flow_id == parent.id,
                                Variable.tenant_id == parent.tenant_id,
                                Variable.version_id == value.version_id,
                            )
                        )
                    ).first()
                    if saved is None:
                        raise NotFoundError()
                    for field in ("variable_name", "value", "value_type", "is_option"):
                        setattr(saved, field, getattr(value, field))
                else:
                    duplicate = (
                        await session.exec(
                            select(Variable.id).where(
                                Variable.flow_id == parent.id,
                                Variable.tenant_id == parent.tenant_id,
                                Variable.version_id == value.version_id,
                                Variable.node_id == value.node_id,
                                Variable.variable_name == value.variable_name,
                            )
                        )
                    ).first()
                    if duplicate is not None:
                        raise WorkFlowInvalidUserInputError()
                    saved = Variable.model_validate(
                        value.model_dump(exclude={"id", "tenant_id", "create_time", "update_time"}),
                        update={"tenant_id": parent.tenant_id},
                    )
                    session.add(saved)
            await session.commit()
            if saved is not None:
                await session.refresh(saved)
            return saved
