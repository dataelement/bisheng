"""F025 owner capability, tenant restriction and page metadata boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.errcode.dsh import (
    DshAuthorizationUnavailableError,
    DshInvalidRequestError,
    DshModelNotAllowedError,
)
from bisheng.dsh.domain.services import vision
from bisheng.dsh.domain.services.profile import profile_scope


@pytest.fixture
def capability_store(monkeypatch):
    from bisheng.llm.domain.services.llm import LLMService

    persisted, legacy = {}, {}

    class Store:
        def __init__(self, tenant, model):
            self.key = tenant, model

        async def read(self):
            return persisted.get(self.key)

        async def save(self, value):
            persisted[self.key] = value

    def repository(model):
        from bisheng.core.context.tenant import get_current_tenant_id

        return Store(get_current_tenant_id(), model)

    async def legacy_visual(model, tenant):
        return legacy.get((tenant, model))

    snapshot = AsyncMock(return_value=(SimpleNamespace(id=7, tenant_id=1), SimpleNamespace(tenant_id=1)))
    monkeypatch.setattr(vision, "repository", repository)
    monkeypatch.setattr(vision, "legacy_visual", legacy_visual)
    monkeypatch.setattr(LLMService, "get_dsh_model_metadata_snapshot", snapshot)
    return SimpleNamespace(persisted=persisted, legacy=legacy, snapshot=snapshot)


@pytest.mark.parametrize(
    "owner,old_owner,child,old_child,expected",
    [
        (None, None, None, None, False),
        (True, None, None, None, True),
        (None, True, None, None, True),
        (True, False, None, None, False),
        (False, True, True, None, False),
        (True, None, False, None, False),
        (True, None, True, False, False),
        (True, None, None, False, False),
    ],
)
async def test_historical_false_never_expands_capability(
    capability_store, owner, old_owner, child, old_child, expected
):
    state = capability_store
    for tenant, value in ((1, owner), (69, child)):
        if value is not None:
            state.persisted[tenant, 7] = json.dumps({"vision": value})
    state.legacy.update({(1, 7): old_owner, (69, 7): old_child})
    before = dict(state.persisted)
    with profile_scope(69):
        row = await vision.configure_vision(7)
    assert row["vision"] is expected
    assert row["effective"] is expected
    assert state.persisted == before  # GET cannot migrate historical data.


async def test_explicit_owner_save_repairs_conflict_child_cannot_override_owner(capability_store):
    state = capability_store
    state.persisted[1, 7] = '{"vision":true}'
    state.legacy[1, 7] = False
    with profile_scope(1):
        assert not (await vision.configure_vision(7))["vision"]
        assert (await vision.configure_vision(7, vision.VisionSetting(vision=True)))["vision"]
    assert json.loads(state.persisted[1, 7])["authority_version"] == 1
    with profile_scope(69):
        assert (await vision.read_vision(7)).vision
        assert not (await vision.configure_vision(7, vision.VisionSetting(vision=False)))["vision"]
        assert (await vision.configure_vision(7, vision.VisionSetting(vision=True)))["vision"]
    with profile_scope(1):
        await vision.configure_vision(7, vision.VisionSetting(vision=False))
    with profile_scope(69):
        assert not (await vision.read_vision(7)).vision
        with pytest.raises(DshInvalidRequestError):
            await vision.configure_vision(7, vision.VisionSetting(vision=True))


async def test_batch_known_refusal_is_diagnostic_outage_is_real_failure(capability_store):
    state = capability_store
    state.snapshot.side_effect = [
        (SimpleNamespace(id=7, tenant_id=1), SimpleNamespace()),
        DshModelNotAllowedError(),
    ]
    with profile_scope(69):
        rows = await vision.batch_vision([7, 8, 7])
    assert len(rows) == 2 and rows[1]["status"] == "unavailable" and rows[1]["read_only"]
    state.snapshot.side_effect = DshAuthorizationUnavailableError()
    with profile_scope(69), pytest.raises(DshAuthorizationUnavailableError):
        await vision.batch_vision([7])


async def test_batch_http_admin_scope_and_payload(monkeypatch):
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.dsh.api.endpoints import admin

    app = FastAPI()
    app.include_router(admin.router, prefix="/api/v1")
    management = SimpleNamespace(authorize=AsyncMock(return_value=(None, 69)))
    app.dependency_overrides[admin.admin_user] = lambda: SimpleNamespace(user_id=90)
    app.dependency_overrides[admin.get_model_management] = lambda: management

    async def read(ids):
        assert get_current_tenant_id() == 69
        return [{"model_id": item, "vision": False} for item in ids]

    monkeypatch.setattr(admin, "batch_vision", read)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/dsh/admin/model-vision", json={"model_ids": [7]})
        assert response.json()["data"] == [{"model_id": 7, "vision": False}]
        assert (await client.post("/api/v1/dsh/admin/model-vision", json={"model_ids": [7] * 201})).status_code == 422
    management.authorize.assert_awaited_once()


async def test_non_dsh_catalog_uses_same_owner_capability(capability_store):
    from bisheng.dsh.domain.services.model_catalog import _project_visible_models

    state = capability_store
    state.persisted[1, 7] = '{"vision":false}'
    model = SimpleNamespace(id=7, tenant_id=1, model_name="m", name="m")
    server = SimpleNamespace(id=1, tenant_id=1, name="owner", type="openai")
    with profile_scope(69):
        rows = await _project_visible_models(SimpleNamespace(models=[]), [(model, server)], {7})
        assert rows[0].visual is False
        state.persisted[1, 7] = '{"vision":true}'
        rows = await _project_visible_models(SimpleNamespace(models=[]), [(model, server)], {7})
        assert rows[0].visual is True


async def test_legacy_visual_reads_only_local_rows_in_native_sqlite(monkeypatch):
    from contextlib import asynccontextmanager

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core import database
    from bisheng.core.database import tenant_filter
    from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    table = TenantSystemModelConfig.__table__
    tenant_filter.register_tenant_filter_events()
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: sa.MetaData().create_all(sync, tables=[table]))
        await connection.execute(
            table.insert(),
            [
                {"tenant_id": 1, "key": "linsight_llm", "value": '{"models":[{"id":"7","visual":true}]}'},
                {"tenant_id": 69, "key": "linsight_llm", "value": '{"models":[{"id":"7","visual":false}]}'},
            ],
        )
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {table.name})

    @asynccontextmanager
    async def session_scope():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(database, "get_async_db_session", session_scope)
    try:
        with profile_scope(69):
            assert await vision.legacy_visual(7, 1) is True
            assert await vision.legacy_visual(7, 69) is False
            assert await vision.legacy_visual(7, 70) is None  # never Root fallback
        async with engine.connect() as connection:
            assert await connection.scalar(sa.select(sa.func.count()).select_from(table)) == 2
    finally:
        await engine.dispose()


async def test_platform_vision_management_does_not_require_enabled_dsh(monkeypatch, capability_store):
    from bisheng.common.services import config_service
    from bisheng.dsh import admin_runtime
    from bisheng.dsh.api.endpoints import admin

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=SimpleNamespace(enabled=False)))
    authorize = AsyncMock(return_value=(None, 69))
    monkeypatch.setattr(admin_runtime, "authorize_admin", authorize)
    monkeypatch.setattr(
        admin, "get_runtime", AsyncMock(side_effect=AssertionError("DSH runtime must not be constructed"))
    )
    service = await admin.get_model_management()
    with profile_scope(69):
        row = await service.model_vision(90, 7)
    assert row["model_id"] == 7 and row["owner_tenant_id"] == 1
    authorize.assert_awaited_once_with(90, None)
