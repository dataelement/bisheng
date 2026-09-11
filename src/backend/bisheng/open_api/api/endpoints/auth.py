from fastapi import APIRouter, Depends

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.open_api.api.dependencies import get_open_api_execution
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.schemas.credential import WhoamiResourceOwner, WhoamiResponse
from bisheng.open_api.domain.scopes import open_api_scope

router = APIRouter(prefix="/auth", tags=["OpenAPI", "Auth"])


@router.get("/whoami", response_model=UnifiedResponseModel[WhoamiResponse])
@open_api_scope(None)
async def whoami(principal: OpenApiPrincipal = Depends(get_open_api_execution)):
    credential = await CredentialRepository.get(principal.credential_id)
    resource_owner = (
        WhoamiResourceOwner(user_id=principal.resource_owner_user_id)
        if principal.resource_owner_user_id is not None
        else None
    )
    return resp_200(
        data=WhoamiResponse(
            credential_id=principal.credential_id,
            actor_kind=principal.actor_kind,
            actor_id=principal.actor_id,
            actor_name=principal.actor_name,
            tenant_id=principal.tenant_id,
            resource_owner=resource_owner,
            authorization_subject_type=principal.authorization_subject_type,
            authorization_subject_id=principal.authorization_subject_id,
            effective_user_id=principal.effective_user_id,
            mode=principal.mode,
            scopes=sorted(principal.scopes),
            key_mask=credential.key_mask if credential is not None else "",
            expires_at=credential.expires_at if credential is not None else None,
        )
    )
