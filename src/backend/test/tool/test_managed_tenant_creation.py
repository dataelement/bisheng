"""Nonempty tool children share parent T and atomic SQL failure."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao, GptsToolsType, GptsToolsTypeRead
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope


@pytest.fixture
async def tool_db(managed_db, monkeypatch):
    from bisheng.tool.domain.models import gpts_tools
    from bisheng.tool.domain.repositories import creation_repository

    await managed_db.create(GptsToolsType, GptsTools)
    monkeypatch.setattr(gpts_tools, "get_async_db_session", managed_db.sessions)
    monkeypatch.setattr(creation_repository, "get_async_db_session", managed_db.sessions)
    return managed_db


async def test_nonempty_tool_inherits_parent_t_despite_actor_home(tool_db):
    with management_scope(1, 2):
        result = await GptsToolsDao.insert_tool_type(
            GptsToolsTypeRead(
                name="A",
                tenant_id=2,
                user_id=7,
                children=[GptsTools(name="child", desc="", tool_key="before", user_id=7, tenant_id=1)],
            )
        )
    with bypass_tenant_filter():
        async with tool_db.sessions() as session:
            parent = await session.get(GptsToolsType, result.id)
            child = (await session.exec(select(GptsTools))).one()
            assert parent.tenant_id == child.tenant_id == 2
            assert parent.creation_state == "PENDING"


async def test_child_sql_failure_does_not_leave_parent(tool_db):
    with management_scope(1, 2), pytest.raises(IntegrityError):
        await GptsToolsDao.insert_tool_type(
            GptsToolsTypeRead(
                name="bad",
                tenant_id=2,
                user_id=7,
                children=[
                    GptsTools(name="same", desc="", tool_key="one", user_id=7),
                    GptsTools(name="same", desc="", tool_key="two", user_id=7),
                ],
            )
        )
    with bypass_tenant_filter():
        async with tool_db.sessions() as session:
            assert not (await session.exec(select(GptsToolsType))).all()
            assert not (await session.exec(select(GptsTools))).all()
