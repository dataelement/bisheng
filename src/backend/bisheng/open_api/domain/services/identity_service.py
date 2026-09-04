"""Identity-header validation and delegated-subject resolution."""

from __future__ import annotations

from collections.abc import Iterable

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    OpenApiDelegationHeaderRequiredError,
    OpenApiDelegationNotAllowedError,
    OpenApiDelegationTargetInvalidError,
    OpenApiEndUserInvalidError,
    OpenApiIdentityHeaderConflictError,
    OpenApiPrivilegedTargetError,
    OpenApiRemovedIdentityInputError,
)
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.repositories.owner_repository import OwnerRepository
from bisheng.open_api.domain.services.delegate_scope_service import DelegateScopeService

ON_BEHALF_OF_HEADER = "X-On-Behalf-Of"
END_USER_HEADER = "X-End-User"


def assert_no_removed_identity_headers(headers: Iterable[tuple[str, str]]) -> None:
    allowed = {ON_BEHALF_OF_HEADER.lower(), END_USER_HEADER.lower()}
    for name, _value in headers:
        normalized = name.lower()
        if normalized not in allowed and (
            normalized.endswith("-on-behalf-of") or normalized.endswith("-end-user")
        ):
            raise OpenApiRemovedIdentityInputError()


def parse_identity_headers(
    *,
    on_behalf_of: str | None,
    end_user: str | None,
) -> tuple[int | None, str | None]:
    if on_behalf_of is not None and end_user is not None:
        raise OpenApiIdentityHeaderConflictError()
    target_id = None
    if on_behalf_of is not None:
        if not on_behalf_of.isascii() or not on_behalf_of.isdecimal() or int(on_behalf_of) <= 0:
            raise OpenApiDelegationTargetInvalidError()
        target_id = int(on_behalf_of)
    if end_user is not None:
        encoded = end_user.encode("utf-8")
        if not end_user or len(encoded) > 128 or any(byte < 0x20 or byte > 0x7E for byte in encoded):
            raise OpenApiEndUserInvalidError()
    return target_id, end_user


async def resolve_request_identity(
    principal: OpenApiPrincipal,
    *,
    on_behalf_of: str | None,
    end_user: str | None,
) -> OpenApiPrincipal:
    target_id, external_user_id = parse_identity_headers(
        on_behalf_of=on_behalf_of,
        end_user=end_user,
    )
    has_delegate = principal.has_scope("delegate")
    if target_id is None:
        if has_delegate:
            raise OpenApiDelegationHeaderRequiredError()
        return principal.model_copy(update={"end_user_id": external_user_id})

    if principal.actor_kind != "service_account" or not has_delegate:
        raise OpenApiDelegationNotAllowedError()

    try:
        target = await OwnerRepository.get_active_natural_person(target_id)
        if target is None or target.tenant_id != principal.tenant_id:
            raise OpenApiDelegationTargetInvalidError()
        if await _is_privileged_target(target_id, principal.tenant_id):
            raise OpenApiPrivilegedTargetError()
        if not await DelegateScopeService.target_allowed(principal.credential_id, target_id):
            raise OpenApiDelegationNotAllowedError()
    except (
        OpenApiDelegationNotAllowedError,
        OpenApiDelegationTargetInvalidError,
        OpenApiPrivilegedTargetError,
    ):
        raise
    except Exception as exc:
        raise OpenApiAuthDependencyUnavailableError() from exc

    return principal.model_copy(
        update={
            "mode": "D",
            "authorization_subject_type": "user",
            "authorization_subject_id": target_id,
            "effective_user_id": target_id,
            "resource_owner_user_id": target_id,
            "on_behalf_of_user_id": target_id,
            "end_user_id": None,
        }
    )


async def _is_privileged_target(user_id: int, tenant_id: int) -> bool:
    from bisheng.permission.application.relation_api import is_tenant_admin
    from bisheng.utils.http_middleware import _check_is_global_super

    return await _check_is_global_super(user_id) or await is_tenant_admin(user_id, tenant_id)


__all__ = [
    "END_USER_HEADER",
    "ON_BEHALF_OF_HEADER",
    "assert_no_removed_identity_headers",
    "parse_identity_headers",
    "resolve_request_identity",
]
