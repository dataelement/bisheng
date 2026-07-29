"""Dictionary API endpoints - 系统字典接口"""

from fastapi import APIRouter, Depends, Path, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import PageData, UnifiedResponseModel, resp_200
from bisheng.dictionary.api.dependencies import get_dictionary_service
from bisheng.dictionary.domain.schemas.dictionary_schema import (
    DictionaryCreateRequest,
    DictionaryResponse,
    DictionaryTypeResponse,
    DictionaryUpdateRequest,
)
from bisheng.dictionary.domain.services.dictionary_service import DictionaryService

router = APIRouter(prefix="/dictoption", tags=["Dictionary"])


@router.post("/create", response_model=UnifiedResponseModel[DictionaryResponse])
async def create_dictionary(
    request: DictionaryCreateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: DictionaryService = Depends(get_dictionary_service),
):
    """新增字典条目(管理员)"""
    result = await service.create(request, user)
    return resp_200(data=result.model_dump())


@router.put("/update/{dictionary_id}", response_model=UnifiedResponseModel[DictionaryResponse])
async def update_dictionary(
    dictionary_id: int,
    request: DictionaryUpdateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: DictionaryService = Depends(get_dictionary_service),
):
    """修改字典条目(管理员)"""
    result = await service.update(dictionary_id, request, user)
    return resp_200(data=result.model_dump())


@router.delete("/delete/{dictionary_id}", response_model=UnifiedResponseModel[bool])
async def delete_dictionary(
    dictionary_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: DictionaryService = Depends(get_dictionary_service),
):
    """删除字典条目(管理员)"""
    await service.delete(dictionary_id, user)
    return resp_200(data=True)


@router.get("/types", response_model=UnifiedResponseModel[list[DictionaryTypeResponse]])
async def list_dictionaries_by_type(
    service: DictionaryService = Depends(get_dictionary_service),
):
    """查询所有字典类型"""
    result = await service.list_by_type()
    return resp_200(data=[item.model_dump() for item in result])


@router.get("/type/{dict_type}", response_model=UnifiedResponseModel[list[DictionaryResponse]])
async def get_dictionary_by_type(
    dict_type: str = Path(..., description="字典类型"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=500, description="每页数量"),
    service: DictionaryService = Depends(get_dictionary_service),
):
    """根据 dict_type 查询启用的字典条目列表"""
    result = await service.get_list_by_type(dict_type, page, page_size)
    return resp_200(data=[item.model_dump() for item in result])


@router.get("/query/{dictionary_id}", response_model=UnifiedResponseModel[DictionaryResponse])
async def get_dictionary_by_id(
    dictionary_id: int,
    service: DictionaryService = Depends(get_dictionary_service),
):
    """根据 ID 查询字典条目"""
    result = await service.get_by_id(dictionary_id)
    return resp_200(data=result.model_dump())


@router.get("/list", response_model=UnifiedResponseModel[PageData[DictionaryResponse]])
async def list_dictionaries(
    type: str | None = Query(None, description="字典类型筛选"),
    keyword: str | None = Query(None, description="关键词模糊匹配 type/dict_key/dict_value"),
    sort_order: bool | None = Query(None, description="排序顺序, True 升序, False 降序"),
    enabled: bool | None = Query(None, description="是否启用筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=500, description="每页数量"),
    service: DictionaryService = Depends(get_dictionary_service),
):
    """分页查询字典条目"""
    result = await service.list_page(
        dict_type=type,
        keyword=keyword,
        page=page,
        page_size=page_size,
        sort_order=sort_order,
        enabled=enabled,
    )
    return resp_200(data=result.model_dump())
