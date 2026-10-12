from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from inspect import signature

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.flow import FlowType
from bisheng.database.models.session import MessageSession
from bisheng.knowledge.api.dependencies import (
    get_knowledge_chat_session_repository,
    get_knowledge_space_chat_service,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_chat_session_repository_impl import (
    KnowledgeChatSessionRepositoryImpl,
)


@pytest.fixture()
async def session_repo():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(MessageSession.__table__.create)

    state = {"active": 0}

    @asynccontextmanager
    async def session_factory():
        state["active"] += 1
        try:
            async with AsyncSession(bind=engine, expire_on_commit=False) as session:
                yield session
        finally:
            state["active"] -= 1

    try:
        yield session_factory, state, KnowledgeChatSessionRepositoryImpl(session_factory)
    finally:
        await engine.dispose()


def _session(
    chat_id: str,
    flow_id: str,
    *,
    entry_flow_id: str | None = None,
    user_id: int = 10,
    tenant_id: int = 1,
    flow_type: int = FlowType.KNOLEDGE_SPACE.value,
    is_delete: bool = False,
    created_offset: int = 0,
) -> MessageSession:
    return MessageSession(
        chat_id=chat_id,
        flow_id=flow_id,
        entry_flow_id=entry_flow_id,
        flow_type=flow_type,
        flow_name="knowledge chat",
        user_id=user_id,
        tenant_id=tenant_id,
        is_delete=is_delete,
        create_time=datetime(2026, 1, 1) + timedelta(seconds=created_offset),
        update_time=datetime(2026, 1, 1),
    )


async def test_effective_entry_list_is_mutually_exclusive_and_create_time_sorted(session_repo):
    session_factory, state, repo = session_repo
    root = "space_1_folder_0"
    async with session_factory() as session:
        session.add_all(
            [
                _session("native-root", root, created_offset=1),
                _session("recovered", "space_1_file_11", entry_flow_id=root, created_offset=2),
                _session("old-entry-hidden", "space_1_file_12", entry_flow_id=root, created_offset=3),
                _session("other-user", root, user_id=99, created_offset=4),
                _session("deleted", root, is_delete=True, created_offset=5),
                _session("other-type", root, flow_type=FlowType.ASSISTANT.value, created_offset=6),
            ]
        )
        await session.commit()

    rows = await repo.list_by_effective_entry(root, user_id=10)
    old_rows = await repo.list_by_effective_entry("space_1_file_12", user_id=10)

    assert [row.chat_id for row in rows] == [
        "old-entry-hidden",
        "recovered",
        "native-root",
    ]
    assert old_rows == []
    assert state["active"] == 0


async def test_chat_lookup_requires_current_effective_entry(session_repo):
    session_factory, state, repo = session_repo
    root = "space_1_folder_0"
    async with session_factory() as session:
        session.add(_session("recovered", "space_1_folder_12", entry_flow_id=root))
        await session.commit()

    assert await repo.get_by_chat_and_effective_entry("recovered", root, 10) is not None
    assert await repo.get_by_chat_and_effective_entry("recovered", "space_1_folder_12", 10) is None
    assert await repo.get_by_chat_and_effective_entry("recovered", root, 99) is None
    assert state["active"] == 0


async def test_rehome_updates_only_active_null_entry_knowledge_sessions(session_repo):
    session_factory, state, repo = session_repo
    root = "space_1_folder_0"
    affected = "space_1_file_11"
    async with session_factory() as session:
        session.add_all(
            [
                _session("owner-a", affected, tenant_id=1),
                _session("owner-b", affected, user_id=20, tenant_id=2),
                _session("sticky", affected, entry_flow_id="space_1_folder_9"),
                _session("deleted", affected, is_delete=True),
                _session("other-type", affected, flow_type=FlowType.ASSISTANT.value),
                _session("unaffected", "space_1_file_99"),
            ]
        )
        await session.commit()

    first = await repo.rehome_by_flows(root, [affected, affected])
    second = await repo.rehome_by_flows(root, [affected])

    assert (first.matched_count, first.updated_count) == (2, 2)
    assert (second.matched_count, second.updated_count) == (0, 0)
    assert state["active"] == 0
    async with session_factory() as session:
        assert (await session.get(MessageSession, "owner-a")).entry_flow_id == root
        assert (await session.get(MessageSession, "owner-b")).entry_flow_id == root
        assert (await session.get(MessageSession, "sticky")).entry_flow_id == "space_1_folder_9"
        assert (await session.get(MessageSession, "deleted")).entry_flow_id is None
        assert (await session.get(MessageSession, "other-type")).entry_flow_id is None
        assert (await session.get(MessageSession, "unaffected")).entry_flow_id is None


async def test_rehome_rejects_more_than_one_chunk_before_database_access(session_repo):
    _, _, repo = session_repo

    with pytest.raises(ValueError, match="exceeds 500"):
        await repo.rehome_by_flows(
            "space_1_folder_0",
            [f"space_1_file_{resource_id}" for resource_id in range(1, 502)],
        )


def test_streaming_chat_dependencies_do_not_capture_request_scoped_db_session():
    assert "session" not in signature(get_knowledge_chat_session_repository).parameters
    chat_service_params = signature(get_knowledge_space_chat_service).parameters
    assert "session" not in chat_service_params
    assert "version_repo" not in chat_service_params
