from fastapi import APIRouter, Depends, Path, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import PageData, UnifiedResponseModel, resp_200
from bisheng.knowledge.application.provider_diagnostics import list_provider_operations
from bisheng.knowledge.domain.schemas.provider_diagnostics import ProviderOperationDiagnostic

router = APIRouter(tags=["knowledge_processing"])


@router.get(
    "/{space_id}/provider-operations", response_model=UnifiedResponseModel[PageData[ProviderOperationDiagnostic]]
)
async def provider_operations(
    space_id: int = Path(gt=0, le=2**63 - 1),
    page: int = Query(default=1, ge=1, le=2**31 - 1),
    page_size: int = Query(default=20, ge=1, le=100),
    identity: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await list_provider_operations(identity, space_id, page, page_size))
