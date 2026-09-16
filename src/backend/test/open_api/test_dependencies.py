from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI, File, Request, UploadFile
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    PersonalTokenDisabledError,
)
from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.open_api.api.dependencies import (
    admit_open_api_principal,
    open_api_execution_scope,
    verify_open_api_access,
)
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.context import OpenApiPrincipal, get_current_open_api_principal
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
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
            "super_admin": actor.super_admin,
            "tenant_admin_tenants": sorted(actor.tenant_admin_tenant_ids),
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

    # Stands in for the local development toolkit endpoints (`app:manage` is the
    # only one of the three with routes today: POST /apps/deploy, GET
    # /apps/{app_id}/logs).
    @router.get("/toolkit")
    @open_api_scope("app:manage", modes=("S",))
    async def toolkit():
        return {"deployed": True}

    @router.post("/upload")
    @open_api_scope("knowledge:write")
    async def upload(file: UploadFile = File(...)):
        return {"filename": file.filename}

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
        "super_admin": False,
        "tenant_admin_tenants": [],
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


async def test_pat_permission_actor_inherits_holder_tenant_admin_fact(monkeypatch):
    async def validate(_authorization):
        return natural_person_principal()

    async def tenant_policy(_tenant_id):
        return SimpleNamespace(enabled=True, data_scope="all_visible")

    async def is_global_super(_user_id):
        return False

    async def is_tenant_admin(user_id, tenant_id):
        assert (user_id, tenant_id) == (12, 9)
        return True

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", True)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.TenantSettingService.get_policy", tenant_policy)
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", is_global_super)
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", is_tenant_admin)

    response = await request(build_app(), "/api/v2/registered", authorization="Bearer opaque")

    assert response.status_code == 200
    assert response.json()["super_admin"] is False
    assert response.json()["tenant_admin_tenants"] == [9]
    assert response.json()["visible"] == [1, 9]


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


async def test_removed_user_id_is_rejected_in_multipart_before_upload_handler(monkeypatch):
    async def validate(_authorization):
        return service_account_principal(scopes=frozenset({"knowledge:write"}))

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    headers = {"Authorization": "Bearer opaque"}
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://test") as client:
        rejected = await client.post(
            "/api/v2/upload",
            headers=headers,
            data={"user_id": "123"},
            files={"file": ("sample.txt", b"content", "text/plain")},
        )
        accepted = await client.post(
            "/api/v2/upload",
            headers=headers,
            files={"file": ("sample.txt", b"content", "text/plain")},
        )

    assert rejected.status_code == 400
    assert rejected.json()["status_code"] == 26019
    assert accepted.status_code == 200
    assert accepted.json() == {"filename": "sample.txt"}


async def test_delegate_key_is_refused_at_the_toolkit_entrance_not_sent_to_an_admin(monkeypatch):
    """INV-31 runtime half: 26051, whether or not the key also holds the scope.

    The scope-less half is the one that used to hurt. It answered 26003 ("ask
    an administrator to tick app:manage"), and the administrator then could not
    — 26050 refuses `delegate` + a toolkit scope at issue time — so the two
    gates pointed at each other.
    """

    async def with_scope(_authorization):
        return service_account_principal(scopes=frozenset({"delegate", "app:manage"}))

    async def without_scope(_authorization):
        return service_account_principal(scopes=frozenset({"delegate"}))

    app = build_app()
    for validate in (with_scope, without_scope):
        monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
        response = await request(app, "/api/v2/toolkit", authorization="Bearer opaque")
        assert response.status_code == 403
        assert response.json()["status_code"] == 26051


async def test_delegate_refusal_beats_delegation_resolution_so_no_header_advice_is_given(monkeypatch):
    """26051 even when the caller does everything a delegated key is told to do.

    Sending `X-On-Behalf-Of` is what 26016 asks for; on a toolkit endpoint it
    must not turn the refusal into a success, or INV-31 degrades into "delegate
    keys work here as long as you pass a header".
    """

    async def validate(_authorization):
        return service_account_principal(scopes=frozenset({"delegate", "app:manage"}))

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="http://test") as client:
        response = await client.get(
            "/api/v2/toolkit",
            headers={"Authorization": "Bearer opaque", "X-On-Behalf-Of": "12"},
        )

    assert response.status_code == 403
    assert response.json()["status_code"] == 26051


async def test_a_key_without_delegate_is_untouched_by_the_toolkit_gate(monkeypatch):
    async def holder(_authorization):
        return service_account_principal(scopes=frozenset({"app:manage"}))

    async def bystander(_authorization):
        return service_account_principal(scopes=frozenset({"knowledge:read"}))

    app = build_app()
    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", holder)
    granted = await request(app, "/api/v2/toolkit", authorization="Bearer opaque")
    assert granted.status_code == 200
    assert granted.json() == {"deployed": True}

    # Still the ordinary missing-scope verdict, which is actionable: an
    # administrator can tick `app:manage` on a key that has no `delegate`.
    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", bystander)
    refused = await request(app, "/api/v2/toolkit", authorization="Bearer opaque")
    assert refused.status_code == 403
    assert refused.json()["status_code"] == 26003


async def test_delegate_key_on_a_non_toolkit_endpoint_keeps_its_existing_verdicts(monkeypatch):
    """The gate is scoped to the toolkit faces and nothing else.

    `whoami` is the case `bisheng login` hits, and it deliberately keeps 26016:
    it requires no scope at all, is not one of the three faces, and "send
    X-On-Behalf-Of" is correct advice for the general integration calling it.
    The CLI — which never sends identity headers — translates 26016 into the
    delegate refusal on its side (`bisheng_cli/errors.py`), which is what makes
    `login` refuse such a key.
    """

    async def validate(_authorization):
        return service_account_principal(scopes=frozenset({"delegate", "knowledge:read"}))

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    app = build_app()

    whoami = await request(app, "/api/v2/whoami", authorization="Bearer opaque")
    assert whoami.status_code == 400
    assert whoami.json()["status_code"] == 26016

    scoped = await request(app, "/api/v2/registered", authorization="Bearer opaque")
    assert scoped.status_code == 400
    assert scoped.json()["status_code"] == 26016


# ---------------------------------------------------------------------------
# F052 T201a — the split that lets the MCP face reuse this code, not copy it.
# ---------------------------------------------------------------------------


def bare_connection(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({"type": "http", "headers": headers or [], "path": "/x", "query_string": b""})


async def test_admit_returns_principal_and_pat_scope(monkeypatch):
    async def validate_service_account(_authorization):
        return service_account_principal()

    async def validate_pat(_authorization):
        return natural_person_principal()

    conn = bare_connection([(b"authorization", b"Bearer opaque")])

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate_service_account)
    principal, data_scope = await admit_open_api_principal(conn)
    assert (principal.actor_kind, data_scope) == ("service_account", DATA_SCOPE_ALL)
    # Admission publishes the principal for the audit middleware and installs
    # nothing that outlives the call — the execution scope owns that.
    assert conn.scope["open_api_principal"] is principal
    assert get_current_tenant_id() is None
    assert get_current_permission_actor() is None

    async def narrowed_policy(_tenant_id):
        return SimpleNamespace(enabled=True, data_scope="personal_only")

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate_pat)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", True)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.TenantSettingService.get_policy", narrowed_policy)
    _principal, data_scope = await admit_open_api_principal(conn)
    assert data_scope == "personal_only"


async def test_admit_refuses_a_personal_token_the_deployment_disabled(monkeypatch):
    async def validate_pat(_authorization):
        return natural_person_principal()

    async def disabled_policy(_tenant_id):
        return SimpleNamespace(enabled=False, data_scope=DATA_SCOPE_ALL)

    conn = bare_connection([(b"authorization", b"Bearer opaque")])
    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate_pat)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", False)
    with pytest.raises(PersonalTokenDisabledError):
        await admit_open_api_principal(conn)

    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", True)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.TenantSettingService.get_policy", disabled_policy)
    with pytest.raises(PersonalTokenDisabledError):
        await admit_open_api_principal(conn)


async def test_pat_policy_read_happens_with_tenant_contextvar_installed(monkeypatch):
    """The one ordering the split could silently reverse.

    ``TenantSettingService.get_policy`` takes the tenant id explicitly, but the
    DAO underneath it still runs under the automatic tenant filter — read it
    before the tenant ContextVar is installed and it fails (or, worse, reads
    somebody else's row) only on a real database, where no unit test looks.
    """

    seen: dict[str, object] = {}

    async def validate_pat(_authorization):
        return natural_person_principal()

    async def recording_policy(_tenant_id):
        seen["tenant"] = get_current_tenant_id()
        seen["visible"] = set(get_visible_tenant_ids())
        return SimpleNamespace(enabled=True, data_scope=DATA_SCOPE_ALL)

    conn = bare_connection([(b"authorization", b"Bearer opaque")])
    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate_pat)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", True)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.TenantSettingService.get_policy", recording_policy)

    await admit_open_api_principal(conn)

    assert seen["tenant"] == 9
    assert seen["visible"] == {1, 9}
    assert get_current_tenant_id() is None


async def test_execution_scope_installs_and_resets_four_contextvars():
    principal = service_account_principal()
    conn = bare_connection()

    async with open_api_execution_scope(conn, principal, data_scope=DATA_SCOPE_ALL) as resolved:
        assert resolved is principal
        assert get_current_tenant_id() == 9
        assert set(get_visible_tenant_ids()) == {1, 9}
        assert get_current_open_api_principal() is principal
        actor = get_current_permission_actor()
        assert actor.fga_subject == "service_account:31"
        assert actor.data_scope == DATA_SCOPE_ALL

    assert get_current_tenant_id() is None
    assert get_current_open_api_principal() is None
    assert get_current_permission_actor() is None


async def test_execution_scope_without_prepare_never_resolves_delegation(monkeypatch):
    """The MCP face passes no ``prepare``: identity headers are refused, not parsed."""

    async def explode(*_args, **_kwargs):
        raise AssertionError("resolve_request_identity must not run without prepare")

    monkeypatch.setattr("bisheng.open_api.api.dependencies.resolve_request_identity", explode)
    principal = service_account_principal(scopes=frozenset({"delegate"}))
    conn = bare_connection([(b"x-on-behalf-of", b"12")])

    async with open_api_execution_scope(conn, principal, data_scope=DATA_SCOPE_ALL) as resolved:
        assert resolved.mode == "S"
