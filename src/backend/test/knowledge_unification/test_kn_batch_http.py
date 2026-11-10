"""The real ASGI wire uses exact closed inputs and the original management pin."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.knowledge.api.endpoints import batch as wire
from bisheng.knowledge.api.endpoints import processing
from test.knowledge_unification import test_kn_batch as native

deletion_tenant, db, batch = native.deletion_tenant, native.db, native.batch


@pytest.fixture
async def client(batch, monkeypatch):
    app = FastAPI()
    app.include_router(wire.router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: batch.user
    app.dependency_overrides[wire.get_batch_application] = batch.application
    monkeypatch.setattr(processing, "resolve_management_scope", AsyncMock(return_value=SimpleNamespace(tenant_id=101)))

    @app.exception_handler(BaseErrorCode)
    async def error(request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_same_action_inspect_has_no_plan_or_root_visible_gate(client, batch):
    response = await client.post("/1/files/batch/download/inspect", json={"items": [{"id": 30, "type": "file"}]})
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["can_execute"] and "confirmation_id" not in result
    assert all(call[2] == ("download",) for call in batch.calls)


async def test_strict_pin_and_three_field_confirmation_create_native_tags(client, batch):
    body = {"items": [{"id": 30, "type": "file"}], "new_tag_names": ["on-confirm"]}
    absent = (await client.post("/1/files/batch/tag/precheck", json=body)).json()
    assert absent["status_code"] == 19703
    plan = (await client.post("/1/files/batch/tag/precheck", json=body, headers={"X-Management-Tenant": "101"})).json()[
        "data"
    ]
    confirmation = {
        "confirmation_id": plan["confirmation_id"],
        "plan_digest": plan["plan_digest"],
        "idempotency_key": "http-batch",
    }
    result = (
        await client.post("/1/files/batch/tag/confirm", json=confirmation, headers={"X-Management-Tenant": "101"})
    ).json()["data"]
    assert result["items"][0]["state"] == "succeeded" and "job_id" not in result


async def test_force_and_action_inapplicable_parameters_are_rejected(client):
    body = {"items": [{"id": 30, "type": "file"}], "force": True}
    assert (await client.post("/1/files/batch/download/inspect", json=body)).status_code == 422
    assert (
        await client.post("/1/files/batch/download/inspect", json={"items": body["items"], "tag_ids": []})
    ).status_code == 422
