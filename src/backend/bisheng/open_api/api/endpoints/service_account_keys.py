from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.open_api import ServiceAccountInactiveError
from bisheng.common.errcode.permission import AuthorizationModelMismatchError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.common.services.config_service import settings
from bisheng.open_api.api.dependencies import get_service_account_admin
from bisheng.open_api.domain.models.api_credential import (
    REVOKE_REASON_BATCH,
    REVOKE_REASON_MANUAL,
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
from bisheng.open_api.domain.scopes import ISSUABLE_OPEN_API_SCOPE_CODES, OPEN_API_SCOPE_MAP
from bisheng.open_api.domain.services.credential_service import CredentialService
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService
from bisheng.permission.application.process_runtime import ensure_f048_process_runtime_ready

router = APIRouter(prefix="/service-accounts", tags=["ServiceAccount"])
scopes_router = APIRouter(prefix="/service-accounts", tags=["ServiceAccount"])


@scopes_router.get("/scopes", response_model=UnifiedResponseModel[OpenApiScopeCatalog])
async def list_open_api_scopes(_admin: UserPayload = Depends(get_service_account_admin)):
    items = []
    for code in sorted(ISSUABLE_OPEN_API_SCOPE_CODES):
        scope = OPEN_API_SCOPE_MAP[code]
        items.append(
            OpenApiScopeItem(
                code=code,
                endpoints=[f"{method} {path}" for method, path in scope.endpoints],
            )
        )
    return resp_200(
        data=OpenApiScopeCatalog(
            scopes=items,
            open_platform_enabled=settings.open_platform.enabled,
        )
    )


async def _account(service_account_id: int):
    return await ServiceAccountService.get_row(service_account_id)


@router.get("/{service_account_id}/keys", response_model=UnifiedResponseModel[list[KeyItem]])
async def list_keys(
    service_account_id: int,
    _admin: UserPayload = Depends(get_service_account_admin),
):
    await _account(service_account_id)
    return resp_200(data=await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, service_account_id))


@router.post("/{service_account_id}/keys", response_model=UnifiedResponseModel[KeyIssuedResponse])
async def issue_key(
    service_account_id: int,
    data: KeyIssueRequest,
    admin: UserPayload = Depends(get_service_account_admin),
):
    account = await _account(service_account_id)
    if not account.is_enabled:
        raise ServiceAccountInactiveError()
    if not settings.openfga.enabled:
        raise AuthorizationModelMismatchError(msg="Service-account authorization model is not enabled")
    await ensure_f048_process_runtime_ready(expected_role="api")
    issued = await CredentialService.issue(
        tenant_id=account.tenant_id,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=service_account_id,
        request=data,
        created_by=admin.user_id,
        audit_operator=admin,
    )
    return resp_200(data=issued)


@router.patch("/{service_account_id}/keys/{key_id}", response_model=UnifiedResponseModel[KeyItem])
async def update_key(
    service_account_id: int,
    key_id: int,
    data: KeyUpdateRequest,
    admin: UserPayload = Depends(get_service_account_admin),
):
    await _account(service_account_id)
    item = await CredentialService.update(
        SUBJECT_KIND_SERVICE_ACCOUNT,
        service_account_id,
        key_id,
        data,
        audit_operator=admin,
    )
    return resp_200(data=item)


@router.post("/{service_account_id}/keys/revoke-all", response_model=UnifiedResponseModel[dict])
async def revoke_all_keys(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    await _account(service_account_id)
    count = await CredentialService.revoke_by_subject(
        SUBJECT_KIND_SERVICE_ACCOUNT,
        service_account_id,
        reason=REVOKE_REASON_BATCH,
        audit_operator=admin,
    )
    return resp_200(data={"revoked": count})


@router.post("/{service_account_id}/keys/{key_id}/revoke", response_model=UnifiedResponseModel[KeyItem])
async def revoke_key(
    service_account_id: int,
    key_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    await _account(service_account_id)
    item = await CredentialService.revoke(
        SUBJECT_KIND_SERVICE_ACCOUNT,
        service_account_id,
        key_id,
        reason=REVOKE_REASON_MANUAL,
        audit_operator=admin,
    )
    return resp_200(data=item)
