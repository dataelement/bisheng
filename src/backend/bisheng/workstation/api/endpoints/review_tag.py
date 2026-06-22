from fastapi import APIRouter, Body, Depends, Path, Query, Request

from bisheng.api.v1.schemas import (
    KnowledgeSpaceConfig,
    LinsightConfig,
    SubscriptionConfig,
    UnifiedResponseModel,
    WorkstationConfig,
    resp_200,
)
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.workstation.domain.services import WorkStationService
from bisheng.workstation.domain.services.workstation_tags_service import WorkStationTagsService
from bisheng.workstation.api.dependencies import get_workstation_tags_service
from bisheng.database.models.tag import TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.common.errcode.tag import ReviewTagParamIsEmptyError

from ..dependencies import LoginUserDep

router = APIRouter(prefix='/tags', tags=['Tags'])


# 查询标签库中的标签
@router.get('/list', summary='List tag library', response_model=UnifiedResponseModel)
async def list_tag_library(
    request: Request,
    keyword: str = Query(default="", description="标签名称"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep
):
    tags_list = await tags_service.list_tag_library_by_name(keyword, login_user.tenant_id)
    return resp_200(tags_list)


# 新增标签库中的标签
@router.post('/create', summary='Create tag library', response_model=UnifiedResponseModel)
async def create_tag_library(
    request: Request,
    tag_name: str = Body(..., embed=True, description="标签名称"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep
):
    await tags_service.create_tag_library_by_name(tag_name, login_user.tenant_id)
    return resp_200(True)


# 更新标签库中的标签
@router.post('/update', summary='Update tag library', response_model=UnifiedResponseModel)
async def update_tag_library(
    request: Request,
    original_tag_name: str = Body(..., description="原始标签名称"),
    tag_name: str = Body(..., description="标签名称"),
    resource_type: TagResourceTypeEnum = Body(..., description="标签资源类型"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep
):
    await tags_service.update_tag_library_by_name(original_tag_name, tag_name, resource_type, login_user.tenant_id)
    return resp_200(True)



# 删除标签库中的标签
@router.post('/delete', summary='Delete tag library', response_model=UnifiedResponseModel)
async def delete_tag_library(
    request: Request,
    tag_name: str = Body(..., embed=True, description="标签名称"),
    resource_type: TagResourceTypeEnum = Body(..., description="标签资源类型"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep
):
    await tags_service.delete_tag_library_by_name(tag_name, resource_type, login_user.tenant_id)
    return resp_200(True)




# 通过/驳回-待审核标签
@router.post('/approve_or_reject', summary='Approve or reject review tag', response_model=UnifiedResponseModel)
async def approve_or_reject_review_tags(
    request: Request,
    data: ApproveOrRejectRequest = Body(..., description="操作参数"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep
):
    if not data or not data.tag_name or not data.status:
        raise ReviewTagParamIsEmptyError.http_exception()
    await tags_service.approve_or_reject_review_tag(data, login_user.tenant_id)
    return resp_200(True)


# 删除-待审核标签
@router.post("/delete_review", summary='Delete review tag', response_model=UnifiedResponseModel)
async def delete_review_tags(
    request: Request,
    tag_name: str = Body(..., embed=True, description="标签名称"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep
):
    await tags_service.delete_review_tag(tag_name, TagBusinessTypeEnum.KNOWLEDGE_SPACE, login_user.tenant_id)
    return resp_200(True)

# 分页查询-待审核标签
@router.post('/list_review', summary='List review tag', response_model=UnifiedResponseModel)
async def list_review_tags(
    request: Request,
    page: int = Body(default=1, description="页码"),
    page_size: int = Body(default=10, description="每页数量"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep
):
    result = await tags_service.list_review_tag_by_page(page, page_size, login_user.tenant_id)
    return resp_200(result)
