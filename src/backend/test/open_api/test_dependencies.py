from fastapi import APIRouter, Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.open_api import OpenApiAuthDependencyUnavailableError
from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.context import OpenApiPrincipal, get_current_open_api_principal
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.permission.application.identity import get_current_permission_actor


def build_app() -> FastAPI:
    app = FastAPI()
    register_open_api_exception_handlers(app)
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])

    @router.get("/registered")
    @open_api_scope("knowledge:read")
    async def registered(request: Request):
        principal = get_current_open_api_principal()
        actor = get_current_permission_actor()
        return {
            "scope_actor": request.scope["open_api_principal"].actor_id,
            "principal_actor": principal.actor_id,
            "permission_subject": actor.fga_subject,
            "tenant": get_current_tenant_id(),
            "visible": sorted(get_visible_tenant_ids()),
        }

    @router.get("/whoami")
    @open_api_scope(None)
    async def whoami():
        return {"ok": True}

    @router.get("/unregistered")
    async def unregistered():
        return {"unsafe": True}

    app.include_router(router)
    return app


def service_account_principal(*, scopes=frozenset({"knowledge:read"})) -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=7,
        actor_kind="service_account",
        actor_id=31,
        actor_name="indexer",
        tenant_id=9,
        resource_owner_user_id=12,
        scopes=scopes,
        authorization_subject_type="service_account",
        authorization_subject_id=31,
        effective_user_id=None,
    )


def natural_person_principal() -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=8,
        actor_kind="natural_person",
        actor_id=12,
        actor_name="employee",
        tenant_id=9,
        resource_owner_user_id=12,
        scopes=frozenset({"knowledge:read"}),
        authorization_subject_type="user",
        authorization_subject_id=12,
        effective_user_id=12,
    )


async def request(app: FastAPI, path: str, *, authorization: str | None = None):
    headers = {"Authorization": authorization} if authorization is not None else None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def test_missing_and_jwt_credentials_are_real_401():
    app = build_app()
    for authorization in (None, "Bearer jwt.header.payload"):
        response = await request(app, "/api/v2/registered", authorization=authorization)
        assert response.status_code == 401
        assert response.json()["status_code"] == 26001


async def test_valid_key_installs_all_three_request_contexts(monkeypatch):
    async def validate(_authorization):
        return service_account_principal()

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    response = await request(build_app(), "/api/v2/registered", authorization="Bearer opaque")
    assert response.status_code == 200
    assert response.json() == {
        "scope_actor": 31,
        "principal_actor": 31,
        "permission_subject": "service_account:31",
        "tenant": 9,
        "visible": [1, 9],
    }
    assert get_current_open_api_principal() is None
    assert get_current_permission_actor() is None


async def test_scope_and_marker_are_fail_closed(monkeypatch):
    async def validate(_authorization):
        return service_account_principal(scopes=frozenset())

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    app = build_app()
    missing_scope = await request(app, "/api/v2/registered", authorization="Bearer opaque")
    assert missing_scope.status_code == 403
    assert missing_scope.json()["status_code"] == 26003

    unregistered = await request(app, "/api/v2/unregistered", authorization="Bearer opaque")
    assert unregistered.status_code == 500
    assert unregistered.json()["status_code"] == 26031

    whoami = await request(app, "/api/v2/whoami", authorization="Bearer opaque")
    assert whoami.status_code == 200


async def test_auth_dependency_outage_is_real_503(monkeypatch):
    async def fail(_authorization):
        raise OpenApiAuthDependencyUnavailableError()

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", fail)
    response = await request(build_app(), "/api/v2/registered", authorization="Bearer opaque")
    assert response.status_code == 503
    assert response.json()["status_code"] == 26030


async def test_pat_policy_dependency_outage_is_real_503_before_scope(monkeypatch):
    async def validate(_authorization):
        return natural_person_principal()

    async def fail_policy(_tenant_id):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", True)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.TenantSettingService.get_policy", fail_policy)
    response = await request(build_app(), "/api/v2/registered", authorization="Bearer opaque")
    assert response.status_code == 503
    assert response.json()["status_code"] == 26030


async def test_identity_headers_are_not_silently_ignored(monkeypatch):
    async def validate(_authorization):
        return service_account_principal()

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://test") as client:
        response = await client.get(
            "/api/v2/registered",
            headers={"Authorization": "Bearer opaque", "X-On-Behalf-Of": "12"},
        )
    assert response.status_code == 403
    assert response.json()["status_code"] == 26004
