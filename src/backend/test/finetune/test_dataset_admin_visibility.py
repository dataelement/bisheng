"""Dataset management compares the same tenant, never a creator's old rows."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.admin.application import request_admission
from bisheng.admin.application.tenant_scope import EffectiveManagementScope
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.request_scope import RequestScope, inherit_scope
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope, visible_tenant_ids
from bisheng.finetune.api.finetune import router
from bisheng.finetune.domain.models import preset_train as model
from bisheng.finetune.domain.models.dataset import FinetuneDataset
from bisheng.finetune.domain.repositories import dataset_catalog
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter


@pytest.fixture
async def datasets(tmp_path, monkeypatch, isolated_tenant_filter):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'datasets.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(model.PresetTrain.__table__.create)
        await connection.run_sync(FinetuneDataset.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(model, "get_async_db_session", sessions)
    monkeypatch.setattr(dataset_catalog, "get_async_db_session", sessions)
    with bypass_tenant_filter():
        async with sessions() as session:
            for tenant in (1, 60, 70):
                for index in range(3):
                    session.add(
                        model.PresetTrain(
                            id=f"{tenant}-{index}",
                            tenant_id=tenant,
                            name=f"dataset-{tenant}-{index}",
                            user_id="849",
                            user_name="same historical creator",
                            url=f"dataset/{tenant}/{index}.json",
                            create_time=datetime(2026, 11, 19) + timedelta(seconds=index),
                        )
                    )
            await session.commit()
    user = SimpleNamespace(user_id=849, tenant_id=60, is_global_super=False)
    selected = SimpleNamespace(tenant_id=60)
    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(return_value=user))

    async def selection(_user):
        return EffectiveManagementScope(selected.tenant_id, "selected", None)

    monkeypatch.setattr(request_admission, "request_target", selection)
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.dependency_overrides[UserPayload.get_tenant_admin_user] = lambda: user
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    monkeypatch.setattr(UserPayload, "assert_effective_web_menu_contains", AsyncMock())
    inherit_scope(router, RequestScope.TENANT)
    app.include_router(router, prefix="/api/v1")
    request_admission.install_request_admission(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, user=user, selected=selected, app=app, sessions=sessions)
    await engine.dispose()


@pytest.mark.parametrize("tenant", [1, 60, 70])
async def test_admins_get_identical_dataset_pages_counts_and_search(datasets, tenant):
    datasets.selected.tenant_id = tenant
    snapshots = []
    for is_super in (False, True):
        datasets.user.is_global_super = is_super
        datasets.user.tenant_id = 1 if is_super else tenant
        headers = {"X-Management-Tenant": str(tenant)} if is_super else {}
        values = []
        for params in (
            {"page_num": 1},
            {"page_num": 2},
            {"page_num": 4},
            {"keyword": f"dataset-{tenant}-1"},
            {"keyword": f"dataset-{70 if tenant == 1 else 1}-"},
        ):
            response = await datasets.client.get(
                "/api/v1/finetune/job/file/preset", params={"page_size": 1, **params}, headers=headers
            )
            assert response.status_code == 200 and response.json()["status_code"] == 200
            data = response.json()["data"]
            assert all(row["tenant_id"] == tenant for row in data["list"])
            values.append(([row["id"] for row in data["list"]], data["total"]))
        snapshots.append(values)
    assert (
        snapshots[0]
        == snapshots[1]
        == [([f"{tenant}-2"], 3), ([f"{tenant}-1"], 3), ([], 3), ([f"{tenant}-1"], 1), ([], 0)]
    )


@pytest.mark.parametrize("tenant", [1, 60, 70])
async def test_dataset_queries_ignore_a_wider_legacy_visibility_set(datasets, tenant):
    with tenant_execution_scope(tenant):
        token = visible_tenant_ids.set(frozenset({1, 60, 70}))
        try:
            rows, count = await model.PresetTrainDao.search_name(page_size=1, page_num=1)
            all_rows = await model.PresetTrainDao.find_all()
            foreign = 70 if tenant == 1 else 1
            assert await model.PresetTrainDao.find_one(f"{foreign}-0") is None
            assert await model.PresetTrainDao.find_by_url(f"dataset/{foreign}/0.json") is None
            assert (await model.PresetTrainDao.find_by_url(f"dataset/{tenant}/0.json")).tenant_id == tenant
        finally:
            visible_tenant_ids.reset(token)
    assert count == 3 and len(rows) == 1 and rows[0].tenant_id == tenant
    assert {row.tenant_id for row in all_rows} == {tenant}
