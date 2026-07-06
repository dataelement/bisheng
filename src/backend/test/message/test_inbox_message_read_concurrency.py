"""Concurrency regression tests for inbox message read-status writes.

Reproduces the production race condition (trace 19d54fcc… / 66d16bfb…):
``batch_mark_as_read`` / ``mark_as_read`` used a check-then-insert pattern with
no protection against a concurrent transaction inserting the same
``(message_id, user_id)`` between the SELECT and the INSERT, so the second
committer hit the ``ix_inbox_message_read_msg_user`` unique constraint
(dmPython IntegrityError -6602 / SQLAlchemy gkpj) and the whole batch rolled
back — every message in that request stayed unread and the API 500'd.

These tests drive two *independent* DB connections sharing one in-memory
database and inject a competing insert into the exact window between the
read-status SELECT and the batch INSERT, deterministically (no timing luck).
"""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.message.domain.models.inbox_message_read import InboxMessageRead
from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import (
    InboxMessageReadRepositoryImpl,
)

# Each test gets a distinct shared-cache in-memory DB name so committed rows
# from one test never bleed into the next (a shared-cache DB lives as long as
# any connection to that name is open).
_db_counter = itertools.count()


def _make_engine(db_name: str):
    # Shared-cache in-memory DB: multiple connections see the same tables/rows,
    # but each connection runs its own transaction (unlike StaticPool ':memory:',
    # which is a single connection with no isolation between sessions).
    # StaticPool keeps exactly one live connection per engine so the shared
    # in-memory DB is never torn down while a session is open.
    uri = f"sqlite+aiosqlite:///file:{db_name}?mode=memory&cache=shared&uri=true"
    return create_async_engine(
        uri,
        connect_args={"check_same_thread": False, "uri": True},
        poolclass=StaticPool,
    )


@pytest.fixture()
async def race_sessions():
    """Two AsyncSessions on independent connections over one shared in-memory DB."""
    db_name = f"inbox_read_race_{next(_db_counter)}"
    engine_a = _make_engine(db_name)
    engine_b = _make_engine(db_name)

    async with engine_a.begin() as conn:
        await conn.run_sync(InboxMessageRead.__table__.create)

    session_a = AsyncSession(bind=engine_a, expire_on_commit=False)
    session_b = AsyncSession(bind=engine_b, expire_on_commit=False)
    try:
        yield session_a, session_b
    finally:
        await session_a.close()
        await session_b.close()
        await engine_a.dispose()
        await engine_b.dispose()


async def _count_rows(session: AsyncSession, message_id: int, user_id: int) -> int:
    result = await session.exec(
        select(InboxMessageRead).where(
            InboxMessageRead.message_id == message_id,
            InboxMessageRead.user_id == user_id,
        )
    )
    return len(list(result.all()))


def _inject_competing_insert_after_first_query(session_a, session_b, message_id, user_id):
    """Patch session_a.exec so that, right after the FIRST query returns (the
    read-status SELECT), a competing transaction on session_b inserts
    ``(message_id, user_id)`` and commits — landing us in the exact race window.

    Only the first exec is hijacked; the repository's own retry re-query runs
    unhijacked so it can observe the competitor's row.
    """
    state = {"fired": False}
    orig_exec = session_a.exec

    async def exec_with_injection(*args, **kwargs):
        result = await orig_exec(*args, **kwargs)
        if not state["fired"]:
            state["fired"] = True
            session_b.add(InboxMessageRead(message_id=message_id, user_id=user_id))
            await session_b.commit()
        return result

    session_a.exec = exec_with_injection


async def test_batch_mark_as_read_is_idempotent_under_concurrent_insert(race_sessions):
    session_a, session_b = race_sessions
    user_id = 1
    shared_id = 123  # both requests try to mark this one
    only_a_id = 456  # only request A marks this one

    repo_a = InboxMessageReadRepositoryImpl(session_a)
    _inject_competing_insert_after_first_query(session_a, session_b, shared_id, user_id)

    # Must NOT raise IntegrityError even though `shared_id` gets inserted by the
    # competitor in the SELECT→INSERT window.
    newly_marked = await repo_a.batch_mark_as_read([shared_id, only_a_id], user_id)

    # A only newly marked `only_a_id`; `shared_id` was won by the competitor.
    assert newly_marked == 1
    # Exactly one row per (message_id, user_id) — no duplicates, nothing lost.
    assert await _count_rows(session_a, shared_id, user_id) == 1
    assert await _count_rows(session_a, only_a_id, user_id) == 1


async def test_mark_as_read_is_idempotent_under_concurrent_insert(race_sessions):
    session_a, session_b = race_sessions
    user_id = 7
    shared_id = 999

    repo_a = InboxMessageReadRepositoryImpl(session_a)
    _inject_competing_insert_after_first_query(session_a, session_b, shared_id, user_id)

    # find_one (the first exec) returns empty, competitor inserts, then save()
    # would hit the unique constraint. Must be swallowed idempotently.
    record = await repo_a.mark_as_read(shared_id, user_id)

    assert record is not None
    assert record.message_id == shared_id
    assert record.user_id == user_id
    assert await _count_rows(session_a, shared_id, user_id) == 1


async def test_batch_mark_as_read_dedupes_duplicate_ids(race_sessions):
    """Duplicate ids within one request must not self-collide on the unique index."""
    session_a, _ = race_sessions
    user_id = 3
    repo_a = InboxMessageReadRepositoryImpl(session_a)

    newly_marked = await repo_a.batch_mark_as_read([555, 555, 666], user_id)

    assert newly_marked == 2
    assert await _count_rows(session_a, 555, user_id) == 1
    assert await _count_rows(session_a, 666, user_id) == 1
