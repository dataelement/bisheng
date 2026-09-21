"""Transport-neutral Open API identity and permission context lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from typing import Any

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    OpenApiAuthError,
    OpenApiDelegationModeUnsupportedError,
    OpenApiEndpointUnregisteredError,
    OpenApiScopeMissingError,
    PersonalTokenDisabledError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, current_tenant_id, visible_tenant_ids
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.open_api.domain.scopes import OpenApiScopeMarker
from bisheng.open_api.domain.services.credential_validator import validate_bearer
from bisheng.open_api.domain.services.identity_service import (
    assert_no_removed_identity_headers,
    resolve_request_identity,
)
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
from bisheng.permission.application.identity import (
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor

OPEN_API_PRINCIPAL_SCOPE_KEY = "open_api_principal"
BeforeIdentityCheck = Callable[[], Awaitable[None]]
CredentialValidator = Callable[[str | None], Awaitable[OpenApiPrincipal]]


@asynccontextmanager
async def open_api_access_context(
    *,
    authorization: str | None,
    headers: Iterable[tuple[str, str]],
    marker: OpenApiScopeMarker | None,
    on_behalf_of: str | None,
    end_user: str | None,
    connection_scope: dict[str, Any] | None = None,
    before_identity_check: BeforeIdentityCheck | None = None,
    credential_validator: CredentialValidator = validate_bearer,
    settings_obj: Any = settings,
    tenant_setting_service: Any = TenantSettingService,
) -> AsyncIterator[OpenApiPrincipal]:
    """Authenticate and install the same execution context for HTTP or MCP."""

    principal = await credential_validator(authorization)
    tenant_token = current_tenant_id.set(principal.tenant_id)
    visible_token = visible_tenant_ids.set(frozenset({DEFAULT_TENANT_ID, principal.tenant_id}))
    principal_token = None
    permission_token = None
    if connection_scope is not None:
        connection_scope[OPEN_API_PRINCIPAL_SCOPE_KEY] = principal
    pat_data_scope = DATA_SCOPE_ALL
    try:
        if principal.actor_kind == "natural_person":
            if not settings_obj.open_api.pat_enabled:
                raise PersonalTokenDisabledError()
            try:
                tenant_policy = await tenant_setting_service.get_policy(principal.tenant_id)
            except OpenApiAuthError:
                raise
            except Exception as exc:
                raise OpenApiAuthDependencyUnavailableError() from exc
            if not tenant_policy.enabled:
                raise PersonalTokenDisabledError()
            pat_data_scope = tenant_policy.data_scope

        if marker is None:
            raise OpenApiEndpointUnregisteredError()
        if marker.scope is not None and not principal.has_scope(marker.scope):
            raise OpenApiScopeMissingError(required=marker.scope)

        assert_no_removed_identity_headers(headers)
        if before_identity_check is not None:
            await before_identity_check()
        principal = await resolve_request_identity(
            principal,
            on_behalf_of=on_behalf_of,
            end_user=end_user,
        )
        if connection_scope is not None:
            connection_scope[OPEN_API_PRINCIPAL_SCOPE_KEY] = principal
        if principal.mode not in marker.modes:
            raise OpenApiDelegationModeUnsupportedError()

        super_admin = False
        tenant_admin_tenant_ids: frozenset[int] = frozenset()
        if principal.actor_kind == "natural_person":
            from bisheng.permission.application.relation_api import is_tenant_admin
            from bisheng.utils.http_middleware import _check_is_global_super

            try:
                super_admin = await _check_is_global_super(principal.actor_id)
                if not super_admin and await is_tenant_admin(principal.actor_id, principal.tenant_id):
                    tenant_admin_tenant_ids = frozenset({principal.tenant_id})
            except OpenApiAuthError:
                raise
            except Exception as exc:
                raise OpenApiAuthDependencyUnavailableError() from exc

        actor = PermissionActor(
            subject_type=principal.authorization_subject_type,
            subject_id=principal.authorization_subject_id,
            tenant_id=principal.tenant_id,
            super_admin=super_admin,
            tenant_admin_tenant_ids=tenant_admin_tenant_ids,
            data_scope=pat_data_scope,
        )
        principal_token = set_current_open_api_principal(principal)
        permission_token = set_current_permission_actor(actor)
        yield principal
    finally:
        if permission_token is not None:
            reset_current_permission_actor(permission_token)
        if principal_token is not None:
            reset_current_open_api_principal(principal_token)
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)


__all__ = ["OPEN_API_PRINCIPAL_SCOPE_KEY", "open_api_access_context"]
