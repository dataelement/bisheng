import json
from typing import List, Literal, Any, Coroutine
from uuid import UUID

from fastapi import APIRouter, Depends, Body, Query, UploadFile, File
from fastapi_jwt_auth import AuthJWT
from sse_starlette import EventSourceResponse
from starlette.websockets import WebSocket

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.linsight.message_stream_handle import MessageStreamHandle
from bisheng.api.services.linsight.sop_manage import SOPManageService
from bisheng.api.services.linsight.workbench_impl import LinsightWorkbenchImpl
from bisheng.api.services.user_service import get_login_user, UserPayload
from bisheng.api.v1.schema.inspiration_schema import SOPManagementSchema, SOPManagementUpdateSchema
from bisheng.api.v1.schema.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200, resp_500
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum
from bisheng.database.models.linsight_sop import LinsightSOPDao
from bisheng.worker.linsight.state_message_manager import LinsightStateMessageManager

router = APIRouter(prefix="/linsight", tags=["灵思"])


# 灵思上传文件
@router.post("/workbench/upload-file", summary="灵思上传文件", response_model=UnifiedResponseModel)
async def upload_file(file: UploadFile = File(...),
                      login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    灵思上传文件
    :param file: 上传的文件
    :param login_user: 登录用户信息
    :return: 上传结果
    """

    try:
        # 调用实现类处理文件上传
        upload_result = await LinsightWorkbenchImpl.upload_file(file)

        # 解析
        parse_result = await LinsightWorkbenchImpl.parse_file(upload_result)

        result = {
            "file_id": parse_result.get("file_id"),
            "file_name": parse_result.get("original_filename"),
            "parsing_status": "completed"
        }
    except Exception as e:
        return resp_500(code=500, message=str(e))

    # 返回上传结果
    return resp_200(data=result, message="文件上传成功")


# 提交灵思用户问题请求
@router.post("/workbench/submit", summary="提交灵思用户问题请求")
async def submit_linsight_workbench(
        submit_obj: LinsightQuestionSubmitSchema = Body(..., description="灵思用户问题提交对象"),
        login_user: UserPayload = Depends(get_login_user)) -> EventSourceResponse:
    """
    提交灵思用户问题请求
    :param submit_obj:
    :param login_user:
    :return:
    """
    message_session_model, linsight_session_version_model = await LinsightWorkbenchImpl.submit_user_question(submit_obj,
                                                                                                             login_user)

    async def event_generator():
        """
        事件生成器，用于生成SSE事件
        """
        response_data = {
            "message_session": message_session_model.model_dump(),
            "linsight_session_version": linsight_session_version_model.model_dump()
        }

        yield {
            "event": "linsight_workbench_submit",
            "data": json.dumps(response_data)
        }

        # 任务标题生成
        title_data = await LinsightWorkbenchImpl.task_title_generate(question=submit_obj.question,
                                                                     chat_id=message_session_model.chat_id,
                                                                     login_user=login_user)

        yield {
            "event": "linsight_workbench_title_generate",
            "data": json.dumps(title_data)
        }

    return EventSourceResponse(event_generator())


# workbench 生成与重新规划灵思SOP
@router.post("/workbench/generate-sop", summary="生成与重新规划灵思SOP", response_model=UnifiedResponseModel)
async def generate_sop(
        linsight_session_version_id: str = Body(..., description="灵思会话版本ID"),
        feedback_content: str = Body(None, description="用户反馈内容"),
        reexecute: bool = Body(False, description="是否重新执行生成SOP"),
        login_user: UserPayload = Depends(get_login_user)) -> EventSourceResponse:
    """
    生成与重新规划灵思SOP
    :param reexecute:
    :param linsight_session_version_id:
    :param feedback_content:
    :param login_user:
    :return:
    """

    async def event_generator():
        """
        事件生成器，用于生成SSE事件
        """
        # 生成SOP
        sop_generate = LinsightWorkbenchImpl.generate_sop(
            linsight_session_version_id=linsight_session_version_id,
            feedback_content=feedback_content,
            reexecute=reexecute,
            login_user=login_user
        )

        async for event in sop_generate:
            yield event

        # 结束
        yield {
            "event": "sop_generate_complete",
            "data": json.dumps({"message": "SOP生成与重新规划完成"})
        }

    return EventSourceResponse(event_generator())


# workbench 修改sop
@router.post("/workbench/sop-modify", summary="修改灵思SOP", response_model=UnifiedResponseModel)
async def modify_sop(
        sop_content: str = Body(..., description="SOP内容"),
        linsight_session_version_id: str = Body(..., description="灵思会话版本ID"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    修改灵思SOP
    :param sop_content:
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """

    modify_res = await LinsightWorkbenchImpl.modify_sop(linsight_session_version_id=linsight_session_version_id,
                                                        sop_content=sop_content)
    return resp_200(modify_res)


# workbench 开始执行
@router.post("/workbench/start-execute", summary="开始执行灵思", response_model=UnifiedResponseModel)
async def start_execute_sop(
        linsight_session_version_id: str = Body(..., description="灵思会话版本ID", embed=True),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    开始执行灵思SOP
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """
    from bisheng.worker.linsight.task_exec import LinsightWorkflowTask
    LinsightWorkflowTask.delay(linsight_session_version_id=linsight_session_version_id)

    return resp_200(data=True, message="灵思执行任务已开始，执行结果将通过消息流返回")


# workbench 用户输入
@router.post("/workbench/user-input", summary="用户输入灵思", response_model=UnifiedResponseModel)
async def user_input(
        session_version_id: str = Body(..., description="灵思会话版本ID"),
        linsight_execute_task_id: str = Body(..., description="灵思执行任务ID"),
        input_content: str = Body(..., description="用户输入内容"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    用户输入
    :param session_version_id:
    :param input_content:
    :param linsight_execute_task_id:
    :param login_user:
    :return:
    """
    state_message_manager = LinsightStateMessageManager(session_version_id=session_version_id)

    await state_message_manager.set_user_input(task_id=linsight_execute_task_id, user_input=input_content)

    return resp_200(data=True, message="用户输入已提交")


# workbench 提交执行结果反馈
@router.post("/workbench/submit-feedback", summary="提交执行结果反馈", response_model=UnifiedResponseModel)
async def submit_feedback(
        linsight_session_version_id: str = Body(..., description="灵思会话版本ID"),
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
        linsight_session_version_id: str = Body(..., description="灵思会话版本ID", embed=True),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    终止执行灵思
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """
    # 现终止执行灵思的逻辑
    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=linsight_session_version_id)

    if not session_version_model:
        return resp_500(code=404, message="灵思会话版本不存在")

    if session_version_model.status == SessionVersionStatusEnum.COMPLETED:
        return resp_500(code=400, message="灵思会话版本已完成，无法终止执行")

    if session_version_model.status == SessionVersionStatusEnum.TERMINATED:
        return resp_500(code=400, message="灵思会话版本已终止执行")

    # 更新状态为终止
    session_version_model.status = SessionVersionStatusEnum.TERMINATED

    state_message_manager = LinsightStateMessageManager(session_version_id=linsight_session_version_id)

    await state_message_manager.set_session_version_info(session_version_model)

    return resp_200(data=True, message="灵思执行已终止")


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

    linsight_session_version_models = await LinsightWorkbenchImpl.get_linsight_session_version_list(session_id)
    return resp_200([model.model_dump() for model in linsight_session_version_models])


# 获取执行任务详情
@router.get("/workbench/execute-task-detail", summary="获取执行任务详情", response_model=UnifiedResponseModel)
async def get_execute_task_detail(
        session_version_id: str = Query(..., description="灵思会话版本ID"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    获取执行任务详情
    :param session_version_id:
    :param login_user:
    :return:
    """

    execute_task_models = await LinsightWorkbenchImpl.get_execute_task_detail(session_version_id)
    return resp_200(execute_task_models)


# 建立灵思任务消息流 websocket
@router.websocket("/workbench/task-message-stream", name="task_message_stream")
async def task_message_stream(
        websocket: WebSocket,
        session_version_id: str = Query(..., description="灵思会话版本ID"),
        Authorize: AuthJWT = Depends()):
    """
    建立灵思任务消息流 websocket
    :param Authorize:
    :param websocket:
    :param session_version_id:
    :return:
    """

    try:
        Authorize.jwt_required(auth_from='websocket', websocket=websocket)
        payload = Authorize.get_jwt_subject()
        payload = json.loads(payload)
        login_user = UserPayload(**payload)

        message_handler = MessageStreamHandle(websocket=websocket, session_version_id=session_version_id)

        await message_handler.connect()

    except Exception as e:
        await websocket.close(code=1000, reason=str(e))
        return


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

    return await SOPManageService.add_sop(sop_obj, user_id=login_user.user_id)


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
