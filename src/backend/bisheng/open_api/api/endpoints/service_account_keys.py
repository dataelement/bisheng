"""API-key endpoints + the scope catalogue, under ``/api/v1/service-accounts`` (F049 §4.2).

Every key operation addresses its **owning account first**: the account read is
what applies tenant scoping (26020), and only then is the key resolved inside
that subject (26026 for a foreign key id). Doing it the other way round — key id
first — would let one tenant probe another tenant's key id space.

``POST /{id}/keys`` is the single place in the platform where a credential
plaintext is ever returned (AC-02).

``GET /scopes`` lives in its own router so ``bisheng/open_api/api/router.py`` can
register it **before** ``GET /{service_account_id}``: FastAPI matches in
registration order, and "scopes" is not an int.
"""

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.common.services.config_service import settings
from bisheng.open_api.api.dependencies import get_service_account_admin
from bisheng.open_api.domain.models.api_credential import (
    REVOKE_REASON_BATCH,
    SUBJECT_KIND_SERVICE_ACCOUNT,
)
from bisheng.open_api.domain.schemas.credential import (
    KeyIssuedResponse,
    KeyIssueRequest,
    KeyItem,
    KeyUpdateRequest,
    OpenApiScopeCatalog,
    OpenApiScopeItem,
)
from bisheng.open_api.domain.scopes import visible_scopes
from bisheng.open_api.domain.services.credential_service import CredentialService
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService

router = APIRouter(prefix="/service-accounts", tags=["ServiceAccount"])
scopes_router = APIRouter(prefix="/service-accounts", tags=["ServiceAccount"])


@scopes_router.get("/scopes", response_model=UnifiedResponseModel[OpenApiScopeCatalog])
async def list_open_api_scopes(admin: UserPayload = Depends(get_service_account_admin)):
    """Grantable permission bits of *this* deployment (AC-13 / AC-44 / AC-49).

    The three ``local_dev_toolkit`` bits appear only where the open platform is
    deployed — the same predicate that rejects them at issue time (26023), so the
    form can never offer a bit the service would refuse.
    """
    enabled = bool(settings.open_platform.enabled)
    return resp_200(
        data=OpenApiScopeCatalog(
            scopes=[OpenApiScopeItem.from_registry(scope) for scope in visible_scopes(enabled)],
            open_platform_enabled=enabled,
        )
    )


async def _assert_account(admin: UserPayload, service_account_id: int) -> None:
    """Resolve the account in the admin's tenant first — 26020 before anything else."""
    await ServiceAccountService.get_detail(admin, service_account_id)


@router.get("/{service_account_id}/keys", response_model=UnifiedResponseModel[list[KeyItem]])
async def list_keys(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    """Masked view of every key of the account, newest first (AC-44)."""
    await _assert_account(admin, service_account_id)
    return resp_200(data=await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, str(service_account_id)))


@router.post("/{service_account_id}/keys", response_model=UnifiedResponseModel[KeyIssuedResponse])
async def issue_key(
    service_account_id: int,
    data: KeyIssueRequest,
    admin: UserPayload = Depends(get_service_account_admin),
):
    """Mint a key. The ``plaintext`` in this response is the only copy that exists (AC-02)."""
    # A disabled / deleted account must not gain new credentials: ``get_detail``
    # hides deleted rows (26020) and the enabled check below covers the rest.
    detail = await ServiceAccountService.get_detail(admin, service_account_id)
    if detail.status != "enabled":
        from bisheng.common.errcode.open_api import ServiceAccountInactiveError

        raise ServiceAccountInactiveError()
    return resp_200(
        data=await CredentialService.issue(admin, SUBJECT_KIND_SERVICE_ACCOUNT, str(service_account_id), data)
    )


@router.patch("/{service_account_id}/keys/{key_id}", response_model=UnifiedResponseModel[KeyItem])
async def update_key(
    service_account_id: int,
    key_id: int,
    data: KeyUpdateRequest,
    admin: UserPayload = Depends(get_service_account_admin),
):
    """Edit name / scopes / expiry — same key, effective on the next call (AC-08)."""
    await _assert_account(admin, service_account_id)
    return resp_200(
        data=await CredentialService.update(admin, SUBJECT_KIND_SERVICE_ACCOUNT, str(service_account_id), key_id, data)
    )


@router.post("/{service_account_id}/keys/revoke-all", response_model=UnifiedResponseModel[dict])
async def revoke_all_keys(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    """Revoke every still-valid key of the account within 5s (AC-09 / AC-46)."""
    await _assert_account(admin, service_account_id)
    revoked = await CredentialService.revoke_by_subject(
        admin, SUBJECT_KIND_SERVICE_ACCOUNT, str(service_account_id), reason=REVOKE_REASON_BATCH
    )
    return resp_200(data={"revoked": revoked})


@router.post("/{service_account_id}/keys/{key_id}/revoke", response_model=UnifiedResponseModel[KeyItem])
async def revoke_key(
    service_account_id: int,
    key_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    """Soft revoke: the row and its history stay for audit (AC-11)."""
    await _assert_account(admin, service_account_id)
    return resp_200(
        data=await CredentialService.revoke(admin, SUBJECT_KIND_SERVICE_ACCOUNT, str(service_account_id), key_id)
    )
