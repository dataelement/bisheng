"""Wave 1 infrastructure smoke tests (F049 T001-T008).

Guards the pieces that have no test pairing of their own: ORM shape + DAO on a
real (sqlite) session, scope registry invariants (D3 / D9), 260xx error
contract (D10), audit lockstep registration (D11), settings keys (K8) and the
conftest fixtures themselves.

覆盖 AC: AC-05 (validity predicate boundary), AC-06 (no default scopes / unknown
scope detectable), AC-11 (soft revoke keeps the row), AC-13 (toolkit scopes follow
the open-platform switch), AC-14 (``delegate`` is not registered).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    OpenApiCredentialMissingError,
    OpenApiEndpointUnregisteredError,
    OpenApiScopeMissingError,
)
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    get_current_open_api_principal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.open_api.domain.models import ApiCredential, ApiCredentialDao, ServiceAccount, ServiceAccountDao
from bisheng.open_api.domain.models.api_credential import KEY_PREFIX, SUBJECT_KIND_SERVICE_ACCOUNT, mask_key
from bisheng.open_api.domain.scopes import (
    DELEGATE_SCOPE_CODE,
    LOCAL_DEV_TOOLKIT_SCOPES,
    OPEN_API_SCOPE_CODES,
    OPEN_API_SCOPES,
    get_open_api_scope_marker,
    open_api_scope,
    visible_scopes,
)
from test.open_api.conftest import SEED_PASSWORD_PLACEHOLDER

# ---- scope registry (D3 / D9) ------------------------------------------------


def test_registry_maps_38_endpoints_and_excludes_delegate():
    mapped = [ep for scope in OPEN_API_SCOPES for ep in scope.endpoints]
    assert len(mapped) == 38 and len(set(mapped)) == 38
    assert DELEGATE_SCOPE_CODE not in OPEN_API_SCOPE_CODES  # AC-14
    assert "chat:invoke" in OPEN_API_SCOPE_CODES
    chat = next(s for s in OPEN_API_SCOPES if s.code == "chat:invoke")
    assert chat.endpoints == () and chat.pending_note_key


def test_visible_scopes_gate_toolkit_on_open_platform():
    assert LOCAL_DEV_TOOLKIT_SCOPES == {"model:invoke", "identity:read", "app:manage"}
    hidden = {s.code for s in visible_scopes(False)}
    shown = {s.code for s in visible_scopes(True)}
    assert LOCAL_DEV_TOOLKIT_SCOPES.isdisjoint(hidden)
    assert LOCAL_DEV_TOOLKIT_SCOPES <= shown
    assert shown - hidden == LOCAL_DEV_TOOLKIT_SCOPES  # AC-13 / AC-49


def test_marker_roundtrip_and_unknown_scope_rejected():
    @open_api_scope("workflow:invoke", allow_share_token=True)
    async def endpoint():
        return None

    @open_api_scope(None)
    async def whoami():
        return None

    assert get_open_api_scope_marker(endpoint).scope == "workflow:invoke"
    assert get_open_api_scope_marker(endpoint).allow_share_token is True
    assert get_open_api_scope_marker(whoami).scope is None
    assert get_open_api_scope_marker(lambda: None) is None
    with pytest.raises(ValueError):
        open_api_scope("delegate")


# ---- errors (D10) ------------------------------------------------------------


def test_error_codes_carry_real_http_status_and_required_scope():
    assert OpenApiCredentialMissingError.Code == 26001 and OpenApiCredentialMissingError.http_status == 401
    err = OpenApiScopeMissingError(required="workflow:invoke")
    assert err.code == 26003 and err.http_status == 403
    assert err.to_dict()["data"]["required"] == "workflow:invoke"  # AC-04 names the missing scope
    assert OpenApiAuthDependencyUnavailableError.http_status == 503
    assert OpenApiEndpointUnregisteredError.http_status == 500


# ---- audit lockstep (D11) + settings (K8) --------------------------------------


def test_audit_actions_registered_with_namespace():
    from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS, _V2_NAMESPACE_TO_ACTION_PREFIX

    assert _V2_NAMESPACE_TO_ACTION_PREFIX["open_api"] == "open_api."
    for action in (
        "open_api.api_key.issue",
        "open_api.api_key.expire",
        "open_api.ws.connect",
        "open_api.grant.remove_all",
    ):
        assert action in _UI_VISIBLE_V2_ACTIONS


def test_settings_expose_open_platform_and_open_api():
    from bisheng.core.config.open_platform import OpenApiConf
    from bisheng.core.config.settings import Settings

    settings = Settings()
    assert settings.open_platform.enabled is False
    assert settings.open_api.service_account_idle_days == 90
    assert settings.open_api.credential_cache_ttl_seconds == 3
    assert OpenApiConf(credential_cache_ttl_seconds=30).credential_cache_ttl_seconds == 5  # capped


# ---- context -----------------------------------------------------------------


def test_principal_context_var_roundtrip():
    principal = OpenApiPrincipal(subject_kind="service_account", subject_user_id=5, scopes=("app:manage",))
    token = set_current_open_api_principal(principal)
    try:
        assert get_current_open_api_principal().has_scope("app:manage")
    finally:
        reset_current_open_api_principal(token)
    assert get_current_open_api_principal() is None


# ---- ORM + DAO on a real session (T002) ---------------------------------------


async def test_dao_create_lookup_and_validity(oapi_db, human_user, tenant_admin_payload):
    from bisheng.database.models.tenant import UserTenant
    from bisheng.user.domain.models.user import USER_TYPE_SERVICE, User

    now = datetime.now()
    async with oapi_db() as session:
        principal = User(
            user_name="oapi-sa-row",
            password=SEED_PASSWORD_PLACEHOLDER,
            user_type=USER_TYPE_SERVICE,
            source="service_account",
            external_id=None,
        )
        account = await ServiceAccountDao.acreate_with_user(
            session,
            user=principal,
            tenant_id=1,
            resource_owner_user_id=human_user.user_id,
            description="d",
            created_by=tenant_admin_payload.user_id,
        )
        row = await ApiCredentialDao.acreate(
            session,
            ApiCredential(
                tenant_id=1,
                subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
                subject_id=str(account.user_id),
                name="k",
                key_prefix=KEY_PREFIX,
                last4="wxyz",
                token_hash="a" * 64,
                scopes=[],
                expires_at=now + timedelta(hours=1),
            ),
        )
        await session.commit()

        assert principal.user_id == account.user_id and account.is_enabled
        tenants = (await session.exec(select(UserTenant).where(UserTenant.user_id == account.user_id))).all()
        assert [(t.status, t.is_active) for t in tenants] == [("active", 1)]

        found = await ApiCredentialDao.aget_by_hash(session, "a" * 64)
        assert found.id == row.id and found.scopes == [] and found.key_mask == mask_key("wxyz")
        assert found.is_valid_at(now) and not found.is_valid_at(now + timedelta(hours=1))  # boundary = expired

        found.revoked_at = now
        found.revoke_reason = "manual"
        await ApiCredentialDao.aupdate_row(session, found)
        await session.commit()
        still_there = await ApiCredentialDao.aget(session, row.id)
        assert still_there is not None and not still_there.is_valid_at(now)  # soft revoke keeps the row (AC-11)

        rows, total = await ServiceAccountDao.alist_page(session)
        assert total == 1 and rows[0].user_id == account.user_id
        await ServiceAccountDao.aset_timestamps(session, rows[0], disabled_at=now)
        await session.commit()
        assert not (await ServiceAccountDao.aget(session, account.user_id)).is_enabled
        assert (await session.exec(select(ServiceAccount).where(ServiceAccount.user_id == account.user_id))).first()


def test_tenant_admin_payload_is_not_super(tenant_admin_payload):
    assert tenant_admin_payload.is_global_super is False and tenant_admin_payload.user_role == []


async def test_sub_tenant_fixture(sub_tenant, oapi_db):
    from bisheng.database.models.tenant import Tenant

    async with oapi_db() as session:
        tenant = (await session.exec(select(Tenant).where(Tenant.id == sub_tenant.tenant_id))).first()
    assert tenant is not None and tenant.parent_tenant_id == 1
    assert sub_tenant.admin_payload.tenant_id == sub_tenant.tenant_id


async def test_fga_down_raises_unavailable(fga_down):
    from bisheng.permission.application.access import get_f048_runtime

    with pytest.raises(fga_down):
        await get_f048_runtime()


async def test_factories_skip_until_services_exist(service_account_factory, credential_factory):
    # While T010 / T014 are absent both factories skip instead of failing collection.
    await service_account_factory("oapi-sa")
