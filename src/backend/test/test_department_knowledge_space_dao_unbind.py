"""TDD tests for DepartmentKnowledgeSpaceDao.adelete_by_space_id.

Uses a self-contained async SQLite engine (the department_knowledge_space
table is not part of the shared test/fixtures table set) and patches
get_async_db_session inside the model module so the DAO's own async context
manager targets this in-memory session, following the pattern in
test_shougang_domain_file_counts_dao.py (session-factory patch) and
test_tenant_tree_dao.py (self-contained SQLite engine).
"""
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.department import Department  # noqa: F401  (registers FK target table)
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpace,
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge  # noqa: F401  (registers FK target table)


@pytest.fixture()
async def binding_session():
    engine = create_async_engine(
        'sqlite+aiosqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[DepartmentKnowledgeSpace.__table__],
        )
    session = AsyncSession(bind=engine, expire_on_commit=False)

    @asynccontextmanager
    async def _factory():
        yield session

    with patch(
        'bisheng.knowledge.domain.models.department_knowledge_space.get_async_db_session',
        _factory,
    ):
        yield session
    await session.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_adelete_by_space_id_removes_binding(binding_session):
    await DepartmentKnowledgeSpaceDao.acreate(
        tenant_id=1, department_id=11, space_id=101, created_by=1,
    )
    assert await DepartmentKnowledgeSpaceDao.aget_by_space_id(101) is not None

    deleted = await DepartmentKnowledgeSpaceDao.adelete_by_space_id(101)
    assert deleted is True
    assert await DepartmentKnowledgeSpaceDao.aget_by_space_id(101) is None


@pytest.mark.asyncio
async def test_adelete_by_space_id_missing_returns_false(binding_session):
    assert await DepartmentKnowledgeSpaceDao.adelete_by_space_id(999999) is False
