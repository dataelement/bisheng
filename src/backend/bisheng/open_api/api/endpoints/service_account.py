from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.open_api.api.dependencies import get_service_account_admin
from bisheng.open_api.domain.schemas.service_account import (
    ServiceAccountCreate,
    ServiceAccountDetail,
    ServiceAccountPage,
    ServiceAccountUpdate,
)
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService
from bisheng.permission.api.actors import permission_actor
from bisheng.permission.api.dependencies import ResourcePermissionApiPort, get_resource_permission_api
from bisheng.permission.domain.schemas import GrantMutationRequest

router = APIRouter(prefix="/service-accounts", tags=["ServiceAccount"])


@router.get("", response_model=UnifiedResponseModel[ServiceAccountPage])
async def list_service_accounts(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    admin: UserPayload = Depends(get_service_account_admin),
):
    return resp_200(data=await ServiceAccountService.list_page(keyword=keyword, page=page, page_size=page_size))


@router.post("", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def create_service_account(
    data: ServiceAccountCreate,
    admin: UserPayload = Depends(get_service_account_admin),
):
    account = await ServiceAccountService.create(admin, data)
    return resp_200(data=await ServiceAccountService.get_detail(account.id))


@router.get("/{service_account_id}", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def get_service_account(
    service_account_id: int,
    _admin: UserPayload = Depends(get_service_account_admin),
):
    return resp_200(data=await ServiceAccountService.get_detail(service_account_id))


@router.patch("/{service_account_id}", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def update_service_account(
    service_account_id: int,
    data: ServiceAccountUpdate,
    admin: UserPayload = Depends(get_service_account_admin),
):
    await ServiceAccountService.update(admin, service_account_id, data)
    return resp_200(data=await ServiceAccountService.get_detail(service_account_id))


@router.post("/{service_account_id}/enable", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def enable_service_account(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    await ServiceAccountService.enable(admin, service_account_id)
    return resp_200(data=await ServiceAccountService.get_detail(service_account_id))


@router.post("/{service_account_id}/disable", response_model=UnifiedResponseModel[ServiceAccountDetail])
async def disable_service_account(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    await ServiceAccountService.disable(admin, service_account_id)
    return resp_200(data=await ServiceAccountService.get_detail(service_account_id))


@router.delete("/{service_account_id}", response_model=UnifiedResponseModel[dict])
async def delete_service_account(
    service_account_id: int,
    admin: UserPayload = Depends(get_service_account_admin),
):
    await ServiceAccountService.delete(admin, service_account_id)
    return resp_200(data={"id": service_account_id})


@router.get("/{service_account_id}/resource-grants", response_model=UnifiedResponseModel)
async def list_service_account_resource_grants(
    service_account_id: int,
    resource_type: str = Query(min_length=1, max_length=64),
    resource_id: str = Query(min_length=1, max_length=128),
    admin: UserPayload = Depends(get_service_account_admin),
    api: ResourcePermissionApiPort = Depends(get_resource_permission_api),
):
    """List this account's grants on one explicitly selected resource."""

    await ServiceAccountService.get_row(service_account_id)
    page = await api.list_grants(
        resource_type=resource_type,
        resource_id=resource_id,
        actor=await permission_actor(admin),
        cursor=None,
        page_size=200,
    )
    subject_id = str(service_account_id)
    page["data"] = [
        item
        for item in page["data"]
        if item["subject"]["type"] == "service_account" and item["subject"]["id"] == subject_id
    ]
    page["has_more"] = False
    page["next_cursor"] = None
    return resp_200(data=page)


@router.post("/{service_account_id}/resource-grants:mutate", response_model=UnifiedResponseModel)
async def mutate_service_account_resource_grants(
    service_account_id: int,
    body: GrantMutationRequest,
    resource_type: str = Query(min_length=1, max_length=64),
    resource_id: str = Query(min_length=1, max_length=128),
    admin: UserPayload = Depends(get_service_account_admin),
    api: ResourcePermissionApiPort = Depends(get_resource_permission_api),
):
    """Mutate grants while fixing every addressed subject to this account."""

    from bisheng.common.errcode.open_api import ServiceAccountOperationForbiddenError

    await ServiceAccountService.get_row(service_account_id)
    actor = await permission_actor(admin)
    existing = await api.list_grants(
        resource_type=resource_type,
        resource_id=resource_id,
        actor=actor,
        cursor=None,
        page_size=200,
    )
    subject_id = str(service_account_id)
    editable_ids = {
        item["assignee_id"]
        for item in existing["data"]
        if item["subject"]["type"] == "service_account"
        and item["subject"]["id"] == subject_id
        and item["editable"]
        and not item["protected"]
    }
    for change in body.changes:
        if change.subject is not None:
            if change.subject.type != "service_account" or change.subject.id != subject_id:
                raise ServiceAccountOperationForbiddenError()
        elif change.assignee_id not in editable_ids:
            raise ServiceAccountOperationForbiddenError()
    return resp_200(
        data=await api.mutate_grants(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            request=body,
        )
    )
