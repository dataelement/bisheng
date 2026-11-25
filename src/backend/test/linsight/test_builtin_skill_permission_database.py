"""Native row-lock regression on an explicitly disposable MySQL/DM8 schema.

Set SKILL_BOOTSTRAP_TEST_DSN to an async SQLAlchemy URL and
SKILL_BOOTSTRAP_EPHEMERAL_ACK=1. The schema/user name must contain
``skill_bootstrap_test`` and the schema must be empty. Only this fixture's
skill table is created and dropped. Application configuration is never used
as a database-test destination.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.repositories import skill_permission as persistence


@pytest.fixture
async def native_skills(monkeypatch):
    dsn = os.environ.get("SKILL_BOOTSTRAP_TEST_DSN")
    if not dsn:
        pytest.skip("SKILL_BOOTSTRAP_TEST_DSN is required for native MySQL/DM8 locking")
    if os.environ.get("SKILL_BOOTSTRAP_EPHEMERAL_ACK") != "1":
        pytest.fail("SKILL_BOOTSTRAP_EPHEMERAL_ACK=1 is required")
    url = make_url(dsn)
    if url.drivername not in {"mysql+aiomysql", "dm+dmAsync"}:
        pytest.fail("SKILL_BOOTSTRAP_TEST_DSN must use mysql+aiomysql or dm+dmAsync")
    if "skill_bootstrap_test" not in f"{url.database or ''}|{url.username or ''}".casefold():
        pytest.fail("Native locking tests require a dedicated skill_bootstrap_test schema/user")
    engine = create_async_engine(dsn, pool_size=5, max_overflow=0)
    metadata = sa.MetaData()
    LinsightSkill.__table__.to_metadata(metadata)
    owned = False
    try:
        async with engine.begin() as connection:
            existing = await connection.run_sync(lambda conn: sa.inspect(conn).get_table_names())
            if existing:
                pytest.fail("Refusing to use a non-empty database test schema")
            owned = True
            await connection.run_sync(metadata.create_all)

        @asynccontextmanager
        async def sessions():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

        async with sessions() as session:
            session.add_all(
                [
                    LinsightSkill(
                        id=ident,
                        tenant_id=1,
                        name=f"builtin-{ident}",
                        description="Disposable native lock regression",
                        source="builtin",
                        object_path=f"skills/{ident}.zip",
                    )
                    for ident in (902, 903)
                ]
            )
            await session.commit()
        monkeypatch.setattr(persistence, "get_async_db_session", sessions)
        yield SimpleNamespace(repository=persistence.SkillPermissionRepository(), engine=engine)
    finally:
        if owned:
            async with engine.begin() as connection:
                await connection.run_sync(metadata.drop_all)
        await engine.dispose()


@pytest.mark.parametrize("release_kind", ["complete", "exception", "cancel"])
async def test_native_connections_serialize_one_skill_and_release_the_lock(native_skills, release_kind):
    repository = native_skills.repository
    entered, release, queried, acquired = (asyncio.Event() for _ in range(4))
    second = None

    def before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        if asyncio.current_task() is second and "FOR UPDATE" in statement.upper():
            queried.set()

    sa.event.listen(native_skills.engine.sync_engine, "before_cursor_execute", before_cursor_execute)

    async def holder():
        async with repository.lock(902, tenant_id=1) as row:
            assert row.id == 902
            entered.set()
            await release.wait()
            if release_kind == "exception":
                raise RuntimeError("injected bootstrap failure")

    async def waiter():
        async with repository.lock(902, tenant_id=1) as row:
            acquired.set()
            return row.id

    first = asyncio.create_task(holder())
    try:
        await asyncio.wait_for(entered.wait(), 10)
        second = asyncio.create_task(waiter())
        # The waiter must have issued its native locking SELECT, rather than
        # merely having been scheduled, before we assert that it cannot enter.
        await asyncio.wait_for(queried.wait(), 10)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(acquired.wait(), 0.2)
        async with asyncio.timeout(10):
            async with repository.lock(903, tenant_id=1) as other:
                assert other.id == 903  # Unrelated skills are not serialized.
        if release_kind == "cancel":
            first.cancel()
        else:
            release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 10)
        assert outcomes[1] == 902
        if release_kind == "complete":
            assert outcomes[0] is None
        elif release_kind == "exception":
            assert isinstance(outcomes[0], RuntimeError)
        else:
            assert isinstance(outcomes[0], asyncio.CancelledError)
        assert acquired.is_set()
    finally:
        release.set()
        pending = [task for task in (first, second) if task is not None and not task.done()]
        for task in pending:
            task.cancel()
        for result in await asyncio.gather(*pending, return_exceptions=True):
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                raise result
        sa.event.remove(native_skills.engine.sync_engine, "before_cursor_execute", before_cursor_execute)
