"""Finetune jobs stay inside the current tenant, even when Root is visible."""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.finetune.domain.models import finetune as finetune_module
from bisheng.finetune.domain.models.finetune import Finetune, FinetuneDao, FinetuneList


def _job(job_id: str, tenant_id: int, model_name: str, server_name: str) -> Finetune:
    return Finetune(
        id=job_id,
        server=1,
        server_name=server_name,
        base_model_name="base",
        model_name=model_name,
        extra_params={"gpus": "0"},
        user_id=1,
        user_name="admin",
        tenant_id=tenant_id,
    )


@pytest.fixture
async def jobs(tmp_path, monkeypatch):
    from bisheng.core.database import tenant_filter

    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'finetune.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Finetune.__table__.create)

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(finetune_module, "get_async_db_session", session_factory)
    async with session_factory() as session:
        with bypass_tenant_filter():
            session.add(_job("root-job", 1, "AA", "FT-20"))
            session.add(_job("leaf-job", 5, "leaf-model", "FT-leaf"))
            await session.commit()
    yield
    await engine.dispose()
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()


def _child_scope():
    tenant_token = set_current_tenant_id(5)
    visible_token = set_visible_tenant_ids(frozenset({5, 1}))
    return tenant_token, visible_token


def _reset(tenant_token, visible_token):
    current_tenant_id.reset(tenant_token)
    visible_tenant_ids.reset(visible_token)


@pytest.mark.asyncio
async def test_child_tenant_list_hides_root_jobs(jobs):
    tokens = _child_scope()
    try:
        rows, total = await FinetuneDao.find_jobs(FinetuneList(page=1, limit=10))
    finally:
        _reset(*tokens)

    assert total == 1
    assert [row.id for row in rows] == ["leaf-job"]


@pytest.mark.asyncio
async def test_child_tenant_cannot_open_root_job(jobs):
    tokens = _child_scope()
    try:
        foreign = await FinetuneDao.find_job("root-job")
        own = await FinetuneDao.find_job("leaf-job")
        servers = await FinetuneDao.get_server_filters()
    finally:
        _reset(*tokens)

    assert foreign is None
    assert own is not None and own.id == "leaf-job"
    assert list(servers) == ["FT-leaf"]


@pytest.mark.asyncio
async def test_root_tenant_still_sees_its_own_jobs(jobs):
    tenant_token = set_current_tenant_id(1)
    visible_token = set_visible_tenant_ids(frozenset({1}))
    try:
        rows, total = await FinetuneDao.find_jobs(FinetuneList(page=1, limit=10))
    finally:
        _reset(tenant_token, visible_token)

    assert total == 1
    assert [row.id for row in rows] == ["root-job"]
