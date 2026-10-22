"""覆盖 AC: AC-03、AC-04、AC-13、AC-14、AC-15、AC-48. Signed HTTP plus real SQL ledger."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json, signed_headers
from test.app_runtime.test_runtime_kubernetes_repository import UID
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import REF, document
from test.app_runtime.test_runtime_kubernetes_service import control as control

PREFIX = "/api/v1/internal/app-runtime/v2"


@pytest.fixture
async def api_client(control, monkeypatch):
    from bisheng.app_runtime.api.endpoints import runtime_delivery as authentication
    from bisheng.app_runtime.api.endpoints import runtime_kubernetes as api

    svc, repository, op = control
    keys = {
        role: {"secret": "fixture-" + role, "roles": [role], "node_id": "node-a"}
        for role in ("manager", "admission", "entry")
    }
    keys["other-node"] = {"secret": "fixture-other-node", "roles": ["admission"], "node_id": "node-b"}
    keys["mixed"] = {"secret": "fixture-mixed", "roles": ["manager", "admission"], "node_id": "node-a"}
    seen = set()
    state = {"nonce_available": True}

    async def nonce_store(key, ttl):
        assert ttl == 120
        if not state["nonce_available"]:
            raise RuntimeError("fixture nonce store unavailable")
        if key in seen:
            return False
        seen.add(key)
        return True

    runtime_settings = SimpleNamespace(enabled=True, runtime_service_keys=keys)
    monkeypatch.setattr(authentication, "settings", SimpleNamespace(app_runtime=runtime_settings))
    monkeypatch.setattr(authentication, "consume_runtime_nonce", nonce_store)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.service] = lambda: svc
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:

        async def send(method, path, body=None, *, role="manager", nonce=None, tamper=False):
            raw = canonical_json(body) if body is not None else b""
            target = PREFIX + path
            headers = signed_headers(method, target, raw, key_id=role, secret=keys[role]["secret"], nonce=nonce)
            headers["Content-Type"] = "application/json"
            return await client.request(method, target, content=raw + (b" " if tamper else b""), headers=headers)

        yield SimpleNamespace(send=send, svc=svc, repo=repository, op=op, state=state, settings=runtime_settings)


async def create(api_client):
    response = await api_client.send("POST", "/resources", document(api_client.op))
    assert response.status_code == 200, response.text
    return response.json()


async def test_registered_routes_are_wired_in_the_production_module_router():
    from bisheng.app_runtime.api.router import router

    paths = {route.path for route in router.routes}
    assert {
        "/internal/app-runtime/v2/controllers/claim",
        "/internal/app-runtime/v2/controllers/renew",
        "/internal/app-runtime/v2/resources",
        "/internal/app-runtime/v2/resources/{resource_ref}/observations",
        "/internal/app-runtime/v2/admission/plans/{resource_ref}",
    } <= paths


async def test_controller_claim_and_renew_are_signed_and_epoch_checked(api_client):
    claim = {"holder_id": "controller-a", "expected_epoch": 1}
    response = await api_client.send("POST", "/controllers/claim", claim)
    assert response.status_code == 200, response.text
    assert response.json()["controller_epoch"] == 1
    assert (
        await api_client.send("POST", "/controllers/renew", {"holder_id": "controller-a", "controller_epoch": 1})
    ).status_code == 200
    assert (await api_client.send("POST", "/controllers/claim", {**claim, "holder_id": "other"})).status_code == 409
    assert (
        await api_client.send("POST", "/controllers/renew", {"holder_id": "controller-a", "controller_epoch": True})
    ).status_code == 422


async def test_resource_intent_is_visible_to_the_separate_readonly_principal(api_client):
    created = await create(api_client)
    assert created["uid"] is None and created["resource_ref"] == REF
    before = (await api_client.repo.get(RuntimeExecutionResource, REF)).model_dump()
    response = await api_client.send("GET", f"/admission/plans/{REF}", role="admission")
    assert response.status_code == 200, response.text
    assert response.json()["allow_create"] is True
    assert "tenant_id" not in response.json()
    assert (await api_client.repo.get(RuntimeExecutionResource, REF)).model_dump() == before


@pytest.mark.parametrize("role", ["admission", "entry", "mixed"])
async def test_only_the_independent_manager_role_can_register(api_client, role):
    assert (await api_client.send("POST", "/resources", document(api_client.op), role=role)).status_code == 403
    assert await api_client.repo.find(RuntimeExecutionResource, operation_id=api_client.op.id) == []


@pytest.mark.parametrize("role", ["manager", "entry", "mixed", "other-node"])
async def test_plan_reader_is_role_and_node_bound(api_client, role):
    await create(api_client)
    response = await api_client.send("GET", f"/admission/plans/{REF}", role=role)
    assert response.status_code in {403, 404}, response.text


async def test_signed_command_replay_and_body_tampering_fail_closed(api_client):
    body = document(api_client.op)
    first = await api_client.send("POST", "/resources", body, nonce="0" * 32)
    assert first.status_code == 200
    assert (await api_client.send("POST", "/resources", body, nonce="0" * 32)).status_code == 403
    assert (await api_client.send("POST", "/resources", body, tamper=True)).status_code == 403


async def test_signature_store_unknown_does_not_allow_a_resource(api_client):
    api_client.state["nonce_available"] = False
    response = await api_client.send("POST", "/resources", document(api_client.op))
    assert response.status_code >= 500
    assert "fixture nonce" not in response.text
    assert await api_client.repo.find(RuntimeExecutionResource, operation_id=api_client.op.id) == []


async def test_resource_observation_keeps_uid_and_refuses_unknown_stop(api_client):
    await create(api_client)
    body = {"action": "bind", "holder_id": "controller-a", "controller_epoch": 1, "uid": UID, "node_name": "worker-a"}
    path = f"/resources/{REF}/observations"
    assert (await api_client.send("POST", path, body)).status_code == 200
    unknown = {
        "action": "stopped",
        "holder_id": "controller-a",
        "controller_epoch": 1,
        "evidence": {"evidence_kind": "unknown", "uid": UID},
    }
    assert (await api_client.send("POST", path, unknown)).status_code == 409
    assert (await api_client.repo.get(RuntimeExecutionResource, REF)).stop_state != "confirmed"


async def test_unknown_parameters_and_disabled_runtime_do_not_create_resources(api_client):
    body = document(api_client.op)
    assert (await api_client.send("POST", "/resources", {**body, "tenant_id": 2})).status_code == 422
    assert (await api_client.send("POST", "/resources", {**body, "template": {"metadata": None}})).status_code == 409
    api_client.settings.enabled = False
    assert (await api_client.send("POST", "/resources", body)).status_code == 403
    assert await api_client.repo.find(RuntimeExecutionResource, operation_id=api_client.op.id) == []


async def test_manager_recovery_reads_are_node_bound_and_do_not_require_a_live_operation(api_client):
    await create(api_client)
    response = await api_client.send("GET", f"/resources/{REF}")
    assert response.status_code == 200 and response.json()["purpose"] == "serve"
    response = await api_client.send("GET", f"/resources?operation_id={api_client.op.id}")
    assert response.status_code == 200 and len(response.json()["resources"]) == 1
    assert (await api_client.send("GET", f"/resources/{REF}", role="admission")).status_code == 403
    assert (
        await api_client.send("GET", f"/resources?operation_id={api_client.op.id}", role="entry")
    ).status_code == 403
