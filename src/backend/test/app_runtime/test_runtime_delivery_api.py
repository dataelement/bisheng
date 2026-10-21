"""Internal HTTP contracts use actual domain services and SQL persistence."""

import hashlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from test.app_runtime.test_runtime_artifacts import MemoryObjects
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


@pytest.fixture
async def runtime_api(runtime_repo, monkeypatch):
    from bisheng.app_runtime.api.endpoints import runtime_delivery as api
    from bisheng.app_runtime.domain.services.runtime_artifact_service import RuntimeArtifactService
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService
    from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json, signed_headers

    keys = {
        role: {"secret": "fixture-" + role, "roles": [role], "node_id": "node-a"}
        for role in ["platform", "manager", "entry", "egress"]
    }
    keys["other-node"] = {"secret": "fixture-other", "roles": ["manager"], "node_id": "node-b"}
    seen = set()

    async def consume(key, ttl):
        if key in seen:
            return False
        seen.add(key)
        return True

    async def app_loader(app_id):
        return SimpleNamespace(id=app_id, tenant_id=1, state="draft")

    svc = RuntimeOperationService(
        runtime_repo, RuntimeArtifactService(runtime_repo, MemoryObjects()), nonce_store=consume, app_loader=app_loader
    )
    monkeypatch.setattr(api, "consume_runtime_nonce", consume)
    monkeypatch.setattr(
        api, "settings", SimpleNamespace(app_runtime=SimpleNamespace(enabled=True, runtime_service_keys=keys))
    )
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.service] = lambda: svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:

        async def request(method, path, role="manager", json=None, body=None, extra=None):
            raw = canonical_json(json) if json is not None else (body or b"")
            path = "/api/v1/internal/app-runtime/v2" + path
            headers = signed_headers(method, path, raw, key_id=role, secret=keys[role]["secret"])
            if json is not None:
                headers["Content-Type"] = "application/json"
            headers.update(extra or {})
            return await client.request(method, path, headers=headers, content=raw)

        async def create(document):
            from bisheng.app_runtime.domain.schemas.runtime_delivery import OperationInput

            return await svc.create(OperationInput.model_validate(document))

        request.create = create
        yield request


async def test_operation_idempotency_and_bound_node(runtime_api):
    """AC-06, AC-35, AC-36: repeated publication shares one node-bound operation."""
    payload = {
        "idempotency_key": "request-a",
        "app_id": "app-a",
        "kind": "prepare",
        "node_id": "node-a",
        "generation": 1,
        "owner_epoch": 1,
    }
    created = await runtime_api.create(payload)
    op = created["operation_id"]
    assert (await runtime_api.create(payload))["operation_id"] == op
    # Business intents can only be created by an authenticated backend use case.
    assert (await runtime_api("POST", "/operations", "platform", json=payload)).status_code == 404
    assert (await runtime_api("GET", f"/operations/{op}")).status_code == 200
    assert (await runtime_api("GET", f"/operations/{op}", "other-node")).status_code == 404
    assert (await runtime_api("GET", f"/operations/{op}", "entry")).status_code == 403
    payload["payload"] = {"changed": True}
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

    with pytest.raises(RuntimeConflict, match="idempotency_content_conflict"):
        await runtime_api.create(payload)


async def test_transfer_over_http(runtime_api):
    """AC-05, AC-07, AC-42, AC-43: content is verified before download becomes possible."""
    payload = {
        "idempotency_key": "request-b",
        "app_id": "app-a",
        "kind": "prepare",
        "node_id": "node-a",
        "generation": 1,
        "owner_epoch": 1,
    }
    op = (await runtime_api.create(payload))["operation_id"]
    data = b"payload"
    started = await runtime_api(
        "POST",
        "/transfers",
        json={
            "operation_id": op,
            "kind": "snapshot",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        },
    )
    assert started.status_code == 200, started.text
    session = started.json()
    path = f"/transfers/{session['transfer_id']}"
    auth = {"X-Runtime-Transfer": session["ticket"]}
    assert (await runtime_api("POST", path + "/finalize", extra=auth)).status_code == 409
    assert (await runtime_api("PUT", path + "/content?offset=0", body=data, extra=auth)).status_code == 200
    confirmed = await runtime_api("POST", path + "/finalize", extra=auth)
    assert confirmed.status_code == 200 and confirmed.json()["state"] == "verified"
    download = (
        await runtime_api(
            "POST", "/downloads", json={"operation_id": op, "artifact_id": confirmed.json()["artifact_id"]}
        )
    ).json()
    response = await runtime_api(
        "GET", f"/transfers/{download['transfer_id']}/content", extra={"X-Runtime-Transfer": download["ticket"]}
    )
    assert response.content == data


async def test_route_has_no_manager_write_privilege(runtime_api):
    """AC-48, AC-49, AC-50: platform route reads are independent from the manager process."""
    response = await runtime_api("GET", "/routes/apps/app-a", "entry")
    assert response.status_code == 200 and response.json()["decision"] == "transition"
    assert (await runtime_api("GET", "/routes/apps/app-a", "manager")).status_code == 403
