from types import SimpleNamespace

import pytest

from bisheng.common.errcode.open_api import OpenApiScopeMissingError, PersonalTokenDisabledError
from bisheng.core.context.tenant import current_tenant_id, visible_tenant_ids
from bisheng.open_api.domain.context import OpenApiPrincipal, get_current_open_api_principal
from bisheng.open_api.domain.scopes import OpenApiScopeMarker
from bisheng.open_api.domain.services.access_context import (
    OPEN_API_PRINCIPAL_SCOPE_KEY,
    open_api_access_context,
)
from bisheng.permission.application.identity import get_current_permission_actor


def _principal(*, actor_kind="service_account", scopes=frozenset({"knowledge:read"})):
    is_person = actor_kind == "natural_person"
    return OpenApiPrincipal(
        credential_id=67,
        actor_kind=actor_kind,
        actor_id=23,
        actor_name="f067-caller",
        tenant_id=9,
        resource_owner_user_id=23,
        scopes=scopes,
        authorization_subject_type="user" if is_person else "service_account",
        authorization_subject_id=23,
        effective_user_id=23 if is_person else None,
    )


@pytest.mark.asyncio
async def test_access_context_installs_and_resets_shared_identity_context(monkeypatch):
    principal = _principal()
    scope = {}

    async def _validate(value):
        assert value == "Bearer f067"
        return principal

    async def _resolve(value, **kwargs):
        assert value == principal
        return value

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.access_context.resolve_request_identity",
        _resolve,
    )
    marker = OpenApiScopeMarker(scope="knowledge:read", modes=frozenset({"S"}), session=False)

    async with open_api_access_context(
        authorization="Bearer f067",
        headers=[],
        marker=marker,
        on_behalf_of=None,
        end_user=None,
        connection_scope=scope,
        credential_validator=_validate,
    ) as active:
        assert active == principal
        assert get_current_open_api_principal() == principal
        assert current_tenant_id.get() == 9
        assert visible_tenant_ids.get() == frozenset({1, 9})
        actor = get_current_permission_actor()
        assert actor.subject_type == "service_account"
        assert actor.subject_id == 23
        assert actor.tenant_id == 9
        assert scope[OPEN_API_PRINCIPAL_SCOPE_KEY] == principal

    assert get_current_open_api_principal() is None
    assert get_current_permission_actor() is None
    assert current_tenant_id.get() is None
    assert visible_tenant_ids.get() is None


@pytest.mark.asyncio
async def test_access_context_checks_scope_before_business_execution(monkeypatch):
    principal = _principal(scopes=frozenset())

    async def _validate(value):
        return principal

    marker = OpenApiScopeMarker(scope="knowledge:read", modes=frozenset({"S"}), session=False)
    with pytest.raises(OpenApiScopeMissingError):
        async with open_api_access_context(
            authorization="Bearer f067",
            headers=[],
            marker=marker,
            on_behalf_of=None,
            end_user=None,
            credential_validator=_validate,
        ):
            pass

    assert current_tenant_id.get() is None
    assert visible_tenant_ids.get() is None


@pytest.mark.asyncio
async def test_access_context_enforces_pat_tenant_policy_and_cleans_up():
    principal = _principal(actor_kind="natural_person")

    async def _validate(value):
        return principal

    class _PolicyService:
        @staticmethod
        async def get_policy(tenant_id):
            return SimpleNamespace(enabled=True, data_scope="personal_only")

    marker = OpenApiScopeMarker(scope="knowledge:read", modes=frozenset({"S"}), session=False)
    disabled_settings = SimpleNamespace(open_api=SimpleNamespace(pat_enabled=False))

    with pytest.raises(PersonalTokenDisabledError):
        async with open_api_access_context(
            authorization="Bearer pat",
            headers=[],
            marker=marker,
            on_behalf_of=None,
            end_user=None,
            credential_validator=_validate,
            settings_obj=disabled_settings,
            tenant_setting_service=_PolicyService,
        ):
            pass

    assert get_current_open_api_principal() is None
    assert current_tenant_id.get() is None
