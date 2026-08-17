"""API-key management + ``GET /scopes`` under ``/api/v1/service-accounts/**`` (F049 T025).

Envelope口径 (HTTP 200 + ``status_code``) like every ``/api/v1`` surface; the
credential itself is then exercised against ``/api/v2/auth/whoami``, which is
where the real HTTP statuses live. That pairing is the point of several tests
here: editing a key's scopes must change what the *same* plaintext can do,
without re-issuing it (AC-08), and revoking must take effect on the next call
(AC-09), not on cache expiry.

覆盖 AC: AC-02, AC-06, AC-07, AC-08, AC-09, AC-12, AC-13, AC-14, AC-44, AC-46, AC-49
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlmodel import col, select

from bisheng.database.models.audit_log import AuditLog
from bisheng.open_api.api.dependencies import get_service_account_admin
from bisheng.open_api.domain.models.api_credential import KEY_PREFIX, KEY_SECRET_LENGTH

BASE = "/api/v1/service-accounts"
WHOAMI = "/api/v2/auth/whoami"


def _as_admin(client, payload) -> None:
    from bisheng.core.context.tenant import set_current_tenant_id

    def _override():
        set_current_tenant_id(payload.tenant_id)
        return payload

    client.app.dependency_overrides[get_service_account_admin] = _override


def _envelope(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


def _auth(plaintext: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {plaintext}"}


async def _audit_rows(oapi_db) -> list[AuditLog]:
    async with oapi_db() as session:
        return list((await session.exec(select(AuditLog).order_by(col(AuditLog.id)))).all())


@pytest.fixture()
def admin_client(v2_client, oapi_db, redis_client, tenant_admin_payload):
    _as_admin(v2_client, tenant_admin_payload)
    yield v2_client
    v2_client.app.dependency_overrides.clear()


@pytest.fixture()
async def account(admin_client, human_user):
    body = _envelope(admin_client.post(BASE, json={"name": "key-bot", "resource_owner_user_id": human_user.user_id}))
    return body["data"]


def _issue(client, account_id: int, **payload) -> dict:
    body = _envelope(client.post(f"{BASE}/{account_id}/keys", json={"name": "k", **payload}))
    return body


# ---------------------------------------------------------------------------
# AC-02 — the plaintext exists exactly once
# ---------------------------------------------------------------------------


async def test_issue_plaintext_only_in_create_response(admin_client, oapi_db, account):
    issued = _issue(admin_client, account["id"], name="first")["data"]

    assert issued["plaintext"].startswith(KEY_PREFIX)
    assert len(issued["plaintext"]) == len(KEY_PREFIX) + KEY_SECRET_LENGTH
    assert issued["key_mask"] == f"{KEY_PREFIX}********{issued['plaintext'][-4:]}"

    listed = _envelope(admin_client.get(f"{BASE}/{account['id']}/keys"))["data"]
    assert len(listed) == 1
    assert "plaintext" not in listed[0]
    assert listed[0]["key_mask"] == issued["key_mask"]

    detail = _envelope(admin_client.get(f"{BASE}/{account['id']}"))["data"]
    assert issued["plaintext"] not in str(detail)

    for row in await _audit_rows(oapi_db):
        assert issued["plaintext"] not in str(row.audit_metadata)


# ---------------------------------------------------------------------------
# AC-06 / AC-13 / AC-14 — scope validation at issue / edit time
# ---------------------------------------------------------------------------


async def test_issue_default_no_scopes_and_unknown_26025(admin_client, account):
    default = _issue(admin_client, account["id"], name="bare")["data"]
    # AC-06: nothing is granted implicitly.
    assert default["scopes"] == []

    unknown = _issue(admin_client, account["id"], name="typo", scopes=["knowledge:reed"])
    assert unknown["status_code"] == 26025


async def test_issue_extension_scope_when_platform_off_26023(admin_client, monkeypatch, account):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.open_platform, "enabled", False)
    assert _issue(admin_client, account["id"], name="ext", scopes=["app:manage"])["status_code"] == 26023

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    assert _issue(admin_client, account["id"], name="ext", scopes=["app:manage"])["status_code"] == 200


async def test_issue_or_patch_with_delegate_26024(admin_client, account):
    """AC-14: ``delegate`` is recognised only so the refusal can be specific."""
    assert _issue(admin_client, account["id"], name="deleg", scopes=["delegate"])["status_code"] == 26024

    key = _issue(admin_client, account["id"], name="ok")["data"]
    patched = _envelope(admin_client.patch(f"{BASE}/{account['id']}/keys/{key['id']}", json={"scopes": ["delegate"]}))
    assert patched["status_code"] == 26024


# ---------------------------------------------------------------------------
# AC-08 — edits take effect on the existing key
# ---------------------------------------------------------------------------


async def test_patch_name_scopes_expires_effective_immediately(admin_client, account):
    key = _issue(admin_client, account["id"], name="editable", scopes=["workflow:read"])["data"]
    auth = _auth(key["plaintext"])

    before = admin_client.get(WHOAMI, headers=auth)
    assert before.json()["data"]["scopes"] == ["workflow:read"]

    patched = _envelope(
        admin_client.patch(
            f"{BASE}/{account['id']}/keys/{key['id']}",
            json={"name": "renamed", "scopes": ["knowledge:read", "knowledge:write"]},
        )
    )["data"]
    assert patched["name"] == "renamed"
    assert patched["key_mask"] == key["key_mask"]  # same key, not a rotation

    after = admin_client.get(WHOAMI, headers=auth)
    assert after.status_code == 200
    assert after.json()["data"]["scopes"] == ["knowledge:read", "knowledge:write"]

    expired_at = datetime.now() - timedelta(seconds=1)
    _envelope(
        admin_client.patch(
            f"{BASE}/{account['id']}/keys/{key['id']}",
            json={"expires_at": expired_at.isoformat()},
        )
    )
    dead = admin_client.get(WHOAMI, headers=auth)
    assert dead.status_code == 401
    assert dead.json()["status_code"] == 26002


# ---------------------------------------------------------------------------
# AC-09 / AC-46 — revoke single / revoke all
# ---------------------------------------------------------------------------


async def test_revoke_all_within_5s(admin_client, account):
    first = _issue(admin_client, account["id"], name="a")["data"]
    second = _issue(admin_client, account["id"], name="b")["data"]
    # Warm the positive cache so the assertion proves active invalidation, not
    # a cold lookup that would have hit the DB anyway (K1).
    assert admin_client.get(WHOAMI, headers=_auth(first["plaintext"])).status_code == 200
    assert admin_client.get(WHOAMI, headers=_auth(second["plaintext"])).status_code == 200

    result = _envelope(admin_client.post(f"{BASE}/{account['id']}/keys/revoke-all"))
    assert result["status_code"] == 200
    assert result["data"]["revoked"] == 2

    for key in (first, second):
        rejected = admin_client.get(WHOAMI, headers=_auth(key["plaintext"]))
        assert rejected.status_code == 401
        assert rejected.json()["status_code"] == 26002

    listed = _envelope(admin_client.get(f"{BASE}/{account['id']}/keys"))["data"]
    # AC-11: revoked keys stay listed with their history.
    assert len(listed) == 2
    assert all(row["revoked_at"] is not None and row["is_valid"] is False for row in listed)


async def test_revoke_single_requires_belongs_to_account(admin_client, human_user, account):
    other = _envelope(
        admin_client.post(BASE, json={"name": "other-bot", "resource_owner_user_id": human_user.user_id})
    )["data"]
    mine = _issue(admin_client, account["id"], name="mine")["data"]

    foreign = _envelope(admin_client.post(f"{BASE}/{other['id']}/keys/{mine['id']}/revoke"))
    assert foreign["status_code"] == 26026

    still_alive = admin_client.get(WHOAMI, headers=_auth(mine["plaintext"]))
    assert still_alive.status_code == 200

    revoked = _envelope(admin_client.post(f"{BASE}/{account['id']}/keys/{mine['id']}/revoke"))
    assert revoked["status_code"] == 200
    assert admin_client.get(WHOAMI, headers=_auth(mine["plaintext"])).status_code == 401


# ---------------------------------------------------------------------------
# AC-07 — key operations are tenant-scoped through their account
# ---------------------------------------------------------------------------


async def test_issue_and_list_tenant_isolated(
    v2_client, oapi_db, redis_client, human_user, sub_tenant, tenant_admin_payload
):
    _as_admin(v2_client, tenant_admin_payload)
    root_account = _envelope(
        v2_client.post(BASE, json={"name": "root-bot", "resource_owner_user_id": human_user.user_id})
    )["data"]
    root_key = _issue(v2_client, root_account["id"], name="root-key")["data"]

    _as_admin(v2_client, sub_tenant.admin_payload)
    try:
        assert _envelope(v2_client.get(f"{BASE}/{root_account['id']}/keys"))["status_code"] == 26020
        assert _issue(v2_client, root_account["id"], name="stolen")["status_code"] == 26020
        revoke = v2_client.post(f"{BASE}/{root_account['id']}/keys/{root_key['id']}/revoke")
        assert _envelope(revoke)["status_code"] == 26020
    finally:
        v2_client.app.dependency_overrides.clear()

    # The Root key is untouched by the failed cross-tenant attempts.
    _as_admin(v2_client, tenant_admin_payload)
    assert v2_client.get(WHOAMI, headers=_auth(root_key["plaintext"])).status_code == 200
    v2_client.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC-44 — key list columns
# ---------------------------------------------------------------------------


async def test_key_list_columns(admin_client, account):
    expires_at = datetime.now() + timedelta(days=30)
    key = _issue(
        admin_client,
        account["id"],
        name="columns",
        scopes=["assistant:read"],
        expires_at=expires_at.isoformat(),
    )["data"]

    row = _envelope(admin_client.get(f"{BASE}/{account['id']}/keys"))["data"][0]
    assert row["id"] == key["id"]
    assert row["name"] == "columns"
    assert row["key_mask"].startswith(KEY_PREFIX)
    assert row["scopes"] == ["assistant:read"]
    assert row["last_used_at"] is None
    assert row["expires_at"] is not None
    # Status is derived from ``revoked_at`` / ``expires_at`` at read time — there
    # is no status column that could drift (K3).
    assert row["is_valid"] is True
    assert row["revoked_at"] is None


# ---------------------------------------------------------------------------
# AC-12 — audit
# ---------------------------------------------------------------------------


async def test_key_lifecycle_audit_events(admin_client, oapi_db, account, tenant_admin_payload):
    first = _issue(admin_client, account["id"], name="audited", scopes=["workflow:read"])["data"]
    _envelope(admin_client.patch(f"{BASE}/{account['id']}/keys/{first['id']}", json={"name": "audited-2"}))
    _envelope(admin_client.post(f"{BASE}/{account['id']}/keys/{first['id']}/revoke"))
    second = _issue(admin_client, account["id"], name="audited-3")["data"]
    _envelope(admin_client.post(f"{BASE}/{account['id']}/keys/revoke-all"))

    rows = [row for row in await _audit_rows(oapi_db) if row.action.startswith("open_api.api_key.")]
    assert {row.action for row in rows} == {
        "open_api.api_key.issue",
        "open_api.api_key.update",
        "open_api.api_key.revoke",
        "open_api.api_key.revoke_all",
    }
    for row in rows:
        assert row.operator_id == tenant_admin_payload.user_id, row.action
        assert first["plaintext"] not in str(row.audit_metadata)
        assert second["plaintext"] not in str(row.audit_metadata)

    issued = [row for row in rows if row.action == "open_api.api_key.issue"]
    assert {row.audit_metadata["key_mask"] for row in issued} == {first["key_mask"], second["key_mask"]}
    assert all(row.audit_metadata["subject_id"] == str(account["id"]) for row in issued)

    revoke_all = next(row for row in rows if row.action == "open_api.api_key.revoke_all")
    # Only the still-valid key was revoked; the manually revoked one keeps its
    # original reason (AC-11 "why a key died" is part of the trail).
    assert revoke_all.audit_metadata["revoked_count"] == 1


# ---------------------------------------------------------------------------
# GET /scopes — the issue form's source of truth
# ---------------------------------------------------------------------------


async def test_scopes_route_not_shadowed_by_id(admin_client):
    """``/scopes`` must be registered before ``/{service_account_id}`` or it 422s."""
    response = admin_client.get(f"{BASE}/scopes")

    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200
    assert isinstance(body["data"]["scopes"], list)


async def test_scopes_endpoint_reflects_platform_switch(admin_client, monkeypatch):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.open_platform, "enabled", False)
    off = {item["code"]: item for item in _envelope(admin_client.get(f"{BASE}/scopes"))["data"]["scopes"]}
    assert {"model:invoke", "identity:read", "app:manage"}.isdisjoint(off)
    assert "workflow:invoke" in off

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    body = _envelope(admin_client.get(f"{BASE}/scopes"))["data"]
    on = {item["code"]: item for item in body["scopes"]}

    assert body["open_platform_enabled"] is True
    for code in ("model:invoke", "identity:read", "app:manage"):
        assert on[code]["group"] == "local_dev_toolkit"
        assert on[code]["desc_key"]
    # AC-13: the two hints the form must render prominently.
    assert on["identity:read"]["hint_keys"] == ["scopes.identity_read.full_org_warning"]
    assert on["app:manage"]["hint_keys"] == ["scopes.app_manage.deploy_hint"]
    # AC-49 / "endpoints ship later": chat:invoke is issuable but has no surface.
    assert on["chat:invoke"]["endpoints"] == []
    assert on["chat:invoke"]["pending_note_key"]
    # Hover text for the issue form (AC-44) comes from the endpoint list.
    assert {"method": "POST", "path": "/api/v2/workflow/invoke"} in on["workflow:invoke"]["endpoints"]


async def test_module_endpoints_available_when_platform_off(admin_client, monkeypatch, account):
    """AC-49: only the three toolkit scopes follow the switch, never the module."""
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.open_platform, "enabled", False)

    assert _issue(admin_client, account["id"], name="still-works")["status_code"] == 200
    assert _envelope(admin_client.get(f"{BASE}/{account['id']}/keys"))["status_code"] == 200
    assert _envelope(admin_client.post(f"{BASE}/{account['id']}/keys/revoke-all"))["status_code"] == 200
