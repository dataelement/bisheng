"""Service-account management endpoints ``/api/v1/service-accounts/**`` (F049 T023).

Assertion口径 differs from ``test_open_api_auth_api.py`` on purpose (design K4):
this is a ``/api/v1`` surface, so the platform-wide contract applies — HTTP is
**always 200** and the real outcome lives in the envelope ``status_code``. AC-59
"returns 403" is satisfied by ``body["status_code"] == 403``.

Authentication is injected by overriding ``get_service_account_admin``; the
override also seeds the tenant ContextVar, which is what ``CustomMiddleware``
does from the JWT in production. Without that seeding the acting tenant would
default to Root and every cross-tenant assertion here would be vacuous.

覆盖 AC: AC-07, AC-19, AC-20, AC-23, AC-28, AC-41, AC-42, AC-47, AC-48, AC-49, AC-59
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from bisheng.open_api.api.dependencies import get_service_account_admin
from test.open_api.conftest import ROOT_TENANT_ID

BASE = "/api/v1/service-accounts"
WHOAMI = "/api/v2/auth/whoami"


def _as_admin(client, payload) -> None:
    """Admit ``payload`` to the management face and seed its tenant, as the JWT path would."""
    from bisheng.core.context.tenant import set_current_tenant_id

    def _override():
        set_current_tenant_id(payload.tenant_id)
        return payload

    client.app.dependency_overrides[get_service_account_admin] = _override


def _envelope(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


def _created(client, payload, *, name: str, owner_id: int, **extra) -> dict:
    body = _envelope(client.post(BASE, json={"name": name, "resource_owner_user_id": owner_id, **extra}))
    assert body["status_code"] == 200, body
    return body["data"]


@pytest.fixture()
def admin_client(v2_client, oapi_db, redis_client, tenant_admin_payload):
    """Real app + in-process DB/Redis, with the root-tenant admin admitted."""
    _as_admin(v2_client, tenant_admin_payload)
    yield v2_client
    v2_client.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC-41 / AC-59 — the whole module is tenant-admin only
# ---------------------------------------------------------------------------


async def test_non_admin_403_envelope_not_19801(v2_client, oapi_db, redis_client, monkeypatch, human_user):
    """A non-admin is refused with a generic 403, not the LLM read-only copy (19801)."""
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError

    async def _reject(cls, auth_jwt=None):
        raise LLMModelSharedReadonlyError()

    monkeypatch.setattr(UserPayload, "get_tenant_admin_user", classmethod(_reject))

    listing = _envelope(v2_client.get(BASE))
    creating = _envelope(v2_client.post(BASE, json={"name": "x", "resource_owner_user_id": human_user.user_id}))

    for body in (listing, creating):
        assert body["status_code"] == 403
        # AC-41 / AC-59: the message must not be the LLM "Root-shared … read-only" one.
        assert "read-only" not in body["status_message"].lower()
        assert body["status_code"] != 19801


# ---------------------------------------------------------------------------
# AC-23 — create: owner is mandatory and must be an enabled natural person
# ---------------------------------------------------------------------------


async def test_create_requires_name_and_human_owner(admin_client, human_user, tenant_admin_payload):
    missing_owner = _envelope(admin_client.post(BASE, json={"name": "no-owner"}))
    assert missing_owner["status_code"] == 422

    created = _created(admin_client, tenant_admin_payload, name="ci-bot", owner_id=human_user.user_id)
    assert created["id"] > 0
    assert created["name"] == "ci-bot"
    assert created["resource_owner"]["user_id"] == human_user.user_id

    # The service account just created is itself not a natural person.
    not_a_person = _envelope(admin_client.post(BASE, json={"name": "nested", "resource_owner_user_id": created["id"]}))
    assert not_a_person["status_code"] == 26021

    unknown = _envelope(admin_client.post(BASE, json={"name": "ghost", "resource_owner_user_id": 987654}))
    assert unknown["status_code"] == 26021


async def test_create_tenant_from_admin_scope(v2_client, oapi_db, redis_client, sub_tenant):
    """AC-23: the tenant comes from the admin's current scope, never from the body (pit 23)."""
    from bisheng.common.middleware.admin_scope import MANAGEMENT_API_PREFIXES

    # Without the prefix a super admin's ScopeBar would not apply to this surface
    # and every creation would silently land in Root.
    assert any(BASE.startswith(prefix) for prefix in MANAGEMENT_API_PREFIXES)

    _as_admin(v2_client, sub_tenant.admin_payload)
    try:
        created = _created(
            v2_client,
            sub_tenant.admin_payload,
            name="sub-bot",
            owner_id=sub_tenant.admin_user_id,
            tenant_id=ROOT_TENANT_ID,  # a body-supplied tenant must be ignored
        )
    finally:
        v2_client.app.dependency_overrides.clear()

    assert created["tenant_id"] == sub_tenant.tenant_id


# ---------------------------------------------------------------------------
# AC-07 — tenant isolation of the list / detail surface
# ---------------------------------------------------------------------------


async def test_list_tenant_isolated(v2_client, oapi_db, redis_client, human_user, sub_tenant, tenant_admin_payload):
    _as_admin(v2_client, tenant_admin_payload)
    root_account = _created(v2_client, tenant_admin_payload, name="root-bot", owner_id=human_user.user_id)

    _as_admin(v2_client, sub_tenant.admin_payload)
    sub_account = _created(v2_client, sub_tenant.admin_payload, name="sub-bot", owner_id=sub_tenant.admin_user_id)

    page = _envelope(v2_client.get(BASE))["data"]
    assert [row["id"] for row in page["data"]] == [sub_account["id"]]
    assert page["total"] == 1

    # A child-tenant admin's ``visible_tenant_ids`` is {leaf, Root}; the auto
    # filter would therefore hand them Root's rows on an IN-list. AC-07 demands
    # strict "own tenant only", so the read is pinned explicitly.
    cross = _envelope(v2_client.get(f"{BASE}/{root_account['id']}"))
    assert cross["status_code"] == 26020

    v2_client.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC-42 / AC-28 — list columns
# ---------------------------------------------------------------------------


async def test_list_columns(admin_client, human_user, tenant_admin_payload, credential_factory):
    account = _created(admin_client, tenant_admin_payload, name="col-bot", owner_id=human_user.user_id)
    await credential_factory(account["id"], scopes=["workflow:read"])

    page = _envelope(admin_client.get(BASE))["data"]
    row = next(item for item in page["data"] if item["id"] == account["id"])

    assert row["name"] == "col-bot"
    assert row["status"] == "enabled"
    assert row["active_key_count"] == 1  # 0 is what the UI highlights (AC-42)
    assert row["resource_owner"]["user_id"] == human_user.user_id
    assert row["owner_disabled"] is False
    assert "last_used_at" in row
    assert row["created_by"] == tenant_admin_payload.user_id
    assert row["create_time"] is not None
    # The idle threshold travels with the page so the UI does not hardcode 90.
    assert page["idle_days"] == 90
    assert row["idle"] is True  # never called yet


async def test_owner_disabled_flag_and_keys_still_valid(
    admin_client, oapi_db, human_user, tenant_admin_payload, credential_factory
):
    """AC-28: disabling the owner flags the row but never breaks the integration."""
    from bisheng.user.domain.models.user import User

    account = _created(admin_client, tenant_admin_payload, name="owner-bot", owner_id=human_user.user_id)
    issued = await credential_factory(account["id"], scopes=[])

    async with oapi_db() as session:
        owner = (await session.exec(select(User).where(User.user_id == human_user.user_id))).first()
        owner.delete = 1
        session.add(owner)
        await session.commit()

    page = _envelope(admin_client.get(BASE))["data"]
    row = next(item for item in page["data"] if item["id"] == account["id"])
    assert row["owner_disabled"] is True
    assert row["resource_owner"]["disabled"] is True
    assert row["status"] == "enabled"

    still_working = admin_client.get(WHOAMI, headers={"Authorization": f"Bearer {issued.plaintext}"})
    assert still_working.status_code == 200


# ---------------------------------------------------------------------------
# AC-19 — created accounts are immediately grantable
# ---------------------------------------------------------------------------


async def test_created_account_grantable(admin_client, human_user, tenant_admin_payload):
    from bisheng.database.models.tenant import UserTenantDao

    account = _created(admin_client, tenant_admin_payload, name="grant-bot", owner_id=human_user.user_id)

    active = await UserTenantDao.aget_active_user_tenant(account["id"])
    # pit 8: without ``is_active=1`` F048 subject validation refuses the account
    # and the whole authorization tab is dead on arrival.
    assert active is not None
    assert active.is_active == 1
    assert active.status == "active"
    assert active.tenant_id == ROOT_TENANT_ID


# ---------------------------------------------------------------------------
# AC-20 — people-facing user endpoints refuse the account we just created
# ---------------------------------------------------------------------------


async def test_human_user_endpoints_reject_service_account(admin_client, human_user, tenant_admin_payload):
    from bisheng.common.errcode.open_api import ServiceAccountOperationForbiddenError
    from bisheng.user.api.user import reset_password, update

    account = _created(admin_client, tenant_admin_payload, name="people-bot", owner_id=human_user.user_id)
    login_user = type("Stub", (), {"user_id": 1, "is_admin": lambda self: True})()

    payload = type("Payload", (), {"user_id": account["id"], "delete": 1, "avatar": None})()
    with pytest.raises(ServiceAccountOperationForbiddenError) as disabled:
        await update(request=None, user=payload, login_user=login_user)
    assert disabled.value.code == 26022

    with pytest.raises(ServiceAccountOperationForbiddenError):
        await reset_password(user_id=account["id"], password="x", login_user=login_user)


# ---------------------------------------------------------------------------
# AC-47 / AC-48 — disable / enable / delete
# ---------------------------------------------------------------------------


async def test_disable_enable_keeps_config(admin_client, human_user, tenant_admin_payload, credential_factory):
    account = _created(admin_client, tenant_admin_payload, name="toggle-bot", owner_id=human_user.user_id)
    issued = await credential_factory(account["id"], scopes=["workflow:read"])
    auth = {"Authorization": f"Bearer {issued.plaintext}"}

    disabled = _envelope(admin_client.post(f"{BASE}/{account['id']}/disable"))
    assert disabled["status_code"] == 200
    assert disabled["data"]["status"] == "disabled"

    rejected = admin_client.get(WHOAMI, headers=auth)
    assert rejected.status_code == 401
    assert rejected.json()["status_code"] == 26027

    # AC-47: the configuration survives the disabled state untouched.
    patched = _envelope(
        admin_client.patch(f"{BASE}/{account['id']}", json={"name": "toggle-bot-2", "description": "renamed"})
    )
    assert patched["data"]["name"] == "toggle-bot-2"
    assert patched["data"]["resource_owner"]["user_id"] == human_user.user_id

    enabled = _envelope(admin_client.post(f"{BASE}/{account['id']}/enable"))
    assert enabled["data"]["status"] == "enabled"

    restored = admin_client.get(WHOAMI, headers=auth)
    assert restored.status_code == 200
    # Same key, same scopes — "restored exactly as it was".
    assert restored.json()["data"]["scopes"] == ["workflow:read"]


async def test_delete_second_confirm_payload_and_effect(
    admin_client, human_user, tenant_admin_payload, credential_factory
):
    account = _created(admin_client, tenant_admin_payload, name="doomed-bot", owner_id=human_user.user_id)
    issued = await credential_factory(account["id"], scopes=[])
    auth = {"Authorization": f"Bearer {issued.plaintext}"}

    deleted = _envelope(admin_client.delete(f"{BASE}/{account['id']}"))
    assert deleted["status_code"] == 200
    # AC-48 confirm payload. Wave 1 has no grant reverse-lookup yet, so the list
    # is structurally empty until T065 fills it — the field must exist regardless
    # so the front end never has to branch on its presence.
    assert deleted["data"]["grants"] == []
    assert deleted["data"]["id"] == account["id"]

    gone = admin_client.get(WHOAMI, headers=auth)
    assert gone.status_code in (401,)
    assert _envelope(admin_client.get(f"{BASE}/{account['id']}"))["status_code"] == 26020

    page = _envelope(admin_client.get(BASE))["data"]
    assert account["id"] not in [row["id"] for row in page["data"]]


# ---------------------------------------------------------------------------
# AC-49 — the module does not depend on the open-platform switch
# ---------------------------------------------------------------------------


async def test_module_always_on_when_platform_off(admin_client, monkeypatch, human_user, tenant_admin_payload):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.open_platform, "enabled", False)

    account = _created(admin_client, tenant_admin_payload, name="always-on", owner_id=human_user.user_id)
    assert _envelope(admin_client.get(f"{BASE}/{account['id']}"))["status_code"] == 200
    assert _envelope(admin_client.get(BASE))["status_code"] == 200
    assert _envelope(admin_client.post(f"{BASE}/{account['id']}/disable"))["status_code"] == 200
    assert _envelope(admin_client.post(f"{BASE}/{account['id']}/enable"))["status_code"] == 200
