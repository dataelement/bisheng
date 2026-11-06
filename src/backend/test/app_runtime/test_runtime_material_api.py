"""覆盖 AC: AC-15、AC-28、AC-46、AC-47、AC-51. Actual signed material HTTP requests."""

import ast
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact
from bisheng.app_runtime.domain.services import runtime_material_protocol as wire
from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json
from bisheng.app_runtime.domain.services.runtime_protocol import signed_headers as hmac_headers
from bisheng.utils import http_middleware
from test.app_runtime.test_runtime_kubernetes_repository import UID
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import control as control
from test.app_runtime.test_runtime_material_service import KEY_ID, P
from test.app_runtime.test_runtime_material_service import materials as materials
from test.app_runtime.test_runtime_material_transfers import DATA, upload
from test.app_runtime.test_runtime_material_transfers import transfers as transfers

C = "/api/v1/internal/app-runtime/v2/material-delegations"


@pytest.fixture
async def api_client(transfers, monkeypatch):
    from bisheng.app_runtime.api.endpoints import runtime_delivery as authentication
    from bisheng.app_runtime.api.endpoints import runtime_material as api

    t = transfers
    keys = {
        name: {"secret": "fixture-material-" + name, "roles": [name], "node_id": "node-a"}
        for name in ("manager", "entry", "admission")
    }
    settings = SimpleNamespace(enabled=True, runtime_service_keys=keys)
    monkeypatch.setattr(authentication, "settings", SimpleNamespace(app_runtime=settings))

    async def nonce_store(*args):
        return True

    monkeypatch.setattr(authentication, "consume_runtime_nonce", nonce_store)
    monkeypatch.setattr(http_middleware, "_set_tenant_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "runtime_enabled", lambda: settings.enabled)
    app = FastAPI()
    app.add_middleware(http_middleware.CustomMiddleware)
    app.include_router(api.router)
    app.dependency_overrides[api.authority] = lambda: t.m.svc
    app.dependency_overrides[api.transfers] = lambda: t.svc
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        follow_redirects=False,
    ) as client:

        async def control_send(method, path, body, role="manager"):
            raw = canonical_json(body)
            headers = hmac_headers(method, path, raw, key_id=role, secret=keys[role]["secret"])
            return await client.request(
                method, path, content=raw, headers={**headers, "Content-Type": "application/json"}
            )

        async def send(
            method,
            target,
            *,
            grant,
            session=None,
            body=None,
            raw=None,
            extra_headers=None,
            tamper=False,
            headers_only=None,
        ):
            raw = canonical_json(body) if body is not None else (raw or b"")
            headers = (
                wire.signed_headers(
                    method,
                    target,
                    raw,
                    private_key=t.m.signer,
                    delegation_id=grant["delegation_id"],
                    key_id=KEY_ID,
                    pod_uid=UID,
                    timestamp=int(t.m.clock["now"].replace(tzinfo=UTC).timestamp()),
                    nonce=uuid4().hex,
                    ticket=session["ticket"] if session else "",
                )
                if headers_only is None
                else headers_only
            )
            if extra_headers:
                headers = list(headers.items()) + extra_headers
            return await client.request(method, target, content=raw + (b" " if tamper else b""), headers=headers)

        yield SimpleNamespace(t=t, client=client, send=send, control=control_send, settings=settings)


async def grant(a, *, prepare=False):
    from test.app_runtime.test_runtime_material_service import bind, reframe

    if prepare:
        prior = await a.t.m.repo.get(RuntimeArtifact, a.t.m.content["compiled_artifact_id"])
        prior.sha256 = "f" * 64
        await a.t.m.repo.save(prior)
        await reframe(a.t.m, "prepare", "prepare-upload")
    response = await a.control("POST", C, a.t.m.body)
    assert response.status_code == 200, response.text
    result = response.json()
    await bind(a.t.m, result)
    return result


async def download(a, g):
    response = await a.send(
        "POST",
        P + "/exchange",
        grant=g,
        body={"action": "download", "artifact_id": a.t.m.content["compiled_artifact_id"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_production_main_mounts_the_router_without_an_outer_api_prefix():
    main = Path(__file__).parents[2] / "bisheng/main.py"
    tree = ast.parse(main.read_text())
    names = {
        item.asname or item.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "bisheng.app_runtime.api.endpoints.runtime_material"
        for item in node.names
        if item.name == "router"
    }
    assert names
    mounts = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "include_router"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in names
    ]
    assert len(mounts) == 1 and all(kw.arg != "prefix" for kw in mounts[0].keywords)


async def test_download_root_path_range_status_and_no_minio_link(api_client):
    a = api_client
    g = await grant(a)
    s = await download(a, g)
    assert "ticket" in s and "url" not in s and "object_key" not in s
    path = P + "/transfers/" + s["transfer_id"]
    status = await a.send("GET", path, grant=g, session=s)
    assert status.status_code == 200 and "ticket" not in status.json()
    content = await a.send("GET", path + "/content?length=4&offset=2", grant=g, session=s)
    assert content.status_code == 206 and content.content == DATA[2:6]
    assert content.headers["content-range"] == "bytes 2-5/10" and content.headers["content-length"] == "4"
    eof = await a.send("GET", path + "/content?length=1&offset=10", grant=g, session=s)
    assert eof.status_code == 416
    wrong_prefix = await a.client.get("/api/v1" + path)
    assert wrong_prefix.status_code == 404


async def test_actual_http_upload_and_repeat_finalize(api_client):
    a = api_client
    g = await grant(a, prepare=True)
    response = await a.send("POST", P + "/exchange", grant=g, body={"action": "upload", **upload()})
    assert response.status_code == 200, response.text
    s = response.json()
    path = P + "/transfers/" + s["transfer_id"]
    put = await a.send("PUT", path + "/content?offset=0", grant=g, session=s, raw=DATA)
    assert put.status_code == 200 and put.json()["offset"] == 10
    for _ in range(2):
        done = await a.send(
            "POST", path + "/finalize", grant=g, session=s, body={"sha256": s["sha256"], "size_bytes": 10}
        )
        assert done.status_code == 200 and done.json()["state"] == "verified"


@pytest.mark.parametrize("role", ["entry", "admission"])
async def test_only_manager_can_register_the_public_workload_key(api_client, role):
    a = api_client
    response = await a.control("POST", C, a.t.m.body, role)
    assert response.status_code == 403


async def test_manager_binding_route_requires_previously_observed_uid(api_client):
    a = api_client
    response = await a.control("POST", C, a.t.m.body)
    g = response.json()
    path = C + "/" + g["delegation_id"] + "/bind"
    assert (await a.control("POST", path, {"pod_uid": UID})).status_code == 409
    from test.app_runtime.test_runtime_material_service import MANAGER, REF

    await a.t.m.control.observe_resource(
        MANAGER,
        REF,
        {"action": "bind", "holder_id": "controller-a", "controller_epoch": 1, "uid": UID, "node_name": "worker-a"},
    )
    assert (await a.control("POST", path, {"pod_uid": UID})).status_code == 200


@pytest.mark.parametrize(
    "extra",
    [
        [("Authorization", "Bearer fixture-app-or-obo")],
        [("X-Runtime-Key-Id", "manager")],
        [("X-Material-Key-Id", KEY_ID)],
    ],
)
async def test_material_route_rejects_mixed_or_duplicate_identity_headers(api_client, extra):
    a = api_client
    g = await grant(a)
    response = await a.send(
        "POST",
        P + "/exchange",
        grant=g,
        body={"action": "download", "artifact_id": a.t.m.content["compiled_artifact_id"]},
        extra_headers=extra,
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "raw",
    [
        b'{"action":"download","action":"upload"}',
        b'{"action":"download","artifact_id":"x","extra":1}',
        b'{"action":NaN}',
    ],
)
async def test_strict_json_shape_rejected_with_transport_400(api_client, raw):
    a = api_client
    g = await grant(a)
    response = await a.send("POST", P + "/exchange", grant=g, raw=raw)
    assert response.status_code == 400, response.text


async def test_control_size_limit_and_bad_signature_are_distinct(api_client):
    a = api_client
    g = await grant(a)
    response = await a.client.post(P + "/exchange", content=b" " * (wire.CONTROL_LIMIT + 1))
    assert response.status_code == 413
    tamper = await a.send(
        "POST",
        P + "/exchange",
        grant=g,
        body={"action": "download", "artifact_id": a.t.m.content["compiled_artifact_id"]},
        tamper=True,
    )
    assert tamper.status_code == 401


async def test_runtime_disabled_and_unknown_nonce_fail_closed_without_detail(api_client):
    a = api_client
    g = await grant(a)
    a.t.m.clock["nonce_available"] = False
    response = await a.send(
        "POST",
        P + "/exchange",
        grant=g,
        body={"action": "download", "artifact_id": a.t.m.content["compiled_artifact_id"]},
    )
    assert response.status_code == 503 and "fixture-secret" not in response.text
    a.settings.enabled = False
    response = await a.send(
        "POST",
        P + "/exchange",
        grant=g,
        body={"action": "download", "artifact_id": a.t.m.content["compiled_artifact_id"]},
    )
    assert response.status_code == 403


async def test_storage_exception_does_not_leak_through_global_business_error_handler(api_client):
    a = api_client
    g = await grant(a, prepare=True)
    response = await a.send("POST", P + "/exchange", grant=g, body={"action": "upload", **upload()})
    s = response.json()

    async def fail(*args):
        raise OSError("fixture-storage-password-detail")

    a.t.objects.put = fail
    response = await a.send(
        "PUT", P + "/transfers/" + s["transfer_id"] + "/content?offset=0", grant=g, session=s, raw=DATA
    )
    assert response.status_code == 503 and "fixture-storage-password" not in response.text
