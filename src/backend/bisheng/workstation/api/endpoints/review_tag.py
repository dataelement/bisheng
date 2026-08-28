from fastapi import APIRouter, Body, Depends, Query, Request

from bisheng.api.v1.schemas import (
    UnifiedResponseModel,
    resp_200,
)
from bisheng.common.errcode.tag import ReviewTagParamIsEmptyError
from bisheng.database.models.tag import TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.workstation.api.dependencies import get_workstation_tags_service
from bisheng.workstation.domain.schemas.review_tags_schema import (
    ApproveOrRejectRequest,
    ReviewTagSimilarBatchCheckRequest,
    ReviewTagSimilarCheckRequest,
)
from bisheng.workstation.domain.schemas.tag_console_schema import TagConsoleBlacklistPreviewReq
from bisheng.workstation.domain.services.workstation_tags_service import WorkStationTagsService

from ..dependencies import LoginUserDep

router = APIRouter(prefix="/tags", tags=["Tags"])


# 查询标签库中的标签 -- 废弃
@router.get("/list", summary="List tag library", response_model=UnifiedResponseModel)
async def list_tag_library(
    request: Request,
    keyword: str = Query(default="", description="标签名称"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    tags_list = await tags_service.list_tag_library_by_name(keyword, login_user.tenant_id)
    return resp_200(tags_list)


@router.post("/list_tags", summary="List tags", response_model=UnifiedResponseModel)
async def list_tags(
    request: Request,
    page: int = Body(default=1, description="页码"),
    page_size: int = Body(default=10, description="每页数量"),
    keyword: str = Body(default="", description="标签名称"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    tags_list = await tags_service.list_all_tags_library_by_page(keyword, page, page_size, login_user.tenant_id)
    return resp_200(tags_list)


# 新增标签库中的标签
@router.post("/create", summary="Create tag library", response_model=UnifiedResponseModel)
async def create_tag_library(
    request: Request,
    tag_name: str = Body(..., embed=True, description="标签名称"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    await tags_service.create_tag_library_by_name(tag_name, login_user.tenant_id)
    return resp_200(True)


# 更新标签库中的标签
@router.post("/update", summary="Update tag library", response_model=UnifiedResponseModel)
async def update_tag_library(
    request: Request,
    original_tag_name: str = Body(..., description="原始标签名称"),
    tag_name: str = Body(..., description="标签名称"),
    resource_type: TagResourceTypeEnum = Body(..., description="标签资源类型"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    await tags_service.update_tag_library_by_name(original_tag_name, tag_name, resource_type, login_user.tenant_id)
    return resp_200(True)


# 删除标签库中的标签
@router.post("/delete", summary="Delete tag library", response_model=UnifiedResponseModel)
async def delete_tag_library(
    request: Request,
    tag_name: str = Body(..., embed=True, description="标签名称"),
    resource_type: TagResourceTypeEnum = Body(..., description="标签资源类型"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    await tags_service.delete_tag_library_by_name(tag_name, resource_type, login_user.tenant_id)
    return resp_200(True)


# 通过/驳回-待审核标签
@router.post("/approve_or_reject", summary="Approve or reject review tag", response_model=UnifiedResponseModel)
async def approve_or_reject_review_tags(
    request: Request,
    data: ApproveOrRejectRequest = Body(..., description="操作参数"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    if not data or not data.tag_name or not data.status:
        raise ReviewTagParamIsEmptyError.http_exception()
    existed_tag_list = await tags_service.approve_or_reject_review_tag(data, login_user.tenant_id)
    return resp_200(existed_tag_list)


@router.post("/blacklist/preview", summary="Preview tag blacklist insert capacity", response_model=UnifiedResponseModel)
async def preview_tag_blacklist(
    data: TagConsoleBlacklistPreviewReq = Body(...),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
):
    return resp_200(await tags_service.preview_tag_blacklist(data.names))


# 删除-待审核标签
@router.post("/delete_review", summary="Delete review tag", response_model=UnifiedResponseModel)
async def delete_review_tags(
    request: Request,
    tag_name: str = Body(..., embed=True, description="标签名称"),
    resource_type: TagResourceTypeEnum = Body(..., description="标签资源类型"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    await tags_service.delete_review_tag(
        tag_name, TagBusinessTypeEnum.KNOWLEDGE_SPACE, resource_type, login_user.tenant_id
    )
    return resp_200(True)


# 分页查询-待审核标签
@router.post("/list_review", summary="List review tag", response_model=UnifiedResponseModel)
async def list_review_tags(
    request: Request,
    page: int = Body(default=1, description="页码"),
    page_size: int = Body(default=10, description="每页数量"),
    keyword: str = Body(default="", description="标签名称关键词"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    result = await tags_service.list_review_tag_by_page(page, page_size, login_user.tenant_id, keyword)
    return resp_200(result)


@router.post("/review_similar_check", summary="Check similar tags in target library", response_model=UnifiedResponseModel)
async def review_similar_check(
    request: Request,
    data: ReviewTagSimilarCheckRequest = Body(..., description="Similar tag check params"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    if not data or not data.tag_name or not data.tag_library_id:
        raise ReviewTagParamIsEmptyError.http_exception()
    result = await tags_service.check_review_tag_similar_in_library(
        tag_name=data.tag_name,
        tag_library_id=int(data.tag_library_id),
        tenant_id=login_user.tenant_id,
    )
    return resp_200(result)


@router.post(
    "/review_similar_check_batch",
    summary="Batch check similar tags in target library",
    response_model=UnifiedResponseModel,
)
async def review_similar_check_batch(
    request: Request,
    data: ReviewTagSimilarBatchCheckRequest = Body(..., description="Batch similar tag check params"),
    tags_service: WorkStationTagsService = Depends(get_workstation_tags_service),
    login_user=LoginUserDep,
):
    if not data or not data.tag_names or not data.tag_library_id:
        raise ReviewTagParamIsEmptyError.http_exception()
    result = await tags_service.check_review_tag_similar_in_library_batch(
        tag_names=data.tag_names,
        tag_library_id=int(data.tag_library_id),
        tenant_id=login_user.tenant_id,
    )
    return resp_200(result)
