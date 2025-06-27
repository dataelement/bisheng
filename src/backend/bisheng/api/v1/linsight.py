from typing import List, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Body, Query

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.linsight.sop_manage import SOPManageService
from bisheng.api.services.user_service import get_login_user, UserPayload
from bisheng.api.v1.schema.inspiration_schema import SOPManagementSchema, SOPManagementUpdateSchema
from bisheng.api.v1.schema.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.linsight_sop import LinsightSOPDao

router = APIRouter(prefix="/linsight", tags=["灵思"])


# 提交灵思用户问题请求
@router.post("/workbench/submit", summary="提交灵思用户问题请求", response_model=UnifiedResponseModel)
async def submit_linsight_workbench(
        submit_obj: LinsightQuestionSubmitSchema = Body(..., description="灵思用户问题提交对象"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    提交灵思用户问题请求
    :param submit_obj:
    :param login_user:
    :return:
    """
    # TODO: 实现提交灵思用户问题请求的逻辑
    pass


# workbench 修改sop
@router.post("/workbench/sop-modify", summary="修改灵思SOP", response_model=UnifiedResponseModel)
async def modify_sop(
        sop_content: str = Body(..., description="SOP内容"),
        linsight_session_version_id: UUID = Body(..., description="灵思会话版本ID"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    修改灵思SOP
    :param sop_content:
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """
    # TODO: 实现修改SOP的逻辑
    pass


# workbench 重新规划sop
@router.post("/workbench/sop-replan", summary="重新规划灵思SOP", response_model=UnifiedResponseModel)
async def replan_sop(
        linsight_session_version_id: UUID = Body(..., description="灵思会话版本ID"),
        feedback: str = Body(..., description="用户反馈意见"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    重新规划灵思SOP
    :param feedback:
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """
    # TODO: 实现重新规划SOP的逻辑
    pass


# workbench 开始执行
@router.post("/workbench/start-execute", summary="开始执行灵思SOP", response_model=UnifiedResponseModel)
async def start_execute_sop(
        linsight_session_version_id: UUID = Body(..., description="灵思会话版本ID"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    开始执行灵思SOP
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """
    # TODO: 实现开始执行SOP的逻辑
    pass


# workbench 用户输入
@router.post("/workbench/user-input", summary="用户输入灵思SOP", response_model=UnifiedResponseModel)
async def user_input(
        linsight_execute_task_id: UUID = Body(..., description="灵思执行任务ID"),
        input_content: str = Body(..., description="用户输入内容"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    用户输入
    :param input_content:
    :param linsight_execute_task_id:
    :param login_user:
    :return:
    """
    # TODO: 实现用户输入的逻辑
    pass


# workbench 提交执行结果反馈
@router.post("/workbench/submit-feedback", summary="提交执行结果反馈", response_model=UnifiedResponseModel)
async def submit_feedback(
        linsight_session_version_id: UUID = Body(..., description="灵思会话版本ID"),
        feedback: str = Body(None, description="用户反馈意见"),
        score: int = Body(None, ge=1, le=5, description="用户评分，1-5分"),
        is_reexecute: bool = Body(False, description="是否重新执行"),
        cancel_feedback: bool = Body(False, description="取消反馈"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    提交执行结果反馈
    :param cancel_feedback:
    :param linsight_session_version_id:
    :param feedback:
    :param score:
    :param is_reexecute:
    :param login_user:
    :return:
    """
    # TODO: 实现提交执行结果反馈的逻辑，如果有提交反馈信息，则根据反馈信息重新生成SOP并保存


# workbench 终止执行
@router.post("/workbench/terminate-execute", summary="终止执行灵思", response_model=UnifiedResponseModel)
async def terminate_execute(
        linsight_session_version_id: UUID = Body(..., description="灵思会话版本ID"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    终止执行灵思
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """
    # TODO: 实现终止执行灵思的逻辑
    pass


# 获取当前会话所有灵思信息
@router.get("/workbench/session-version-list", summary="获取当前会话所有灵思信息", response_model=UnifiedResponseModel)
async def get_linsight_session_version_list(
        session_id: str = Query(..., description="会话ID"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    获取当前会话所有灵思信息
    :param session_id:
    :param login_user:
    :return:
    """
    # TODO: 实现获取当前会话所有灵思信息的逻辑
    pass


@router.post("/sop/add", summary="添加灵思SOP", response_model=UnifiedResponseModel)
async def add_sop(
        sop_obj: SOPManagementSchema = Body(..., description="SOP对象"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    添加灵思SOP
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
        sort: Literal["asc", "desc"] = Query("desc", description="排序方式，asc或desc"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    获取灵思SOP列表
    :return:
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()

    sop_pages = await LinsightSOPDao.get_sop_page(keywords=keywords, page=page, page_size=page_size, sort=sort)
    return resp_200(data=sop_pages)


@router.delete("/sop/remove", summary="删除灵思SOP", response_model=UnifiedResponseModel)
async def remove_sop(
        sop_ids: List[int] = Body(..., description="SOP唯一ID列表", embed=True),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    删除灵思SOP
    :return:
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()

    return await SOPManageService.remove_sop(sop_ids, login_user)
