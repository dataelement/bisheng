from types import SimpleNamespace

from fastapi import APIRouter, Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from bisheng.open_api.api import middleware as audit_middleware_module
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.api.middleware import OpenApiAuditMiddleware
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.scopes import open_api_scope


def delegated_key_principal() -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=5,
        actor_kind="service_account",
        actor_id=7,
        actor_name="integration",
        tenant_id=3,
        resource_owner_user_id=11,
        scopes=frozenset({"knowledge:read", "delegate"}),
        authorization_subject_type="service_account",
        authorization_subject_id=7,
        effective_user_id=None,
    )


def build_app() -> FastAPI:
    app = FastAPI()
    register_open_api_exception_handlers(app)
    app.add_middleware(OpenApiAuditMiddleware)
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])

    @router.post("/delegated")
    @open_api_scope("knowledge:read", modes=("S", "D"))
    async def delegated(request: Request):
        principal = request.scope["open_api_principal"]
        return {
            "mode": principal.mode,
            "actor": [principal.actor_kind, principal.actor_id],
            "subject": [
                principal.authorization_subject_type,
                principal.authorization_subject_id,
            ],
        }

    @router.post("/self-only")
    @open_api_scope("knowledge:read", modes=("S",))
    async def self_only():
        return {"unsafe": True}

    app.include_router(router)
    return app


async def client_request(app, path, *, headers=None, params=None, json=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, headers=headers, params=params, json=json)


async def configure_identity(monkeypatch):
    async def validate(_authorization):
        return delegated_key_principal()

    async def target(user_id):
        return SimpleNamespace(user_id=user_id, tenant_id=3)

    async def not_privileged(_user_id, _tenant_id):
        return False

    async def allowed(_credential_id, _user_id):
        return True

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service."
        "OwnerRepository.get_active_natural_person",
        target,
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service._is_privileged_target",
        not_privileged,
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service.DelegateScopeService.target_allowed",
        allowed,
    )


async def test_delegation_replaces_subject_and_endpoint_mode_is_the_fifth_gate(monkeypatch):
    await configure_identity(monkeypatch)
    headers = {"Authorization": "Bearer opaque", "X-On-Behalf-Of": "21"}

    accepted = await client_request(build_app(), "/api/v2/delegated", headers=headers)
    assert accepted.status_code == 200
    assert accepted.json() == {
        "mode": "D",
        "actor": ["service_account", 7],
        "subject": ["user", 21],
    }

    rejected = await client_request(build_app(), "/api/v2/self-only", headers=headers)
    assert rejected.status_code == 403
    assert rejected.json()["status_code"] == 26006


async def test_removed_identity_inputs_and_missing_delegate_header_fail_explicitly(monkeypatch):
    await configure_identity(monkeypatch)
    base_headers = {"Authorization": "Bearer opaque"}

    missing = await client_request(build_app(), "/api/v2/delegated", headers=base_headers)
    assert missing.status_code == 400
    assert missing.json()["status_code"] == 26016

    old_header = await client_request(
        build_app(),
        "/api/v2/delegated",
        headers={**base_headers, "X-Bisheng-On-Behalf-Of": "21"},
    )
    assert old_header.status_code == 400
    assert old_header.json()["status_code"] == 26019

    raw_query = await client_request(
        build_app(),
        "/api/v2/delegated",
        headers=base_headers,
        params={"user_id": 21},
    )
    assert raw_query.status_code == 400
    assert raw_query.json()["status_code"] == 26019


async def test_http_call_audit_observes_final_delegated_subject(monkeypatch):
    await configure_identity(monkeypatch)
    entries = []
    monkeypatch.setattr(
        audit_middleware_module,
        "open_api_call_audit_service",
        SimpleNamespace(enqueue=lambda entry: entries.append(entry) or True),
    )
    response = await client_request(
        build_app(),
        "/api/v2/delegated",
        headers={"Authorization": "Bearer opaque", "X-On-Behalf-Of": "21"},
    )

    assert response.status_code == 200
    assert len(entries) == 1
    metadata = entries[0].audit_metadata
    assert metadata["actor_id"] == 7
    assert metadata["authorization_subject_id"] == 21
    assert metadata["on_behalf_of_user_id"] == 21
