import json
import os
from typing import List, Literal
from loguru import logger
from fastapi import APIRouter, Depends, Body, Query, UploadFile, File, BackgroundTasks
from fastapi_jwt_auth import AuthJWT
from sse_starlette import EventSourceResponse
from starlette.responses import StreamingResponse
from starlette.websockets import WebSocket

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.api.services.linsight.message_stream_handle import MessageStreamHandle
from bisheng.api.services.linsight.sop_manage import SOPManageService
from bisheng.api.services.linsight.workbench_impl import LinsightWorkbenchImpl
from bisheng.api.services.user_service import get_login_user, UserPayload
from bisheng.api.v1.schema.inspiration_schema import SOPManagementSchema, SOPManagementUpdateSchema
from bisheng.api.v1.schema.linsight_schema import LinsightQuestionSubmitSchema, BatchDownloadFilesSchema
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200, resp_500
from bisheng.cache.redis import redis_client
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum, \
    LinsightSessionVersion
from bisheng.database.models.linsight_sop import LinsightSOPDao
from bisheng.linsight.state_message_manager import LinsightStateMessageManager
from bisheng.settings import settings

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
        logger.error(f"文件上传失败: {str(e)}")
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

    logger.info(f"用户 {login_user.user_id} 提交灵思问题: {submit_obj.question}")

    async def event_generator():
        """
        事件生成器，用于生成SSE事件
        """
        try:

            system_config = await settings.aget_all_config()

            # 获取Linsight_invitation_code
            linsight_invitation_code = system_config.get("linsight_invitation_code", False)

            if linsight_invitation_code:
                if await InviteCodeService.use_invite_code(user_id=login_user.user_id) is False:
                    yield {
                        "event": "error",
                        "data": "您的灵思使用次数已用完，请使用新的邀请码激活灵思功能。"
                    }
                    return

            message_session_model, linsight_session_version_model = await LinsightWorkbenchImpl.submit_user_question(
                submit_obj,
                login_user)

            response_data = {
                "message_session": message_session_model.model_dump(),
                "linsight_session_version": linsight_session_version_model.model_dump()
            }
        except Exception as e:
            yield {
                "event": "error",
                "data": "提交灵思用户问题失败: " + str(e)
            }
            return

        yield {
            "event": "linsight_workbench_submit",
            "data": json.dumps(response_data)
        }

        # 任务标题生成
        title_data = await LinsightWorkbenchImpl.task_title_generate(question=submit_obj.question,
                                                                     chat_id=message_session_model.chat_id,
                                                                     login_user=login_user)

        linsight_session_version_model.title = title_data.get("task_title")
        await LinsightSessionVersionDao.insert_one(linsight_session_version_model)

        yield {
            "event": "linsight_workbench_title_generate",
            "data": json.dumps(title_data)
        }

    return EventSourceResponse(event_generator())


# workbench 生成与重新规划灵思SOP
@router.post("/workbench/generate-sop", summary="生成与重新规划灵思SOP", response_model=UnifiedResponseModel)
async def generate_sop(
        linsight_session_version_id: str = Body(..., description="灵思会话版本ID"),
        previous_session_version_id: str = Body(None, description="上一个灵思会话版本ID"),
        feedback_content: str = Body(None, description="用户反馈内容"),
        reexecute: bool = Body(False, description="是否重新执行生成SOP"),
        login_user: UserPayload = Depends(get_login_user)) -> EventSourceResponse:
    """
    生成与重新规划灵思SOP
    :param previous_session_version_id:
    :param reexecute:
    :param linsight_session_version_id:
    :param feedback_content:
    :param login_user:
    :return:
    """

    logger.info(f"开始生成与重新规划灵思SOP，灵思会话版本ID: {linsight_session_version_id} ")

    async def event_generator():
        """
        事件生成器，用于生成SSE事件
        """
        # 生成SOP
        sop_generate = LinsightWorkbenchImpl.generate_sop(
            linsight_session_version_id=linsight_session_version_id,
            previous_session_version_id=previous_session_version_id,
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

    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=linsight_session_version_id)

    if not session_version_model:
        return resp_500(code=404, message="灵思会话版本不存在")
    if login_user.user_id != session_version_model.user_id:
        return resp_500(code=403, message="无权限修改该灵思SOP")

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

    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=linsight_session_version_id)
    if not session_version_model:
        return resp_500(code=404, message="灵思会话版本不存在")

    if login_user.user_id != session_version_model.user_id:
        return resp_500(code=403, message="无权限执行该灵思SOP")

    from bisheng.linsight.worker import RedisQueue
    try:
        queue = RedisQueue('queue', namespace="linsight", redis=redis_client)

        await queue.put(data=linsight_session_version_id)
    except Exception as e:
        logger.error(f"开始执行灵思任务失败: {str(e)}")
        await InviteCodeService.revoke_invite_code(user_id=login_user.user_id)
        return resp_500(code=500, message=str(e))

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

    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=session_version_id)
    if not session_version_model:
        return resp_500(code=404, message="灵思会话版本不存在")

    if login_user.user_id != session_version_model.user_id:
        return resp_500(code=403, message="无权限输入该灵思SOP")

    state_message_manager = LinsightStateMessageManager(session_version_id=session_version_id)

    await state_message_manager.set_user_input(task_id=linsight_execute_task_id, user_input=input_content)

    return resp_200(data=True, message="用户输入已提交")


# workbench 提交执行结果反馈
@router.post("/workbench/submit-feedback", summary="提交执行结果反馈", response_model=UnifiedResponseModel)
async def submit_feedback(
        background_tasks: BackgroundTasks,
        linsight_session_version_id: str = Body(..., description="灵思会话版本ID"),
        feedback: str = Body(None, description="用户反馈意见"),
        score: int = Body(None, ge=1, le=5, description="用户评分，1-5分"),
        is_reexecute: bool = Body(False, description="是否重新执行"),
        cancel_feedback: bool = Body(False, description="取消反馈"),
        login_user: UserPayload = Depends(get_login_user)) -> UnifiedResponseModel:
    """
    提交执行结果反馈
    :param background_tasks:
    :param cancel_feedback:
    :param linsight_session_version_id:
    :param feedback:
    :param score:
    :param is_reexecute:
    :param login_user:
    :return:
    """

    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=linsight_session_version_id)

    if not session_version_model:
        return resp_500(code=404, message="灵思会话版本不存在")

    if login_user.user_id != session_version_model.user_id:
        return resp_500(code=403, message="无权限提交该灵思的反馈")

    # score 不为空，且大于3，cancel_feedback 为 False feedback 为 None 或空字符串
    if score is not None and score > 3 and (feedback is None or feedback.strip() == "") and cancel_feedback is False:
        session_version_model.score = score
        session_version_model.execute_feedback = "评分大于3，未提供反馈"
        # 获取sop
        sop_model = await LinsightSOPDao.get_sop_by_session_id(session_version_model.session_id)
        if sop_model:
            sop_model.rating = score
            await LinsightSOPDao.create_sop(sop_model)
        # 更新会话版本
        await LinsightSessionVersionDao.insert_one(session_version_model)

        return resp_200(data=True, message="评分已提交，感谢您的反馈")

    # score 小于等于3，且没有取消反馈 feedback 不为空
    if score is not None and score <= 3 and (
            feedback is not None and feedback.strip() != "") and cancel_feedback is False and is_reexecute is False:
        # 反馈并重新生成SOP
        session_version_model.score = score
        session_version_model.execute_feedback = feedback
        await LinsightSessionVersionDao.insert_one(session_version_model)

        # 执行重新生成SOP任务
        background_tasks.add_task(
            LinsightWorkbenchImpl.feedback_regenerate_sop_task,
            session_version_model,
            feedback
        )

        return resp_200(data=True, message="反馈已提交，正在重新生成SOP")

    # score 小于等于3，且没有取消反馈 feedback 不为空 is_reexecute 为 True
    if score is not None and score <= 3 and (
            feedback is not None and feedback.strip() != "") and cancel_feedback is False and is_reexecute is True:
        # 重新执行灵思的逻辑
        session_version_model.score = score
        session_version_model.execute_feedback = feedback
        await LinsightSessionVersionDao.insert_one(session_version_model)

        # 灵思会话版本
        linsight_session_version_model = LinsightSessionVersion(
            session_id=session_version_model.session_id,
            user_id=login_user.user_id,
            question=session_version_model.question,
            tools=session_version_model.tools,
            org_knowledge_enabled=session_version_model.org_knowledge_enabled,
            personal_knowledge_enabled=session_version_model.personal_knowledge_enabled,
            files=session_version_model.files,
            title=session_version_model.title
        )
        linsight_session_version_model = await LinsightSessionVersionDao.insert_one(linsight_session_version_model)

        return resp_200(data=linsight_session_version_model.model_dump(),
                        message="重新执行灵思任务。")
    # 取消反馈
    if cancel_feedback:
        # 取消反馈的逻辑
        session_version_model.execute_feedback = "用户取消了反馈"
        await LinsightSessionVersionDao.insert_one(session_version_model)

        return resp_200(data=True, message="反馈已取消")
    return resp_500(code=400, message="参数错误，请检查输入的参数是否正确")


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
    if login_user.user_id != session_version_model.user_id:
        return resp_500(code=403, message="无权限终止该灵思执行")

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


# 批量下载任务文件
@router.post("/workbench/batch-download-files", summary="批量下载任务文件")
async def batch_download_files(
        zip_name: str = Body(..., description="压缩包名称"),
        file_info_list: List[BatchDownloadFilesSchema] = Body(..., description="文件信息列表"),
        login_user: UserPayload = Depends(get_login_user)):
    """
    批量下载任务文件
    :param zip_name:
    :param file_info_list:
    :param login_user:
    :return:
    """

    try:
        # 调用实现类处理批量下载
        zip_bytes = await LinsightWorkbenchImpl.batch_download_files(file_info_list)

        zip_name = zip_name if os.path.splitext(zip_name)[-1] == ".zip" else f"{zip_name}.zip"

        return StreamingResponse(
            iter([zip_bytes]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={zip_name}"
            }
        )
    except Exception as e:
        logger.error(f"批量下载文件失败: {str(e)}")
        return resp_500(code=500, message=str(e))


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
    return await SOPManageService.update_sop(sop_obj)


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
