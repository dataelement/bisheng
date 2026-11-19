"""Static scope/owner routes precede the service-account id lookup."""

from fastapi import APIRouter, Depends, Query, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import PageData, UnifiedResponseModel, resp_200
from bisheng.open_api.api.dependencies import get_service_account_admin, get_service_account_manager
from bisheng.open_api.domain.schemas.service_account_scope import (
    ServiceAccountOwnerCandidate,
    ServiceAccountScopeInput,
    ServiceAccountScopeResult,
)
from bisheng.open_api.domain.services.service_account_scope_service import ServiceAccountScopeService
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService

router = APIRouter(prefix="/service-accounts", tags=["ServiceAccount"])


@router.get("/management-scope", response_model=UnifiedResponseModel[ServiceAccountScopeResult])
async def management_scope(admin: UserPayload = Depends(get_service_account_admin)):
    return resp_200(data=await ServiceAccountScopeService.get_scope(admin))


@router.put("/management-scope", response_model=UnifiedResponseModel[ServiceAccountScopeResult])
async def change_management_scope(
    body: ServiceAccountScopeInput,
    request: Request,
    admin: UserPayload = Depends(get_service_account_admin),
):
    return resp_200(
        data=await ServiceAccountScopeService.set_scope(
            admin,
            body.tenant_id,
            {"ip": request.client.host if request.client else None, "ua": request.headers.get("user-agent")},
        )
    )


@router.get("/owner-candidates", response_model=UnifiedResponseModel[PageData[ServiceAccountOwnerCandidate]])
async def owner_candidates(
    keyword: str | None = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _admin: UserPayload = Depends(get_service_account_manager),
):
    people, total = await ServiceAccountService.owner_candidates(keyword=keyword, page=page, page_size=page_size)
    return resp_200(
        data=PageData(
            data=[
                ServiceAccountOwnerCandidate(
                    user_id=person.user_id,
                    user_name=person.user_name,
                    tenant_id=person.tenant_id,
                )
                for person in people
            ],
            total=total,
        )
    )
