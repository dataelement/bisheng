"""Portable SQL contract tests; SQLite does not prove MySQL/DM8 locking."""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.config import Config
from bisheng.dsh.domain.repositories import tool_publications as module
from bisheng.dsh.domain.schemas.tool_publications import ToolPublication


@pytest.fixture
async def repository(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/publications.db")
    async with engine.begin() as connection:
        await connection.run_sync(Config.__table__.create)

    @asynccontextmanager
    async def session():
        async with AsyncSession(engine, expire_on_commit=False) as value:
            yield value

    monkeypatch.setattr(module, "get_async_db_session", session)
    try:
        yield module.ToolPublicationRepository()
    finally:
        await engine.dispose()


async def test_complete_replace_revision_isolation_and_pagination(repository):
    """AC-03, AC-04, AC-07: complete SQL records, tenant-qualified keys, stable list."""
    for tenant, code in [(2, "alpha"), (2, "beta"), (3, "alpha")]:
        item = ToolPublication(tool_id=7, enabled=True, tool_code=code, revision=1)
        async with repository.locked(tenant, code, initial=item) as record:
            assert record.created
    async with repository.locked(2, "alpha") as record:
        record.publication = record.publication.model_copy(update={"tool_id": 8, "enabled": False, "revision": 2})
    async with repository.locked(3, "alpha") as record:
        assert record.publication.tool_id == 7 and record.publication.enabled
    items, total = await repository.list(2, offset=0, limit=1)
    assert total == 2 and items[0].tool_code == "alpha" and items[0].revision == 2
    async with repository.locked(2, "missing") as record:
        assert record.publication is None


async def test_rollback_and_like_prefix_escape(repository, monkeypatch):
    """AC-07: failed replace rolls back; LIKE underscores never broaden tenant keys."""
    item = ToolPublication(tool_id=7, enabled=True, tool_code="alpha", revision=1)
    async with repository.locked(2, "alpha", initial=item):
        pass
    with pytest.raises(RuntimeError):
        async with repository.locked(2, "alpha") as record:
            record.publication = item.model_copy(update={"enabled": False})
            raise RuntimeError("abort")
    async with repository.locked(2, "alpha") as record:
        assert record.publication.enabled
    original = repository.prefix
    monkeypatch.setattr(repository.__class__, "prefix", staticmethod(lambda tenant: original(tenant).replace("_", "x")))
    items, total = await repository.list(2)
    assert items == [] and total == 0
