"""F016 T04: edit one model's price from the user-selectable model table."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.common.errcode.llm import ModelPricingConflictError, ModelPricingInvalidError
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError, LLMModelSharedReadonlyError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.pricing import service
from bisheng.llm.domain.repositories import model_pricing_repository as repository

QWEN_MAX = {"currency": "CNY", "input": "2.4", "cache_read": "0.48", "cache_write": "3", "output": "9.6"}
STORED = {
    **QWEN_MAX,
    "source": "CATALOG",
    "catalog_key": "qwen/qwen-max",
    "catalog_version": "2026-11-16",
    "ref_key": None,
    "revision": 3,
}
TENANT = 101


async def test_route_passes_the_verified_admin_model_and_body():
    from bisheng.llm.api import pricing

    app = FastAPI()
    app.include_router(pricing.router, prefix="/api/v1")
    admin = object()
    app.dependency_overrides[UserPayload.get_tenant_admin_user] = lambda: admin
    saved = AsyncMock(return_value={**STORED, "input": "6", "revision": 4})
    original = pricing.save_model_pricing
    pricing.save_model_pricing = saved
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            body = {**QWEN_MAX, "input": "6", "revision": 3}
            response = await client.put("/api/v1/llm/models/7/pricing", json=body)
            assert response.status_code == 200 and response.json()["data"]["revision"] == 4
            saved.assert_awaited_once_with(admin, 7, body)
            assert (await client.put("/api/v1/llm/models/0/pricing", json=body)).status_code == 422
            assert (await client.put("/api/v1/llm/models/7/pricing", json=["6"])).status_code == 422
    finally:
        pricing.save_model_pricing = original


@pytest.fixture
def lookup(monkeypatch):
    from bisheng.llm.domain.models.llm_server import LLMDao

    state = SimpleNamespace(
        model=SimpleNamespace(id=7, server_id=2), server=SimpleNamespace(id=2, tenant_id=TENANT), saved=[]
    )

    async def save(model_id, resolve):
        state.saved.append(model_id)
        return resolve("qwen", "qwen-max", STORED)

    monkeypatch.setattr(LLMDao, "aget_model_by_id", AsyncMock(side_effect=lambda *_: state.model))
    monkeypatch.setattr(LLMDao, "aget_server_by_id", AsyncMock(side_effect=lambda *_: state.server))
    monkeypatch.setattr(repository, "asave_model_pricing", save)
    invalidate = Mock()
    monkeypatch.setattr("bisheng.llm.domain.utils.invalidate_llm_info_cache", invalidate)
    state.invalidate = invalidate
    token = current_tenant_id.set(TENANT)
    yield state
    current_tenant_id.reset(token)


async def test_service_resolves_against_the_locked_price_and_evicts_the_model_cache(lookup):
    result = await service.save_model_pricing(object(), 7, {**QWEN_MAX, "input": "6", "revision": 3})
    assert (result["input"], result["source"], result["revision"]) == ("6", "MANUAL", 4)
    assert lookup.saved == [7]
    lookup.invalidate.assert_called_once_with(model_id=7)


async def test_service_rejects_a_stale_revision(lookup):
    with pytest.raises(ModelPricingConflictError):
        await service.save_model_pricing(object(), 7, {**QWEN_MAX, "input": "6", "revision": 2})
    lookup.invalidate.assert_not_called()


async def test_root_shared_model_is_read_only_for_a_child_and_missing_models_stay_hidden(lookup):
    lookup.server.tenant_id = 1
    with pytest.raises(LLMModelSharedReadonlyError):
        await service.save_model_pricing(object(), 7, QWEN_MAX)
    lookup.model = None
    with pytest.raises(LLMModelNotAccessibleError):
        await service.save_model_pricing(object(), 7, QWEN_MAX)
    with pytest.raises(ModelPricingInvalidError):
        await service.save_model_pricing(object(), 7, None)
    assert lookup.saved == []


@pytest.fixture
async def store(monkeypatch):
    """Real provider lock and compare-and-swap on SQLite; only the three tables involved exist."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    tables = [LLMServer.__table__, LLMModel.__table__, KnowledgeOperationPlan.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: sa.MetaData().create_all(sync, tables=tables))
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {t.name for t in tables}
    )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(repository, "get_async_db_session", sessions)
    async with sessions() as session, session.begin():
        session.add(LLMServer(id=2, tenant_id=TENANT, name="qwen", type="qwen"))
        session.add(
            LLMModel(
                id=7,
                tenant_id=TENANT,
                server_id=2,
                name="m",
                model_name="qwen-max",
                model_type="llm",
                config={"max_tokens": 1000, "pricing": STORED},
            )
        )
        session.add(
            LLMModel(
                id=8,
                tenant_id=TENANT,
                server_id=2,
                name="e",
                model_name="text-embedding",
                model_type="embedding",
                config={},
            )
        )
    token = current_tenant_id.set(TENANT)
    yield SimpleNamespace(engine=engine, sessions=sessions)
    current_tenant_id.reset(token)
    await engine.dispose()


def _resolve(incoming):
    return lambda server_type, name, stored: service.resolve_model_pricing(
        server_type, name, incoming=incoming, existing=stored
    )


async def _config(store, model_id):
    async with store.sessions() as session:
        return (await session.exec(sa.select(LLMModel.config).where(LLMModel.id == model_id))).one()[0]


async def test_lock_then_compare_and_swap_keeps_the_rest_of_the_config(store):
    saved = await repository.asave_model_pricing(7, _resolve({**QWEN_MAX, "output": "40", "revision": 3}))
    assert (saved["output"], saved["source"], saved["revision"]) == ("40", "MANUAL", 4)
    config = await _config(store, 7)
    assert config["pricing"] == saved and config["max_tokens"] == 1000
    with pytest.raises(ModelPricingConflictError):
        await repository.asave_model_pricing(7, _resolve({**QWEN_MAX, "revision": 3}))
    assert (await _config(store, 7))["pricing"]["revision"] == 4


async def test_only_llm_models_in_the_callers_tenant_take_a_price(store):
    with pytest.raises(ModelPricingInvalidError):
        await repository.asave_model_pricing(8, _resolve(QWEN_MAX))
    token = current_tenant_id.set(202)
    try:
        with pytest.raises(LLMModelNotAccessibleError):
            await repository.asave_model_pricing(7, _resolve({**QWEN_MAX, "revision": 3}))
    finally:
        current_tenant_id.reset(token)
    assert (await _config(store, 7))["pricing"] == STORED


async def test_a_provider_operation_in_flight_blocks_the_price_edit(store):
    async with store.sessions() as session, session.begin():
        session.add(
            KnowledgeOperationPlan(
                id="op-1",
                tenant_id=TENANT,
                actor_user_id=1,
                actor_reference="{}",
                operation="model_share_server",
                target_manifest="[]",
                target_revisions="[]",
                source_revisions="[]",
                parameters="{}",
                request_hash="h" * 64,
                impact="{}",
                plan_digest="d" * 64,
                expires_at=datetime(2099, 1, 1),
                operation_id="share",
                model_server_id=2,
                model_execution_state="RESERVED",
            )
        )
    with pytest.raises(KnowledgeProcessingConflictError):
        await repository.asave_model_pricing(7, _resolve({**QWEN_MAX, "output": "40", "revision": 3}))
    assert (await _config(store, 7))["pricing"] == STORED
