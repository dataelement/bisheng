"""Coverage AC: AC-03, AC-07, AC-08, AC-52. Offline model administration stays separate from invocation."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import Session

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.core.context.tenant import (
    current_tenant_id,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    set_current_tenant_id,
)
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from test.dsh.test_subject_policy import subject_store as subject_store
from test.dsh.test_unified_policy_repository import store as store


@pytest.fixture
def governed(monkeypatch):
    from bisheng.llm.domain.services.llm import LLMDao, LLMService

    model = SimpleNamespace(id=42, tenant_id=2, server_id=8, online=False, model_type="llm")
    provider = SimpleNamespace(id=8, tenant_id=2, type="openai")
    state = SimpleNamespace(model=model, provider=provider, shares=[], service=LLMService, dao=LLMDao)

    async def read_model(identifier, *, cache=False):
        assert identifier == 42 and cache is False
        value = state.model
        return (
            value
            if value is not None and (is_tenant_filter_bypassed() or value.tenant_id == get_current_tenant_id())
            else None
        )

    async def read_provider(identifier, *, cache=False):
        assert identifier == 8 and cache is False and is_tenant_filter_bypassed()
        return state.provider

    async def shared(tenant):
        assert tenant == get_current_tenant_id() == 2
        return state.shares

    monkeypatch.setattr(LLMDao, "aget_model_by_id", AsyncMock(side_effect=read_model))
    monkeypatch.setattr(LLMDao, "aget_server_by_id", AsyncMock(side_effect=read_provider))
    monkeypatch.setattr(LLMDao, "aget_shared_server_ids_for_leaf", AsyncMock(side_effect=shared))
    token = set_current_tenant_id(2)
    try:
        yield state
    finally:
        current_tenant_id.reset(token)


async def test_offline_metadata_can_be_read_without_allowing_an_invocation(governed):
    model, provider = await governed.service.get_dsh_model_metadata_snapshot(42)
    assert model is governed.model and provider is governed.provider
    assert model.online is False
    governed.dao.aget_server_by_id.assert_awaited_once_with(8, cache=False)
    with pytest.raises(DshModelNotAllowedError):
        await governed.service.get_dsh_model_snapshot(42)


@pytest.mark.parametrize("online", [False, True])
async def test_metadata_keeps_root_share_authorization_canonical(governed, online):
    governed.model.tenant_id = governed.provider.tenant_id = 1
    governed.model.online = online
    with pytest.raises(DshModelNotAllowedError):
        await governed.service.get_dsh_model_metadata_snapshot(42)
    governed.shares = [8]
    assert (await governed.service.get_dsh_model_metadata_snapshot(42))[0] is governed.model
    if online:
        assert (await governed.service.get_dsh_model_snapshot(42))[0] is governed.model
    else:
        with pytest.raises(DshModelNotAllowedError):
            await governed.service.get_dsh_model_snapshot(42)


@pytest.mark.parametrize(
    "change", ["foreign_model", "mismatched_provider", "missing_provider", "missing_model", "embedding", "no_tenant"]
)
async def test_metadata_rejects_every_existing_ownership_and_type_failure(governed, change):
    if change == "foreign_model":
        governed.model.tenant_id = governed.provider.tenant_id = 3
        governed.shares = [8]
    elif change == "mismatched_provider":
        governed.provider.tenant_id = 3
    elif change == "missing_provider":
        governed.provider = None
    elif change == "missing_model":
        governed.model = None
    elif change == "embedding":
        governed.model.model_type = "embedding"
    token = set_current_tenant_id(None) if change == "no_tenant" else None
    try:
        with pytest.raises(DshModelNotAllowedError):
            await governed.service.get_dsh_model_metadata_snapshot(42)
    finally:
        if token is not None:
            current_tenant_id.reset(token)


async def test_online_invocation_retains_the_exact_authorized_uncached_pair(governed):
    governed.model.online = True
    model, provider = await governed.service.get_dsh_model_snapshot(42)
    assert model is governed.model and provider is governed.provider
    governed.dao.aget_model_by_id.assert_awaited_once_with(42)
    governed.dao.aget_server_by_id.assert_awaited_once_with(8, cache=False)


@pytest.fixture
async def management(store, governed, monkeypatch):
    import bisheng.core.database as database
    from bisheng.dsh.api.endpoints import unified_policy as api

    state = SimpleNamespace(allowed=True, attempts=[])

    async def authorize(actor, tenant, *_):
        state.attempts.append((actor, tenant))
        if not state.allowed or tenant != 2:
            raise HTTPException(status_code=403, detail="Management scope rejected")
        return actor, 2

    @contextmanager
    def sessions():
        with Session(store) as session:
            yield session

    monkeypatch.setattr(database, "get_sync_db_session", sessions)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.admin_user] = lambda: SimpleNamespace(user_id=20)
    app.dependency_overrides[api.get_management] = lambda: SimpleNamespace(authorize=authorize)

    @app.exception_handler(BaseErrorCode)
    async def domain_failure(request, error):
        return JSONResponse(status_code=error.HttpStatus, content={"status_code": error.Code})

    with Session(store) as session, session.begin():
        UnifiedPolicyRepository(session).initialize_model_visibility(42, 20)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(
            client=client, state=state, store=store, path="/api/v1/dsh/admin/models/42/visibility?tenant_id=2"
        )


async def test_admin_can_make_an_offline_model_private_before_online_and_cas_is_preserved(management, governed):
    response = await management.client.get(management.path)
    assert response.status_code == 200
    initial = response.json()["data"]
    assert initial["everyone"] is True and initial["version"] == 1
    desired = {
        "version": initial["version"],
        "everyone": False,
        "subjects": [{"kind": "USER", "id": 21}],
        "credit_multiplier": initial["credit_multiplier"],
    }
    response = await management.client.put(management.path, json=desired)
    assert response.status_code == 200 and response.json()["data"]["version"] == 2
    after = (await management.client.get(management.path)).json()["data"]
    assert after["everyone"] is False and after["subjects"] == [{"kind": "USER", "id": 21}]
    assert after["credit_multiplier"] == initial["credit_multiplier"]
    assert governed.model.online is False
    with pytest.raises(DshModelNotAllowedError):
        await governed.service.get_dsh_model_snapshot(42)
    stale = await management.client.put(management.path, json=desired)
    assert stale.status_code == 409
    with Session(management.store) as session:
        repository = UnifiedPolicyRepository(session)
        assert repository.visibility(42)["version"] == 2
        assert repository.effective(20).allowed_model_ids == []
        assert repository.effective(21).allowed_model_ids == [42]
    assert all(actor == 20 and tenant == 2 for actor, tenant in management.state.attempts)


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_management_authorization_precedes_metadata_or_policy_access(management, governed, method):
    management.state.allowed = False
    response = await management.client.request(method, management.path, json={"version": 1})
    assert response.status_code == 403
    governed.dao.aget_model_by_id.assert_not_awaited()
    governed.dao.aget_server_by_id.assert_not_awaited()


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_unshared_root_is_still_refused_by_the_admin_endpoint(management, governed, method):
    governed.model.tenant_id = governed.provider.tenant_id = 1
    response = await management.client.request(method, management.path, json={"version": 1})
    assert response.status_code == 403
    with Session(management.store) as session:
        assert UnifiedPolicyRepository(session).visibility(42)["version"] == 1


async def test_shared_root_offline_metadata_can_be_managed_only_in_authorized_leaf(management, governed):
    governed.model.tenant_id = governed.provider.tenant_id = 1
    governed.shares = [8]
    assert (await management.client.get(management.path)).status_code == 200
    body = {"version": 1, "everyone": False, "subjects": [{"kind": "USER", "id": 21}]}
    assert (await management.client.put(management.path, json=body)).status_code == 200
    foreign = await management.client.get(management.path.replace("tenant_id=2", "tenant_id=3"))
    assert foreign.status_code == 403
    assert governed.model.online is False
