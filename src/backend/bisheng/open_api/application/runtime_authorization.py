"""Re-enter existing OpenAPI admission from a persisted credential reference."""

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.scopes import OpenApiScopeMarker
from bisheng.open_api.domain.services.access_context import open_api_access_context
from bisheng.open_api.domain.services.credential_validator import SUBJECT_RESOLVERS
from bisheng.open_api.domain.services.service_account_tenancy import revalidate_service_account


@asynccontextmanager
async def runtime_credential_context(reference):
    if reference.get("kind") != "api_credential" or type(reference.get("credential_id")) is not int:
        raise PermissionDeniedError(reason="runtime_credential_unavailable")
    row = await CredentialRepository.get(reference["credential_id"])
    if row is None or row.tenant_id != reference.get("tenant_id") or not row.is_valid_at(datetime.now()):
        raise PermissionDeniedError(reason="runtime_credential_invalid")
    # This release's local-development app management is an S-mode service-account face.
    if row.subject_kind != "service_account":
        raise PermissionDeniedError(reason="runtime_credential_mode_refused")
    principal = await revalidate_service_account(await SUBJECT_RESOLVERS[row.subject_kind](row))

    async def validator(_):
        return principal

    async with open_api_access_context(
        authorization=None,
        headers=(),
        marker=OpenApiScopeMarker("app:manage", frozenset({"S"}), False),
        on_behalf_of=None,
        end_user=None,
        credential_validator=validator,
    ) as fresh:
        yield fresh


@contextmanager
def without_open_api_identity():
    from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal

    token = set_current_open_api_principal(None)
    try:
        yield
    finally:
        reset_current_open_api_principal(token)
