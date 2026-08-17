"""``/api/v2`` credential dependency + dedicated handler + ``whoami`` (F049 T020).

These are the only tests in the package that assert **real HTTP status codes**
(design K4 / D2): every other surface of the platform flattens errors to HTTP
200 + envelope, and the whole point of the dedicated ``/api/v2`` handler is that
an SDK reading ``response.status_code`` sees 401 / 403 / 500 / 503. The last
test in this file pins the other half of that contract: ``/api/v1`` keeps the
HTTP 200 + envelope behaviour untouched.

Temporary routes are mounted onto the **real** application object (the same one
``create_app()`` builds, with the real exception handlers) rather than onto a
hand-assembled stub — a stub would let a wiring mistake in ``main.py`` /
``api/router.py`` pass unnoticed.

覆盖 AC: AC-01, AC-04, AC-13, AC-32, AC-33, AC-34, AC-35
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends

from bisheng.common.errcode.open_api import OpenApiExtensionScopeNotDeployedError
from bisheng.common.schemas.api import resp_200
from bisheng.open_api.api.dependencies import open_api_subject, verify_open_api_access
from bisheng.open_api.domain.scopes import open_api_scope
from test.open_api.conftest import ROOT_TENANT_ID

WHOAMI = "/api/v2/auth/whoami"


def _auth(plaintext: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {plaintext}"}


def _mount_v2(app, path: str, endpoint) -> None:
    """Mount ``endpoint`` under ``/api/v2`` behind the real router-level dependency.

    Mirrors what ``T040`` will do globally on ``router_rpc``: the dependency is
    declared on the router, never per endpoint (design D3).
    """
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])
    router.add_api_route(path, endpoint, methods=["GET"])
    app.include_router(router)


def _mount_plain(app, path: str, endpoint) -> None:
    """Mount ``endpoint`` with no router-level dependency (used for the /api/v1 contrast)."""
    router = APIRouter()
    router.add_api_route(path, endpoint, methods=["GET"])
    app.include_router(router)


@pytest.fixture()
async def live_key(oapi_db, redis_client, service_account_factory, credential_factory):
    """A usable service account + one issued key; returns ``(account, issued)``."""
    account = await service_account_factory(name="oapi-auth-api")
    issued = await credential_factory(account.user_id, scopes=["workflow:invoke"])
    return account, issued


# ---------------------------------------------------------------------------
# AC-01 — no credential / bad credential
# ---------------------------------------------------------------------------


async def test_whoami_without_credential_401_26001(v2_client, live_key):
    response = v2_client.get(WHOAMI)

    assert response.status_code == 401
    body = response.json()
    # The envelope shape stays identical to the rest of the platform; only the
    # HTTP status is made real (K4).
    assert set(body) >= {"status_code", "status_message", "data"}
    assert body["status_code"] == 26001


@pytest.mark.parametrize("header", ["", "Token abc", "Bearer ", "Bearer not-a-bisheng-key"])
async def test_whoami_malformed_authorization_401_26001(v2_client, live_key, header):
    response = v2_client.get(WHOAMI, headers={"Authorization": header} if header else {})

    assert response.status_code == 401
    assert response.json()["status_code"] == 26001


async def test_whoami_tampered_credential_401_26002(v2_client, live_key):
    _, issued = live_key
    flipped = "a" if issued.plaintext[-1] != "a" else "b"
    tampered = issued.plaintext[:-1] + flipped

    response = v2_client.get(WHOAMI, headers=_auth(tampered))

    assert response.status_code == 401
    # "presented but unusable" is a different code from "not presented" (D10).
    assert response.json()["status_code"] == 26002


# ---------------------------------------------------------------------------
# AC-32 / AC-35 — mode S: the key subject is the acting identity
# ---------------------------------------------------------------------------


async def test_no_header_runs_as_key_subject(v2_client, live_key):
    account, issued = live_key

    response = v2_client.get(WHOAMI, headers=_auth(issued.plaintext))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["subject_kind"] == "service_account"
    assert data["service_account"]["id"] == account.user_id
    assert data["tenant_id"] == ROOT_TENANT_ID
    assert data["scopes"] == ["workflow:invoke"]
    assert data["key_mask"] == issued.key_mask
    assert "plaintext" not in data


async def test_scope_none_marker_skips_scope_check(
    v2_client, oapi_db, redis_client, service_account_factory, credential_factory
):
    """``whoami`` is marked ``@open_api_scope(None)``: no scope, still admitted."""
    account = await service_account_factory(name="oapi-no-scopes")
    issued = await credential_factory(account.user_id, scopes=[])

    response = v2_client.get(WHOAMI, headers=_auth(issued.plaintext))

    assert response.status_code == 200
    assert response.json()["data"]["scopes"] == []


# ---------------------------------------------------------------------------
# AC-04 — scope enforcement + the structural fail-closed for unmarked endpoints
# ---------------------------------------------------------------------------


async def test_unregistered_endpoint_26031(v2_client, live_key):
    _, issued = live_key

    async def unmarked():  # deliberately no @open_api_scope
        return resp_200(data={"ran": True})

    _mount_v2(v2_client.app, "/__t020_unmarked__", unmarked)

    response = v2_client.get("/api/v2/__t020_unmarked__", headers=_auth(issued.plaintext))

    # Forgetting the marker must break loudly, never become "no scope required".
    assert response.status_code == 500
    body = response.json()
    assert body["status_code"] == 26031
    assert body["data"].get("ran") is None


async def test_missing_scope_403_with_required(v2_client, live_key):
    _, issued = live_key  # holds workflow:invoke only

    @open_api_scope("assistant:read")
    async def needs_assistant_read():
        return resp_200(data={"ran": True})

    _mount_v2(v2_client.app, "/__t020_assistant_read__", needs_assistant_read)

    response = v2_client.get("/api/v2/__t020_assistant_read__", headers=_auth(issued.plaintext))

    assert response.status_code == 403
    body = response.json()
    assert body["status_code"] == 26003
    # AC-04: the caller must learn *which* scope is missing.
    assert body["data"]["required"] == "assistant:read"


async def test_app_manage_scope_check_via_factory(
    v2_client, oapi_db, redis_client, monkeypatch, service_account_factory, credential_factory
):
    """``Depends(open_api_subject('app:manage'))`` — the F053 / F055 reuse surface."""
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    account = await service_account_factory(name="oapi-app-manage")
    with_scope = await credential_factory(account.user_id, scopes=["app:manage"], name="with")
    without_scope = await credential_factory(account.user_id, scopes=["workflow:read"], name="without")

    async def deploy(login_user=Depends(open_api_subject("app:manage"))):
        return resp_200(data={"user_id": login_user.user_id})

    router = APIRouter(prefix="/api/v2")
    router.add_api_route("/__t020_factory__", deploy, methods=["GET"])
    v2_client.app.include_router(router)

    ok = v2_client.get("/api/v2/__t020_factory__", headers=_auth(with_scope.plaintext))
    assert ok.status_code == 200
    assert ok.json()["data"]["user_id"] == account.user_id

    denied = v2_client.get("/api/v2/__t020_factory__", headers=_auth(without_scope.plaintext))
    assert denied.status_code == 403
    assert denied.json()["status_code"] == 26003
    assert denied.json()["data"]["required"] == "app:manage"


# ---------------------------------------------------------------------------
# AC-13 — the three extension scopes follow the open-platform switch
# ---------------------------------------------------------------------------


async def test_extension_scope_issue_rejected_when_platform_off(
    v2_client, oapi_db, redis_client, monkeypatch, service_account_factory, credential_factory
):
    from bisheng.common.services.config_service import settings

    account = await service_account_factory(name="oapi-ext-scope")

    monkeypatch.setattr(settings.open_platform, "enabled", False)
    with pytest.raises(OpenApiExtensionScopeNotDeployedError):
        await credential_factory(account.user_id, scopes=["app:manage"])

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    issued = await credential_factory(account.user_id, scopes=["app:manage"])
    response = v2_client.get(WHOAMI, headers=_auth(issued.plaintext))

    assert response.status_code == 200
    assert response.json()["data"]["scopes"] == ["app:manage"]


# ---------------------------------------------------------------------------
# AC-33 / AC-35 — identity-passing headers are rejected, never ignored
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("header", ["X-Bisheng-On-Behalf-Of", "X-Bisheng-End-User"])
async def test_identity_headers_rejected_26004(v2_client, live_key, header):
    _, issued = live_key
    executed: list[str] = []

    @open_api_scope("workflow:invoke")
    async def business():
        executed.append("ran")
        return resp_200(data={"ran": True})

    _mount_v2(v2_client.app, "/__t020_identity__", business)

    response = v2_client.get(
        "/api/v2/__t020_identity__",
        headers={**_auth(issued.plaintext), header: "1"},
    )

    assert response.status_code == 403
    assert response.json()["status_code"] == 26004
    # AC-33: the header must not be silently dropped and the call continued.
    assert executed == []


async def test_only_two_outcomes_no_silent_downgrade(v2_client, live_key):
    """Same endpoint, same key: mode S or 26004 — there is no third response."""
    _, issued = live_key

    @open_api_scope("workflow:invoke")
    async def business():
        return resp_200(data={"subject": "key"})

    _mount_v2(v2_client.app, "/__t020_two_outcomes__", business)

    plain = v2_client.get("/api/v2/__t020_two_outcomes__", headers=_auth(issued.plaintext))
    assert plain.status_code == 200
    assert plain.json()["data"] == {"subject": "key"}

    with_header = v2_client.get(
        "/api/v2/__t020_two_outcomes__",
        headers={**_auth(issued.plaintext), "X-Bisheng-On-Behalf-Of": "1"},
    )
    assert with_header.status_code == 403
    assert with_header.json()["status_code"] == 26004
    # No "empty set / public subset" degradation exists between the two.
    assert with_header.json()["data"].get("subject") is None


# ---------------------------------------------------------------------------
# AC-34 — dependency outages are 5xx, never a partially filtered result
# ---------------------------------------------------------------------------


async def test_fga_unavailable_503(v2_client, live_key, fga_down):
    _, issued = live_key

    @open_api_scope("workflow:invoke")
    async def guarded():
        from bisheng.common.dependencies.user_deps import UserPayload
        from bisheng.permission.application.business_authorization import require_business_action

        await require_business_action(
            UserPayload(user_id=1, user_name="x", user_role=[], tenant_id=ROOT_TENANT_ID, is_global_super=False),
            resource_type="knowledge",
            resource_id="1",
            action="read",
        )
        return resp_200(data={"rows": [1, 2, 3]})

    _mount_v2(v2_client.app, "/__t020_fga__", guarded)

    response = v2_client.get("/api/v2/__t020_fga__", headers=_auth(issued.plaintext))

    assert response.status_code == 503
    assert response.json()["status_code"] == 19002
    assert response.json()["data"].get("rows") is None


async def test_redis_down_503_26030(v2_client, live_key, monkeypatch):
    _, issued = live_key
    from bisheng.open_api.domain.services import credential_validator

    async def _boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(credential_validator, "get_redis_client", _boom)

    response = v2_client.get(WHOAMI, headers=_auth(issued.plaintext))

    # K2: fail closed. A validation dependency outage is a 503, never a pass.
    assert response.status_code == 503
    assert response.json()["status_code"] == 26030


# ---------------------------------------------------------------------------
# K4 — the /api/v1 envelope semantics are untouched
# ---------------------------------------------------------------------------


async def test_v1_envelope_unchanged(v2_client):
    from bisheng.common.errcode.open_api import ServiceAccountNotFoundError

    async def failing():
        raise ServiceAccountNotFoundError()

    _mount_plain(v2_client.app, "/api/v1/__t020_envelope__", failing)

    response = v2_client.get("/api/v1/__t020_envelope__")

    # Same exception class as on /api/v2 (http_status=404) — but on /api/v1 the
    # platform-wide contract still applies: HTTP 200 + envelope status_code.
    assert response.status_code == 200
    assert response.json()["status_code"] == 26020
