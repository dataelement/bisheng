"""Tenant-local template storage. Every operation uses a fresh strict session."""

from sqlmodel import select

from bisheng.common.errcode.flow import FlowTemplateNameError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.flow import Flow
from bisheng.database.models.template import Template

ORDER_GAP = 65535


class TemplateRepository:
    @staticmethod
    async def list(*, flow_type=None, name=None, page_size=None, page_name=None):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                stmt = select(Template).where(Template.flow_type.in_([5, 10]))
                if flow_type is not None:
                    stmt = stmt.where(Template.flow_type == flow_type)
                if name:
                    stmt = stmt.where(Template.name == name)
                stmt = stmt.order_by(Template.order_num.desc(), Template.id.desc())
                if page_size and page_name:
                    stmt = stmt.offset(page_size * (page_name - 1)).limit(page_size)
                return list((await session.exec(stmt)).all())

    @staticmethod
    async def get(template_id: int):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return (
                    await session.exec(
                        select(Template).where(Template.id == template_id, Template.flow_type.in_([5, 10]))
                    )
                ).first()

    @staticmethod
    async def source(source_id: str, flow_type: int):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                if flow_type == 5:
                    stmt = select(Assistant).where(Assistant.id == source_id, Assistant.is_delete == 0)
                else:
                    stmt = select(Flow).where(Flow.id == source_id, Flow.flow_type == 10)
                row = (await session.exec(stmt)).first()
                return row.model_dump() if row else None

    @staticmethod
    async def create(values: dict):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                duplicate = (await session.exec(select(Template.id).where(Template.name == values["name"]))).first()
                if duplicate is not None:
                    raise FlowTemplateNameError()
                highest = (
                    await session.exec(select(Template.order_num).order_by(Template.order_num.desc()).limit(1))
                ).first()
                row = Template(**values, order_num=(highest or 0) + ORDER_GAP)
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row

    @staticmethod
    async def update(template_id: int, values: dict):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                row = (
                    await session.exec(
                        select(Template).where(Template.id == template_id, Template.flow_type.in_([5, 10]))
                    )
                ).first()
                if row is None:
                    raise NotFoundError()
                if values.get("name"):
                    duplicate = (
                        await session.exec(
                            select(Template.id).where(Template.name == values["name"], Template.id != template_id)
                        )
                    ).first()
                    if duplicate is not None:
                        raise FlowTemplateNameError()
                for key, value in values.items():
                    setattr(row, key, value)
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row

    @staticmethod
    async def delete(template_id: int):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                row = (
                    await session.exec(
                        select(Template).where(Template.id == template_id, Template.flow_type.in_([5, 10]))
                    )
                ).first()
                if row is None:
                    raise NotFoundError()
                await session.delete(row)
                await session.commit()

    @staticmethod
    async def workflow_data():
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return list((await session.exec(select(Template.data).where(Template.flow_type == 10))).all())
