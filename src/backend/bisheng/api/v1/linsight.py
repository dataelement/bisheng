from typing import List

from fastapi import APIRouter, Depends, Body, Query

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.linsight.sop_manage import SOPManageService
from bisheng.api.services.user_service import get_login_user, UserPayload
from bisheng.api.v1.schema.inspiration_schema import SOPManagementSchema, SOPManagementUpdateSchema
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.linsight_sop import LinsightSOPDao

router = APIRouter(prefix="/linsight", tags=["灵思"])


@router.post("/sop/add", summary="添加灵思SOP", response_model=UnifiedResponseModel)
async def add_sop(
        sop_obj: SOPManagementSchema = Body(..., description="SOP对象"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    添加灵思SOP
    :param sop_obj:
    :param login_user:
    :return:
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()

    return await SOPManageService.add_sop(sop_obj, login_user)


@router.post("/sop/update", summary="更新灵思SOP", response_model=UnifiedResponseModel)
async def update_sop(
        sop_obj: SOPManagementUpdateSchema = Body(..., description="SOP对象"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    更新灵思SOP
    :param sop_obj:
    :param login_user:
    :return:
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()
    return await SOPManageService.update_sop(sop_obj, login_user)


@router.get("/sop/list", summary="获取灵思SOP列表", response_model=UnifiedResponseModel)
async def get_sop_list(
        keywords: str = Query(None, description="搜索关键词"),
        page: int = Query(1, ge=1, description="页码"),
        page_size: int = Query(10, ge=1, le=100, description="每页数量"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    获取灵思SOP列表
    :param keywords:
    :param page:
    :param page_size:
    :param login_user:
    :return:
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()

    sop_pages = await LinsightSOPDao.get_sop_page(keywords=keywords, page=page, page_size=page_size)
    return resp_200(data=sop_pages)


@router.delete("/sop/remove", summary="删除灵思SOP", response_model=UnifiedResponseModel)
async def remove_sop(
        sop_ids: List[int] = Body(..., description="SOP唯一ID列表", embed=True),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    删除灵思SOP
    :param sop_ids:
    :param login_user:
    :return:
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()

    return await SOPManageService.remove_sop(sop_ids, login_user)
