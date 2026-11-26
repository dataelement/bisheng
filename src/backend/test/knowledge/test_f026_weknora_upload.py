"""Signed-user WeKnora upload port: JWT principal from instance secret, dual budgets."""

from hashlib import sha256
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import httpx
import jwt
import pytest

from bisheng.knowledge.application import provider_upload_v1 as uploads
from bisheng.knowledge.application import provider_weknora_upload as wk
from bisheng.knowledge.application.provider_instance_admin import seal_api_key
from bisheng.knowledge.application.provider_upload_quota import UploadIdentity
from bisheng.knowledge.infrastructure.providers.registry import PortContext

SECRET = "fixture-hmac-secret-32bytes-min!!"
ROUTE = NS(
    tenant_id=3,
    space_id=14,
    provider_key="weknora",
    capability_revision=7,
    instance_id=1,
    generation=2,
    remote_scope_id="9",
    remote_kb_id="lib-1",
)


def identity(**changes):
    return UploadIdentity(
        **(
            {
                "tenant_id": 3,
                "user_id": 17,
                "space_id": 14,
                "generation": 2,
                "instance_id": 1,
                "remote_scope_id": "9",
                "remote_kb_id": "lib-1",
                "request_key": "req-1",
                "operation_id": "op-1",
                "file_id": 12,
                "document_id": 100,
                "version_id": 3,
                "byte_count": 3,
                "sha256": sha256(b"abc").hexdigest(),
            }
            | changes
        )
    )


@pytest.fixture
def budgets(monkeypatch):
    from bisheng.role.domain.services import quota_service as qs

    monkeypatch.setattr(qs.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=1024))
    monkeypatch.setattr(qs.QuotaService, "get_tenant_storage_used_bytes", AsyncMock(return_value=10))
    monkeypatch.setattr(qs.QuotaService, "get_tenant_storage_remaining_bytes", AsyncMock(return_value=990))


def test_upload_deployments_registers_weknora_resolver():
    assert uploads._UPLOAD_DEPLOYMENTS["weknora"] is wk.resolve_weknora_upload


def test_mint_external_user_token_claims():
    token = wk.mint_external_user_token(secret=SECRET, weknora_tenant_id=9, external_user_id="17")
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], audience="weknora")
    assert (claims["sub"], claims["tenant_id"], claims["aud"]) == ("17", 9, "weknora")


async def test_resolve_requires_instance_upload_secret(monkeypatch, budgets):
    monkeypatch.setattr(wk, "_instance_upload_binding", AsyncMock(return_value=None))
    assert await wk.resolve_weknora_upload(ROUTE, 17) is None

    monkeypatch.setattr(
        wk,
        "_instance_upload_binding",
        AsyncMock(return_value=("http://192.168.1.2:18080", seal_api_key("api-key"), SECRET)),
    )
    admission = await wk.resolve_weknora_upload(ROUTE, 17)
    assert isinstance(admission, uploads.UploadAdmission)
    assert (admission.user_limit, admission.tenant_limit) == (1024, 1000)
    assert isinstance(admission.port, wk.WeKnoraUploadPort)
    assert admission.port.user_id == 17
    assert admission.port.context.operation == "upload"
    assert admission.port.capability_revision == 7


async def test_resolve_rejects_non_positive_budgets(monkeypatch):
    from bisheng.role.domain.services import quota_service as qs

    monkeypatch.setattr(
        wk,
        "_instance_upload_binding",
        AsyncMock(return_value=("http://192.168.1.2:18080", seal_api_key("api-key"), SECRET)),
    )
    monkeypatch.setattr(qs.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=0))
    monkeypatch.setattr(qs.QuotaService, "get_tenant_storage_used_bytes", AsyncMock(return_value=0))
    monkeypatch.setattr(qs.QuotaService, "get_tenant_storage_remaining_bytes", AsyncMock(return_value=100))
    assert await wk.resolve_weknora_upload(ROUTE, 17) is None


async def test_send_attaches_signed_token_and_parses_stock_knowledge_envelope(monkeypatch):
    captured = {}

    def handle(request: httpx.Request):
        captured["token"] = request.headers.get("X-External-User-Token")
        captured["api"] = request.headers.get("X-API-Key")
        captured["body"] = request.content
        assert request.url.path.endswith("/knowledge-bases/lib-1/knowledge/file")
        # Stock WeKnora returns Knowledge, not a managed receipt echo.
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": "remote-doc",
                    "knowledge_base_id": "lib-1",
                    "file_name": "a.txt",
                    "file_size": 3,
                    "parse_status": "pending",
                },
            },
        )

    async def fake_client(self, identity):
        return httpx.AsyncClient(
            base_url="https://wk.test/api/v1/",
            headers={
                "X-API-Key": "api-key",
                "X-External-User-Token": self._token(identity),
            },
            transport=httpx.MockTransport(handle),
            trust_env=False,
            follow_redirects=False,
        )

    monkeypatch.setattr(wk.WeKnoraUploadPort, "_client", fake_client)
    monkeypatch.setattr(wk.WeKnoraUploadPort, "_filename", AsyncMock(return_value="a.txt"))
    monkeypatch.setattr(wk.WeKnoraUploadPort, "_folder_path", AsyncMock(return_value=""))

    port = wk.WeKnoraUploadPort(
        context=PortContext(
            tenant_id=3,
            space_id=14,
            provider_key="weknora",
            operation="upload",
            instance_id=1,
            generation=2,
            remote_scope_id="9",
            remote_kb_id="lib-1",
        ),
        capability_revision=7,
        user_id=17,
        hmac_secret=SECRET,
        timeout_seconds=30.0,
    )

    async def chunks():
        yield b"abc"

    receipt = await port.send(identity=identity(), chunks=chunks(), chunking={"chunk_size": 512, "chunk_overlap": 0})
    claims = jwt.decode(captured["token"], SECRET, algorithms=["HS256"], audience="weknora")
    assert claims["sub"] == "17" and claims["tenant_id"] == 9
    assert captured["api"] == "api-key"
    assert receipt.state == "accepted" and receipt.remote_id == "remote-doc"
    # Root-level uploads stay flat: no folder_path on the remote row.
    assert b'name="fileName"' not in captured["body"]


class _Result:
    def __init__(self, *, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = list(rows)

    def scalar(self):
        return self._scalar

    def all(self):
        return list(self._rows)


class _FolderSession:
    def __init__(self, *, path, ancestors):
        self._results = [_Result(scalar=path), _Result(rows=ancestors)]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):
        return self._results.pop(0)


def _port() -> wk.WeKnoraUploadPort:
    return wk.WeKnoraUploadPort(
        context=PortContext(
            tenant_id=3,
            space_id=14,
            provider_key="weknora",
            operation="upload",
            instance_id=1,
            generation=2,
            remote_scope_id="9",
            remote_kb_id="lib-1",
        ),
        capability_revision=7,
        user_id=17,
        hmac_secret=SECRET,
        timeout_seconds=30.0,
    )


async def test_folder_path_mirrors_local_dir_chain(monkeypatch):
    from types import SimpleNamespace as Row

    monkeypatch.setattr(
        wk,
        "get_async_db_session",
        lambda: _FolderSession(
            path="/5/9",
            ancestors=[Row(id=5, file_name="spec24_forecast"), Row(id=9, file_name="sub")],
        ),
    )
    assert await _port()._folder_path(identity()) == "spec24_forecast/sub"


async def test_folder_path_is_empty_when_an_ancestor_is_missing(monkeypatch):
    from types import SimpleNamespace as Row

    monkeypatch.setattr(
        wk,
        "get_async_db_session",
        lambda: _FolderSession(path="/5/9", ancestors=[Row(id=5, file_name="spec24_forecast")]),
    )
    assert await _port()._folder_path(identity()) == ""


async def test_folder_upload_sends_path_qualified_file_name(monkeypatch):
    captured = {}

    def handle(request: httpx.Request):
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": "remote-doc",
                    "knowledge_base_id": "lib-1",
                    "file_name": "a.txt",
                    "file_size": 3,
                    "parse_status": "pending",
                },
            },
        )

    async def fake_client(self, identity):
        return httpx.AsyncClient(
            base_url="https://wk.test/api/v1/",
            headers={"X-External-User-Token": self._token(identity)},
            transport=httpx.MockTransport(handle),
            trust_env=False,
            follow_redirects=False,
        )

    monkeypatch.setattr(wk.WeKnoraUploadPort, "_client", fake_client)
    monkeypatch.setattr(wk.WeKnoraUploadPort, "_filename", AsyncMock(return_value="a.txt"))
    monkeypatch.setattr(wk.WeKnoraUploadPort, "_folder_path", AsyncMock(return_value="spec24_forecast/sub"))

    async def chunks():
        yield b"abc"

    await _port().send(identity=identity(), chunks=chunks(), chunking=None)
    body = captured["body"]
    assert b'name="fileName"' in body
    assert b"\r\n\r\nspec24_forecast/sub/a.txt\r\n" in body


async def test_lookup_plain_404_is_not_not_received(monkeypatch):
    async def fake_client(self, identity):
        return httpx.AsyncClient(
            base_url="https://wk.test/api/v1/",
            headers={"X-External-User-Token": self._token(identity)},
            transport=httpx.MockTransport(lambda r: httpx.Response(404)),
            trust_env=False,
            follow_redirects=False,
        )

    monkeypatch.setattr(wk.WeKnoraUploadPort, "_client", fake_client)
    port = wk.WeKnoraUploadPort(
        context=PortContext(
            tenant_id=3,
            space_id=14,
            provider_key="weknora",
            operation="upload",
            instance_id=1,
            generation=2,
            remote_scope_id="9",
            remote_kb_id="lib-1",
        ),
        capability_revision=7,
        user_id=17,
        hmac_secret=SECRET,
        timeout_seconds=30.0,
    )
    assert await port.lookup(identity=identity()) is None


async def test_capabilities_supported_when_signed_port_admits(monkeypatch, budgets):
    from fastapi import FastAPI

    from bisheng.knowledge.api.endpoints import knowledge_space as api

    user = NS(tenant_id=3, user_id=17)
    actor = NS(current_tenant_id=3, subject_type="user", subject_id=17)
    svc = NS(
        login_user=user,
        _permission_actor=AsyncMock(return_value=actor),
        _require_action=AsyncMock(),
        require_upload_container=AsyncMock(return_value=NS(tenant_id=3)),
        upload_application_factory=Mock(),
    )
    monkeypatch.setattr(uploads, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(uploads, "resolve_space_route", AsyncMock(return_value=ROUTE))
    monkeypatch.setattr(api.provider, "resolve_space_route", AsyncMock(return_value=ROUTE))
    monkeypatch.setattr(
        wk,
        "_instance_upload_binding",
        AsyncMock(return_value=("http://192.168.1.2:18080", seal_api_key("api-key"), SECRET)),
    )
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.get_knowledge_space_service] = lambda: svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        caps = (await client.get("/api/v1/knowledge/space/14/capabilities")).json()["data"]["capabilities"]
    assert caps["upload"] == caps["folder_upload"] == "supported"


def test_unseal_rejects_missing_or_plain_ref():
    assert wk._unseal_upload_secret(None) is None
    assert wk._unseal_upload_secret("plain") is None
    assert wk._unseal_upload_secret(seal_api_key(SECRET)) == SECRET
