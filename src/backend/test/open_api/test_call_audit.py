from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.database.models.audit_log import AuditLog
from bisheng.open_api.api import middleware as middleware_module
from bisheng.open_api.api.middleware import OpenApiAuditMiddleware
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.call_audit_service import OpenApiCallAuditService


def principal(*, actor_kind: str = "service_account", mode: str = "S") -> OpenApiPrincipal:
    is_service_account = actor_kind == "service_account"
    return OpenApiPrincipal(
        credential_id=5,
        actor_kind=actor_kind,
        actor_id=7,
        actor_name="integration" if is_service_account else "holder",
        tenant_id=3,
        resource_owner_user_id=11 if is_service_account else 7,
        scopes=frozenset({"knowledge:read"}),
        mode=mode,
        authorization_subject_type=(
            "service_account" if is_service_account and mode == "S" else "user"
        ),
        authorization_subject_id=7 if mode == "S" else 21,
        effective_user_id=None if is_service_account and mode == "S" else 7,
        on_behalf_of_user_id=21 if mode == "D" else None,
        end_user_id="external-1" if mode == "S" else None,
    )


@open_api_scope("knowledge:read", modes=("S", "D"))
async def endpoint():
    return None


def scope(*, connection_type: str = "http") -> dict:
    result = {
        "type": connection_type,
        "path": "/api/v2/filelib/retrieve",
        "endpoint": endpoint,
        "route": SimpleNamespace(path="/api/v2/filelib/retrieve"),
        "client": ("127.0.0.1", 3210),
    }
    if connection_type == "http":
        result["method"] = "POST"
    return result


async def run_middleware(monkeypatch, app, connection_scope):
    entries = []
    monkeypatch.setattr(
        middleware_module,
        "open_api_call_audit_service",
        SimpleNamespace(enqueue=lambda entry: entries.append(entry) or True),
    )

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        return None

    await OpenApiAuditMiddleware(app)(connection_scope, receive, send)
    return entries


async def test_success_audit_maps_sa_actor_subject_and_route_without_sensitive_data(monkeypatch):
    async def app(connection_scope, _receive, send):
        connection_scope["open_api_principal"] = principal()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"secret response"})

    entries = await run_middleware(monkeypatch, app, scope())

    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == "open_api.call"
    assert entry.target_type == "api_endpoint"
    assert entry.target_id == "POST /api/v2/filelib/retrieve"
    assert entry.tenant_id == entry.operator_tenant_id == 3
    assert entry.operator_id == 0
    assert entry.operator_name == "integration"
    assert entry.ip_address == "127.0.0.1"
    assert entry.audit_metadata["authorization_subject_type"] == "service_account"
    assert entry.audit_metadata["end_user_id"] == "external-1"
    serialized = entry.model_dump_json()
    assert "Authorization" not in serialized
    assert "secret response" not in serialized


async def test_pat_and_delegated_subject_audit_use_distinct_actor_and_subject(monkeypatch):
    delegated = principal(mode="D")

    async def app(connection_scope, _receive, send):
        connection_scope["open_api_principal"] = delegated
        await send({"type": "http.response.start", "status": 403, "headers": []})
        connection_scope["open_api_error_code"] = 26006
        await send({"type": "http.response.body", "body": b""})

    entries = await run_middleware(monkeypatch, app, scope())
    metadata = entries[0].audit_metadata
    assert metadata["actor_kind"] == "service_account"
    assert metadata["actor_id"] == 7
    assert metadata["identity_mode"] == "D"
    assert metadata["authorization_subject_type"] == "user"
    assert metadata["authorization_subject_id"] == 21
    assert metadata["error_code"] == 26006

    pat = principal(actor_kind="natural_person")

    async def pat_app(connection_scope, _receive, send):
        connection_scope["open_api_principal"] = pat
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    pat_entries = await run_middleware(monkeypatch, pat_app, scope())
    assert pat_entries[0].operator_id == 7
    assert pat_entries[0].operator_name is None


@pytest.mark.parametrize(("status", "error_code"), [(401, 26001), (403, 26003)])
async def test_auth_rejections_are_audited_without_fabricating_a_principal(
    monkeypatch,
    status,
    error_code,
):
    async def app(connection_scope, _receive, send):
        connection_scope["open_api_error_code"] = error_code
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    entries = await run_middleware(monkeypatch, app, scope())
    assert entries[0].tenant_id is None
    assert entries[0].audit_metadata["credential_id"] is None
    assert entries[0].audit_metadata["http_status"] == status
    assert entries[0].audit_metadata["error_code"] == error_code


async def test_unhandled_exception_is_audited_and_propagated(monkeypatch):
    entries = []
    monkeypatch.setattr(
        middleware_module,
        "open_api_call_audit_service",
        SimpleNamespace(enqueue=lambda entry: entries.append(entry) or True),
    )

    async def app(connection_scope, _receive, _send):
        connection_scope["open_api_principal"] = principal()
        raise RuntimeError("boom")

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        return None

    with pytest.raises(RuntimeError, match="boom"):
        await OpenApiAuditMiddleware(app)(scope(), receive, send)
    assert len(entries) == 1
    assert entries[0].audit_metadata["http_status"] == 500


async def test_websocket_is_audited_after_disconnect(monkeypatch):
    async def app(connection_scope, _receive, send):
        connection_scope["open_api_principal"] = principal()
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.close", "code": 1000})

    entries = await run_middleware(monkeypatch, app, scope(connection_type="websocket"))
    assert len(entries) == 1
    assert entries[0].target_id == "WS /api/v2/filelib/retrieve"
    assert entries[0].audit_metadata["http_status"] == 101


def test_bounded_queue_drops_without_changing_the_call_result():
    service = OpenApiCallAuditService(max_queue_size=1)
    first = AuditLog(operator_id=0, action="open_api.call")
    second = AuditLog(operator_id=0, action="open_api.call")

    assert service.enqueue(first) is True
    assert service.enqueue(second) is False


async def test_batch_write_failure_is_best_effort_and_drains_queue(monkeypatch):
    service = OpenApiCallAuditService(max_queue_size=2)
    service.enqueue(AuditLog(operator_id=0, action="open_api.call"))
    write = AsyncMock(side_effect=RuntimeError("database unavailable"))
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.call_audit_service."
        "AuditLogDao.ainsert_audit_logs",
        write,
    )

    assert await service.flush_now() == 1
    assert service.queue.empty()
    write.assert_awaited_once()
