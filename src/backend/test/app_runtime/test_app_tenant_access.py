"""F113: owner equality never substitutes for the authenticated tenant."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_runtime.application.tenant_access import require_app_request_tenant
from bisheng.app_runtime.domain.services.app_data_service import AppDataService
from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService
from bisheng.app_runtime.domain.services.app_query_service import AppQueryService
from bisheng.app_runtime.domain.services.app_state_service import AppStateService
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)


def actor(tenant=1, *, owner=True, super_admin=False):
    return SimpleNamespace(user_id=21 if owner else 22, tenant_id=tenant, is_global_super=super_admin)


def app():
    return SimpleNamespace(id="f113", tenant_id=1, owner_user_id=21)


@pytest.mark.parametrize("method", ["operator", "deleter", "editor", "data", "logs"])
async def test_moved_owner_is_refused_before_role_shortcuts(method, monkeypatch):
    target = app()
    moved = actor(2)
    token = current_tenant_id.set(1)
    try:
        with pytest.raises(AppNotFoundError):
            if method == "operator":
                await AppStateService._require_operator(target, moved)
            elif method == "deleter":
                await AppStateService._require_deleter(target, moved)
            elif method == "editor":
                await AppMetaService._require_editor(target, moved)
            elif method == "data":
                AppDataService._require_owner(target, moved)
            else:
                await AppQueryService._require_log_access(target, moved, entry="detail")
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize("allow_super", [False, True])
def test_global_super_exception_is_explicit(allow_super):
    caller = actor(2, super_admin=True)
    if allow_super:
        require_app_request_tenant(1, caller, allow_global_super=True)
    else:
        with pytest.raises(AppNotFoundError):
            require_app_request_tenant(1, caller)


def test_no_actor_does_not_create_a_background_bypass():
    with pytest.raises(AppNotFoundError):
        require_app_request_tenant(1, None, allow_global_super=True)


async def test_same_tenant_still_requires_the_original_business_permission(monkeypatch):
    from bisheng.app_runtime.domain.services import app_state_service
    from bisheng.common.errcode.app_factory import AppManageForbiddenError

    require_app_request_tenant(1, actor(owner=False))
    monkeypatch.setattr(app_state_service, "check_tenant_admin", AsyncMock(return_value=False))
    with pytest.raises(AppManageForbiddenError):
        await AppStateService._require_operator(app(), actor(owner=False))
    await AppStateService._require_operator(app(), actor())


def test_credential_tenant_overrides_compatibility_owner_and_cannot_borrow_admin():
    principal = OpenApiPrincipal(
        credential_id=9,
        actor_kind="service_account",
        actor_id=3,
        actor_name="f113",
        tenant_id=2,
        resource_owner_user_id=21,
        scopes=frozenset({"app:manage"}),
        authorization_subject_type="service_account",
        authorization_subject_id=3,
        effective_user_id=None,
    )
    token = set_current_open_api_principal(principal)
    try:
        with pytest.raises(AppNotFoundError):
            require_app_request_tenant(1, actor(1, super_admin=True), allow_global_super=True)
    finally:
        reset_current_open_api_principal(token)
