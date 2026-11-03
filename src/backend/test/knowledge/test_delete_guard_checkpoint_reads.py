"""Deletion guard budgets and scope on real repository SQL, without middleware."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database.dialect_helpers import JsonType
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeFootprint as Footprint,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeRequest as Request,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
    KnowledgeSpaceFileChangeFootprintRepository,
)


@pytest.fixture
async def guard_db():
    token = set_current_tenant_id(42)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all, tables=[Request.__table__, Footprint.__table__])

        @asynccontextmanager
        async def sessions():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

        async def seed(ids, *, tenant=42, space=8, action="delete", state="failed", checkpoint=None, kind="folder"):
            async with sessions() as session, session.begin():
                request = Request(
                    tenant_id=tenant,
                    space_id=space,
                    action=action,
                    resource_type=kind,
                    resource_id=ids[0] if ids else None,
                    applicant_user_id=7,
                    business_key=uuid4().hex,
                    request_fingerprint=uuid4().hex,
                    execution_state=state,
                    execution_checkpoint={"deletion_cutover_active": True} if checkpoint is None else checkpoint,
                )
                session.add(request)
                await session.flush()
                for resource_id in ids:
                    session.add(
                        Footprint(
                            tenant_id=tenant,
                            space_id=space,
                            request_id=request.id,
                            resource_type=kind,
                            resource_id=resource_id,
                            lock_scope="exact",
                        )
                    )
                return int(request.id)

        async def read(**kwargs):
            async with sessions() as session:
                return await KnowledgeSpaceFileChangeFootprintRepository(session).list_active_delete_resource_ids(
                    tenant_id=42,
                    space_ids=kwargs.get("spaces", [8]),
                    resource_types=kwargs.get("types", ["folder"]),
                    cutover_checkpoint_key="deletion_cutover_active",
                )

        yield SimpleNamespace(engine=engine, sessions=sessions, seed=seed, read=read)
    finally:
        await engine.dispose()
        current_tenant_id.reset(token)


@pytest.mark.parametrize("count", [1, 40, 399])
async def test_checkpoint_decoded_once_per_request_not_per_footprint(guard_db, monkeypatch, count):
    ids = list(range(1, count + 1))
    await guard_db.seed(ids, checkpoint={"deletion_cutover_active": True, "manifest": "x" * 260362})
    decoded = []
    original = JsonType.process_result_value

    def observe(self, value, dialect):
        decoded.append(len(value))
        return original(self, value, dialect)

    monkeypatch.setattr(JsonType, "process_result_value", observe)
    statements = []
    event.listen(
        guard_db.engine.sync_engine, "before_cursor_execute", lambda c, cu, sql, p, ctx, many: statements.append(sql)
    )
    assert await guard_db.read() == set(ids)
    assert len(decoded) == 1
    assert len(statements) == 2
    assert "execution_checkpoint" not in statements[0].split("FROM")[0]


@pytest.mark.parametrize("spaces,types", [([], ["folder"]), ([8], []), ([8], ["folder"])])
async def test_empty_scope_or_no_candidates_never_reads_checkpoints(guard_db, spaces, types):
    statements = []
    event.listen(
        guard_db.engine.sync_engine, "before_cursor_execute", lambda c, cu, sql, p, ctx, many: statements.append(sql)
    )
    assert await guard_db.read(spaces=spaces, types=types) == set()
    assert len(statements) == (1 if spaces and types else 0)


async def test_request_scope_states_and_exact_true_marker_are_preserved(guard_db):
    for index, state in enumerate(["applying", "failed", "applied"], start=1):
        await guard_db.seed([index], state=state)
    await guard_db.seed([4], checkpoint={"deletion_cutover_active": False})
    await guard_db.seed([5], checkpoint={})
    await guard_db.seed([6], checkpoint={"deletion_cutover_active": 1})
    await guard_db.seed([7], checkpoint=[])
    await guard_db.seed([8], state="closed")
    await guard_db.seed([9], state="queued")
    await guard_db.seed([10], action="rename")
    await guard_db.seed([11], tenant=99)
    await guard_db.seed([12], space=9)
    await guard_db.seed([13], kind="staged_upload")
    await guard_db.seed([None])
    assert await guard_db.read() == {1, 2, 3}


async def test_checkpoint_in_parameters_are_bounded_by_unique_requests(guard_db, monkeypatch):
    for resource_id in range(1, 502):
        await guard_db.seed([resource_id])
    sizes = []
    statements = []

    def observe(c, cu, sql, parameters, ctx, many):
        statements.append(sql)
        if "execution_checkpoint" in sql.split("FROM")[0]:
            sizes.append(len(parameters) - 1)  # explicit tenant + request IDs

    event.listen(guard_db.engine.sync_engine, "before_cursor_execute", observe)
    assert await guard_db.read() == set(range(1, 502))
    assert sizes == [500, 1]
    assert len(statements) == 3


@pytest.mark.parametrize("retired", [False, True])
async def test_retry_or_finalization_between_reads_keeps_guard_semantics(guard_db, retired):
    request_id = await guard_db.seed([101, 102])
    # Simulate the committed state observed by the second SELECT at READ COMMITTED.
    # Session hook mutates only this in-memory fixture, never production state.
    original = AsyncSession.exec
    changed = False

    async def interleave(session, statement, *args, **kwargs):
        nonlocal changed
        if not changed and "execution_checkpoint" in str(statement).split("FROM")[0]:
            changed = True
            from sqlalchemy import update

            await session.execute(
                update(Request)
                .where(Request.id == request_id)
                .values(
                    execution_state="applied" if retired else "queued",
                    execution_checkpoint={"deletion_cutover_active": not retired},
                )
            )
        return await original(session, statement, *args, **kwargs)

    from unittest.mock import patch

    with patch.object(AsyncSession, "exec", interleave):
        assert await guard_db.read() == (set() if retired else {101, 102})
