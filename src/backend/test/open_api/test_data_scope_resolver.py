"""F066: the "created by me" reading matches the sidebar exactly.

覆盖 AC: AC-P25
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager

import pytest

import bisheng.knowledge.domain.services.data_scope_resolver as resolver_module
from bisheng.knowledge.domain.services.data_scope_resolver import KnowledgeDataScopeResolver


@pytest.fixture
async def knowledge_db(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.common.models.space_channel_member import (
        BusinessTypeEnum,
        MembershipStatusEnum,
        SpaceChannelMember,
        UserRoleEnum,
    )
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        for model in (Knowledge, KnowledgeFile, SpaceChannelMember, DepartmentKnowledgeSpace):
            await connection.run_sync(model.__table__.create)
    tenant_token = set_current_tenant_id(1)
    resolver_module._memo.set(None)

    @asynccontextmanager
    async def session_factory():
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    for module_name in (
        "bisheng.knowledge.domain.models.knowledge",
        "bisheng.knowledge.domain.models.knowledge_file",
        "bisheng.common.models.space_channel_member",
        "bisheng.knowledge.domain.models.department_knowledge_space",
    ):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_async_db_session", session_factory)

    async with session_factory() as session:
        # Libraries: 101/102 created by holder 5 (doc + QA), 103 by someone
        # else, 104 a legacy row with no creator at all.
        session.add(Knowledge(id=101, name="mine-doc", type=0, user_id=5, tenant_id=1))
        session.add(Knowledge(id=102, name="mine-qa", type=1, user_id=5, tenant_id=1))
        session.add(Knowledge(id=103, name="theirs-doc", type=0, user_id=6, tenant_id=1))
        session.add(Knowledge(id=104, name="orphan", type=0, user_id=None, tenant_id=1))
        # Spaces: 201 mine, 202 mine but department-bound, 203 someone else's.
        session.add(Knowledge(id=201, name="mine-space", type=3, user_id=5, tenant_id=1))
        session.add(Knowledge(id=202, name="dept-space", type=3, user_id=5, tenant_id=1))
        session.add(Knowledge(id=203, name="their-space", type=3, user_id=6, tenant_id=1))
        for space_id, creator in ((201, 5), (202, 5), (203, 6)):
            session.add(
                SpaceChannelMember(
                    business_id=str(space_id),
                    business_type=BusinessTypeEnum.SPACE,
                    user_id=creator,
                    user_role=UserRoleEnum.CREATOR,
                    status=MembershipStatusEnum.ACTIVE,
                )
            )
        session.add(DepartmentKnowledgeSpace(department_id=9, space_id=202, created_by=1))
        # Files: 1001 in my library, 1002 in their space, 1003 added by user 6
        # inside my space — the accepted residual risk keeps it retrievable.
        session.add(KnowledgeFile(id=1001, knowledge_id=101, file_name="a.docx", user_id=5))
        session.add(KnowledgeFile(id=1002, knowledge_id=203, file_name="b.docx", user_id=6))
        session.add(KnowledgeFile(id=1003, knowledge_id=201, file_name="c.docx", user_id=6))
        await session.commit()

    yield session_factory
    from bisheng.core.context.tenant import current_tenant_id

    current_tenant_id.reset(tenant_token)
    await engine.dispose()


async def test_owned_libraries_follow_creator_column(knowledge_db):
    resolver = KnowledgeDataScopeResolver()

    owned = await resolver.filter_owned(
        holder_user_id=5,
        tenant_id=1,
        resource_type="knowledge_library",
        resource_ids=("101", "102", "103", "104"),
    )

    assert owned == frozenset({"101", "102"})


async def test_owned_spaces_exclude_department_bound(knowledge_db):
    resolver = KnowledgeDataScopeResolver()

    owned = await resolver.filter_owned(
        holder_user_id=5,
        tenant_id=1,
        resource_type="knowledge_space",
        resource_ids=("201", "202", "203"),
    )

    assert owned == frozenset({"201"})  # 202 left the personal set when bound
    assert await resolver.owned_ids(holder_user_id=5, tenant_id=1, resource_type="knowledge_space") == frozenset(
        {"201"}
    )


async def test_files_are_judged_by_parent_not_by_file_creator(knowledge_db):
    resolver = KnowledgeDataScopeResolver()

    owned = await resolver.filter_owned(
        holder_user_id=5,
        tenant_id=1,
        resource_type="knowledge_file",
        resource_ids=("1001", "1002", "1003", "9999"),
    )

    # 1003 was uploaded by user 6 inside holder-created space 201: retrievable
    # (accepted residual risk, D21); unknown file 9999 fails closed.
    assert owned == frozenset({"1001", "1003"})


async def test_ownership_is_memoised_per_request(knowledge_db, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

    resolver = KnowledgeDataScopeResolver()
    first = await resolver.owned_ids(holder_user_id=5, tenant_id=1, resource_type="knowledge_library")

    async def boom(*args, **kwargs):
        raise AssertionError("memo miss: the database was queried twice")

    monkeypatch.setattr(KnowledgeDao, "aget_knowledge_ids_created_by", boom)
    second = await resolver.owned_ids(holder_user_id=5, tenant_id=1, resource_type="knowledge_library")

    assert first == second == frozenset({"101", "102"})
