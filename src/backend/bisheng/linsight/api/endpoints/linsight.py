import asyncio
import json
import os
import time
from datetime import datetime
from typing import List, Literal, Optional, Union
from urllib import parse

from fastapi import APIRouter, Depends, Body, Query, UploadFile, File, BackgroundTasks, Request, Form
from loguru import logger
from pydantic import BaseModel, ValidationError
from sse_starlette import EventSourceResponse
from starlette.responses import StreamingResponse
from starlette.websockets import WebSocket

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.linsight.domain.services.message_stream_handle import MessageStreamHandle
from bisheng.linsight.domain.services.sop_manage import SOPManageService
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.api.v1.schema.base_schema import PageList
from bisheng.linsight.domain.schemas.inspiration_schema import SOPManagementSchema, SOPManagementUpdateSchema
from bisheng.linsight.domain.schemas.linsight_schema import LinsightQuestionSubmitSchema, DownloadFilesSchema, \
    SubmitFileSchema, LinsightToolSchema, ToolChildrenSchema
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError, NotFoundError
from bisheng.common.errcode.linsight import LinsightQuestionError, LinsightUseUpError, LinsightModifySopError, \
    LinsightStartTaskError, LinsightSessionVersionRunningError, LinsightQueueStatusError, FileUploadError, \
    SopShowcaseError
from bisheng.common.errcode.server import InvalidOperationError, ResourceDownloadError
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationAliveEventData, ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum, \
    LinsightSessionVersion
from bisheng.linsight.domain.models.linsight_sop import LinsightSOPDao, LinsightSOPRecord
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum, KnowledgeDao
from bisheng.linsight.domain.services.state_message_manager import LinsightStateMessageManager, MessageData, MessageEventType
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.utils import util

router = APIRouter()


# Inspiration Upload File
@router.post("/workbench/upload-file", summary="Inspiration Upload File", response_model=UnifiedResponseModel)
async def upload_file(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    Inspiration Upload File
    :param background_tasks:
    :param file: files uploaded
    :param login_user: Logged in user information
    :return: Upload results
    """

    try:
        # Call the implementation class to process file uploads
        upload_result = await LinsightWorkbenchImpl.upload_file(file)

        background_tasks.add_task(LinsightWorkbenchImpl.parse_file, upload_result, login_user.user_id)

        result = {
            "file_id": upload_result.get("file_id"),
            "file_name": upload_result.get("original_filename"),
            "parsing_status": upload_result.get("parsing_status"),
        }
    except Exception as e:
        logger.error(f"Upload Failed: {str(e)}")
        return FileUploadError.return_resp()

    # Back to upload results
    return resp_200(data=result, message="Key file uploaded successfully! and start parsing. Please check the resolution status later.")


# Get file resolution status
@router.post("/workbench/file-parsing-status", summary="Get file resolution status", response_model=UnifiedResponseModel)
async def get_file_parsing_status(
        file_ids: List[str] = Body(..., description="Doc.IDVertical", embed=True),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    Get file resolution status
    :param file_ids:
    :param login_user:
    :return:
    """

    # Call the implementation class to get the file parsing state
    key_prefix = LinsightWorkbenchImpl.FILE_INFO_REDIS_KEY_PREFIX

    file_ids = [f"{key_prefix}{file_id}" for file_id in file_ids]

    redis_client = await get_redis_client()

    # Use Redis right of privacy amget Method Get file parsing status in batches
    parsing_status = await redis_client.amget(file_ids)

    return resp_200(data=parsing_status, message="File parsing status retrieved successfully")


@router.post("/workbench/file_download", summary="Inspiration File Download", response_model=UnifiedResponseModel)
async def linsight_file_download(
        file_url: str = Body(..., embed=True),
        session_version_id: str = Body(..., embed=True),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        share_link: Union['ShareLink', None] = Depends(header_share_token_parser)) -> UnifiedResponseModel:
    session_version_model = await LinsightSessionVersionDao.get_by_id(session_version_id)
    if not session_version_model:
        raise NotFoundError()

    # judge permission
    if session_version_model.user_id != login_user.user_id and not login_user.is_admin():
        # Access by sharing a link
        if (share_link is None or
                share_link.meta_data is None or
                share_link.meta_data.get("versionId") != session_version_id):
            raise UnAuthorizedError()

    minio_client = await get_minio_storage()
    file_url = file_url.lstrip("/")
    if file_url.startswith(minio_client.bucket):
        file_url = file_url[len(minio_client.bucket) + 1:]
    file_share_url = await minio_client.get_share_link(file_url)
    return resp_200(data={
        "file_path": file_share_url
    })


# Submit an Idea User Issue Request
@router.post("/workbench/submit", summary="Submit an Idea User Issue Request")
async def submit_linsight_workbench(
        submit_obj: LinsightQuestionSubmitSchema = Body(..., description="Idea User Issue Submitter"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> EventSourceResponse:
    """
    Submit an Idea User Issue Request
    :param submit_obj:
    :param login_user:
    :return:
    """

    logger.info(f"Users {login_user.user_id} Submit an Idea Question: {submit_obj.question}")

    async def event_generator():
        """
        Event generator for generatingSSE events
        """
        try:

            system_config = await settings.aget_all_config()

            # DapatkanLinsight_invitation_code
            linsight_invitation_code = system_config.get("linsight_invitation_code", False)

            if linsight_invitation_code:
                if await InviteCodeService.use_invite_code(user_id=login_user.user_id) is False:
                    yield LinsightUseUpError().to_sse_event_instance()
                    return

            message_session_model, linsight_session_version_model = await LinsightWorkbenchImpl.submit_user_question(
                submit_obj,
                login_user)

            response_data = {
                "message_session": message_session_model.model_dump(),
                "linsight_session_version": linsight_session_version_model.model_dump()
            }
        except Exception as e:
            yield LinsightQuestionError(exception=e).to_sse_event_instance()
            return

        yield {
            "event": "linsight_workbench_submit",
            "data": json.dumps(response_data)
        }

        # Task Title Generation
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


# workbench Generate and Reimagine IdeasSOP
@router.post("/workbench/generate-sop", summary="Generate and Reimagine IdeasSOP", response_model=UnifiedResponseModel)
async def generate_sop(
        request: Request,
        linsight_session_version_id: str = Body(..., description="Inspiration Conversation VersionID"),
        previous_session_version_id: str = Body(None, description="Previous Invisible Conversation VersionID"),
        feedback_content: str = Body(None, description="User feedback content"),
        reexecute: bool = Body(False, description="Whether to rerun the buildSOP"),
        sop_id: int = Body(None, description="Featured Cases'ID"),
        example_session_version_id: str = Body(default=None, description="Reference Cases'linsight_version_id"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> EventSourceResponse:
    """
    Generate and Reimagine IdeasSOP
    :param previous_session_version_id:
    :param reexecute:
    :param linsight_session_version_id:
    :param feedback_content:
    :param sop_id:
    :param login_user:
    :return:
    """

    logger.info(f"Start Generating and Redesigning IdeasSOP, Inscription Conversation VersionID: {linsight_session_version_id} ")
    start_time = time.time()

    session_version = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id)

    # Get a list of knowledge bases with permissions
    if not session_version:
        raise NotFoundError.http_exception()

    example_sop = None
    if sop_id:
        sop_db = await SOPManageService.get_sop_by_id(sop_id)
        example_sop = sop_db.content if sop_db else None
    elif example_session_version_id:
        example_session_version = await LinsightSessionVersionDao.get_by_id(example_session_version_id)
        example_sop = example_session_version.sop if example_session_version else None
    res = []
    linsight_conf = settings.get_linsight_conf()
    if session_version.org_knowledge_enabled and linsight_conf.max_knowledge_num > 0:
        res, _ = await KnowledgeService.get_knowledge(request, login_user, KnowledgeTypeEnum.NORMAL, None, 1,
                                                      linsight_conf.max_knowledge_num)
    if session_version.personal_knowledge_enabled:
        knowledge = await KnowledgeDao.aget_user_knowledge(login_user.user_id, None,
                                                           KnowledgeTypeEnum.PRIVATE)
        if knowledge:
            res.extend(knowledge)

    async def event_generator():
        """
        Event generator for generatingSSE events
        """
        # BuatSOP
        sop_generate = LinsightWorkbenchImpl.generate_sop(
            linsight_session_version_id=linsight_session_version_id,
            previous_session_version_id=previous_session_version_id,
            feedback_content=feedback_content,
            reexecute=reexecute,
            login_user=login_user,
            knowledge_list=res,
            example_sop=example_sop
        )

        async for event in sop_generate:
            yield event

        # End
        yield {
            "event": "sop_generate_complete",
            "data": json.dumps({"message": "SOPGeneration and re-planning complete"})
        }

    try:
        return EventSourceResponse(event_generator())
    finally:
        end_time = time.time()
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationAliveEventData(
                                              app_id=ApplicationTypeEnum.LINSIGHT.value,
                                              app_name=ApplicationTypeEnum.LINSIGHT.value,
                                              app_type=ApplicationTypeEnum.LINSIGHT,
                                              chat_id=session_version.session_id,

                                              start_time=int(start_time),
                                              end_time=int(end_time)
                                          ))
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationProcessEventData(
                                              app_id=ApplicationTypeEnum.LINSIGHT.value,
                                              app_name=ApplicationTypeEnum.LINSIGHT.value,
                                              app_type=ApplicationTypeEnum.LINSIGHT,
                                              chat_id=session_version.session_id,

                                              start_time=int(start_time),
                                              end_time=int(end_time),
                                              process_time=int((end_time - start_time) * 1000)
                                          ))


# workbench Changesop
@router.post("/workbench/sop-modify", summary="Modify InspirationSOP", response_model=UnifiedResponseModel)
async def modify_sop(
        sop_content: str = Body(..., description="SOPContents"),
        linsight_session_version_id: str = Body(..., description="Inspiration Conversation VersionID"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    Modify InspirationSOP
    :param sop_content:
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """

    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=linsight_session_version_id)

    if not session_version_model:
        return NotFoundError.return_resp()
    if login_user.user_id != session_version_model.user_id:
        return UnAuthorizedError.return_resp()

    try:
        modify_res = await LinsightWorkbenchImpl.modify_sop(linsight_session_version_id=linsight_session_version_id,
                                                            sop_content=sop_content)
    except Exception as e:
        return LinsightModifySopError.return_resp(data=str(e))
    return resp_200(modify_res)


# workbench to process
@router.post("/workbench/start-execute", summary="Start Executing Reims", response_model=UnifiedResponseModel)
async def start_execute_sop(
        background_tasks: BackgroundTasks,
        linsight_session_version_id: str = Body(..., description="Inspiration Conversation VersionID", embed=True),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    Start Executing ReimsSOP
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """

    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=linsight_session_version_id)
    if not session_version_model:
        return NotFoundError.return_resp()

    if login_user.user_id != session_version_model.user_id:
        return UnAuthorizedError.return_resp()

    if session_version_model.status in [SessionVersionStatusEnum.COMPLETED, SessionVersionStatusEnum.TERMINATED,
                                        SessionVersionStatusEnum.IN_PROGRESS]:
        # The Inspiration session version has been completed or is being executed and cannot be executed again
        return LinsightSessionVersionRunningError.return_resp()

    from bisheng.linsight.worker import LinsightQueue
    try:
        redis_client = await get_redis_client()
        queue = LinsightQueue('queue', namespace="linsight", redis=redis_client)

        await queue.put(data=linsight_session_version_id)
        # will besopWrite to record table
        background_tasks.add_task(SOPManageService.add_sop_record, LinsightSOPRecord(
            name=session_version_model.title,
            description=None,
            user_id=login_user.user_id,
            content=session_version_model.sop,
            linsight_version_id=session_version_model.id,
            create_time=session_version_model.create_time,
        ))

    except Exception as e:
        logger.error(f"Failed to start the Ideas task: {str(e)}")
        await InviteCodeService.revoke_invite_code(user_id=login_user.user_id)
        return LinsightStartTaskError.return_resp(data=str(e))

    return resp_200(data=True, message="Ideas execution task has started, execution results will be returned via message flow")


# workbench User input
@router.post("/workbench/user-input", summary="User input Ideas", response_model=UnifiedResponseModel)
async def user_input(
        session_version_id: str = Body(..., description="Inspiration Conversation VersionID"),
        linsight_execute_task_id: str = Body(..., description="Inspiration Task ExecutionID"),
        input_content: str = Body(..., description="User input"),
        files: Optional[List[SubmitFileSchema]] = Body(None, description="User-uploaded files"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    User input
    :param files:
    :param session_version_id:
    :param input_content:
    :param linsight_execute_task_id:
    :param login_user:
    :return:
    """

    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=session_version_id)
    if not session_version_model:
        return NotFoundError.return_resp()

    if login_user.user_id != session_version_model.user_id:
        return UnAuthorizedError.return_resp()

    state_message_manager = LinsightStateMessageManager(session_version_id=session_version_id)

    # If there are documents Process files first
    processed_files = await LinsightWorkbenchImpl.human_participate_add_file(session_version_model, files=files)

    await state_message_manager.set_user_input(task_id=linsight_execute_task_id, user_input=input_content,
                                               files=processed_files)

    return resp_200(data=True, message="User input submitted")


# workbench Submitting Execution Result Feedback
@router.post("/workbench/submit-feedback", summary="Submitting Execution Result Feedback", response_model=UnifiedResponseModel)
async def submit_feedback(
        background_tasks: BackgroundTasks,
        linsight_session_version_id: str = Body(..., description="Inspiration Conversation VersionID"),
        feedback: str = Body(None, description="User feedback"),
        score: int = Body(0, ge=0, le=5, description="Users rating1-5cent"),
        is_reexecute: bool = Body(False, description="Whether to re-execute"),
        cancel_feedback: bool = Body(False, description="Cancel feedback"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    Submitting Execution Result Feedback
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
        return NotFoundError.return_resp()

    if login_user.user_id != session_version_model.user_id:
        return UnAuthorizedError.return_resp()

    if score is not None and 0 < score <= 5:
        session_version_model.score = score
        await SOPManageService.update_sop_record_score(session_version_model.id, score)

    if feedback is not None:
        session_version_model.execute_feedback = feedback
    else:
        session_version_model.execute_feedback = "User did not provide feedback"

    # If the feedback is canceled
    if cancel_feedback:
        session_version_model.execute_feedback = "User canceled feedback"
        await LinsightSessionVersionDao.insert_one(session_version_model)
        return resp_200(data=True, message="Submit successful.")

    session_version_model = await LinsightSessionVersionDao.insert_one(session_version_model)

    if is_reexecute:
        # Re-implementing the Logic of Ideas
        system_config = await settings.aget_all_config()

        # DapatkanLinsight_invitation_code
        linsight_invitation_code = system_config.get("linsight_invitation_code", False)

        if linsight_invitation_code:
            if await InviteCodeService.use_invite_code(user_id=login_user.user_id) is False:
                return LinsightUseUpError.return_resp()

        # Inspiration Conversation Version
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
                        message="The submission successfully succeeded.")
    else:

        if feedback is not None and feedback.strip() != "":
            await SOPManageService.update_sop_record_feedback(session_version_model.id, feedback)

        return resp_200(data=True, message="Submit successful.")


# workbench Termination
@router.post("/workbench/terminate-execute", summary="Termination of execution of Ideas", response_model=UnifiedResponseModel)
async def terminate_execute(
        linsight_session_version_id: str = Body(..., description="Inspiration Conversation VersionID", embed=True),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    Termination of execution of Ideas
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """
    # The logic of executing Spirituality is now terminated
    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=linsight_session_version_id)

    if not session_version_model:
        return NotFoundError.return_resp()
    if login_user.user_id != session_version_model.user_id:
        return UnAuthorizedError.return_resp()

    if session_version_model.status == SessionVersionStatusEnum.COMPLETED:
        # return resp_500(code=400, message="Execution cannot be terminated because the Inspiration session version has been completed")
        return InvalidOperationError.return_resp()

    if session_version_model.status == SessionVersionStatusEnum.TERMINATED:
        # return resp_500(code=400, message="Execution terminated for Inspiration session version")
        return InvalidOperationError.return_resp()

    from bisheng.linsight.worker import LinsightQueue
    redis_client = await get_redis_client()
    queue = LinsightQueue('queue', namespace="linsight", redis=redis_client)

    try:
        # Remove task from queue
        await queue.remove(linsight_session_version_id)
    except Exception as e:
        logger.error(f"Failed to delete queue task: {str(e)}")

    # Update status is terminated
    session_version_model.status = SessionVersionStatusEnum.TERMINATED

    state_message_manager = LinsightStateMessageManager(session_version_id=linsight_session_version_id)

    await state_message_manager.set_session_version_info(session_version_model)

    state_message_manager = LinsightStateMessageManager(session_version_id=session_version_model.id)
    # Push termination message
    await state_message_manager.push_message(
        MessageData(
            event_type=MessageEventType.TASK_TERMINATED,
            data={
                "message": "Task has been actively stopped by the user",
                "session_id": session_version_model.id,
                "terminated_at": datetime.now().isoformat()
            }
        )
    )

    return resp_200(data=True, message="Idea Execution Terminated")


# Get all the Inspiration information for the current session
@router.get("/workbench/session-version-list", summary="Get all the Inspiration information for the current session", response_model=UnifiedResponseModel)
async def get_linsight_session_version_list(
        session_id: str = Query(..., description="SessionsID"),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        share_link: Union['ShareLink', None] = Depends(header_share_token_parser)
) -> UnifiedResponseModel:
    """
    Get all the Inspiration information for the current session
    :param share_link:
    :param session_id:
    :param login_user:
    :return:
    """

    linsight_session_version_models = await LinsightWorkbenchImpl.get_linsight_session_version_list(session_id)

    if linsight_session_version_models and login_user.user_id != linsight_session_version_models[0].user_id:
        # Access by sharing a link
        session_version_ids = [model.id for model in linsight_session_version_models]

        # Access by sharing a link
        if (share_link is None or
                share_link.meta_data is None or
                share_link.meta_data.get("versionId") not in session_version_ids):
            return UnAuthorizedError.return_resp()

        # Only return to the shared version of the Inspiration session
        linsight_session_version_models = [
            model for model in linsight_session_version_models if model.id == share_link.meta_data.get("versionId")
        ]

    return resp_200([model.model_dump() for model in linsight_session_version_models])


# Get task execution details
@router.get("/workbench/execute-task-detail", summary="Get task execution details", response_model=UnifiedResponseModel)
async def get_execute_task_detail(
        session_version_id: str = Query(..., description="Inspiration Conversation VersionID"),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        share_link: Union['ShareLink', None] = Depends(header_share_token_parser)) -> UnifiedResponseModel:
    """
    Get task execution details
    :param share_link:
    :param session_version_id:
    :param login_user:
    :return:
    """

    execute_task_models = await LinsightWorkbenchImpl.get_execute_task_detail(session_version_id)

    if not execute_task_models:
        return resp_200([])

    linsight_session_version_model = await LinsightSessionVersionDao.get_by_id(session_version_id)

    if login_user.user_id != linsight_session_version_model.user_id:
        # Access by sharing a link
        if (share_link is None or
                share_link.meta_data is None or
                share_link.meta_data.get("versionId") != session_version_id):
            return UnAuthorizedError.return_resp()

    return resp_200(execute_task_models)


# Creating an Idea Task Message Flow websocket
@router.websocket("/workbench/task-message-stream", name="task_message_stream")
async def task_message_stream(
        websocket: WebSocket,
        session_version_id: str = Query(..., description="Inspiration Conversation VersionID"),
        login_user: UserPayload = Depends(UserPayload.get_login_user_from_ws)):
    """
    Creating an Idea Task Message Flow websocket
    :param Authorize:
    :param websocket:
    :param session_version_id:
    :return:
    """
    start_time = time.time()
    try:
        message_handler = MessageStreamHandle(websocket=websocket, session_version_id=session_version_id)

        await message_handler.connect()

    except Exception as e:
        await websocket.close(code=1000, reason=str(e))
        return
    finally:
        end_time = time.time()
        session_version_info = await LinsightSessionVersionDao.get_by_id(session_version_id)

        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationAliveEventData(
                                              app_id=ApplicationTypeEnum.LINSIGHT.value,
                                              app_name=ApplicationTypeEnum.LINSIGHT.value,
                                              app_type=ApplicationTypeEnum.LINSIGHT,
                                              chat_id=session_version_info.session_id if session_version_info else "",
                                              start_time=int(start_time),
                                              end_time=int(end_time)
                                          ))
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationProcessEventData(
                                              app_id=ApplicationTypeEnum.LINSIGHT.value,
                                              app_name=ApplicationTypeEnum.LINSIGHT.value,
                                              app_type=ApplicationTypeEnum.LINSIGHT,
                                              chat_id=session_version_info.session_id if session_version_info else "",

                                              start_time=int(start_time),
                                              end_time=int(end_time),
                                              process_time=int((end_time - start_time) * 1000)
                                          ))


# Batch Download Task Files
@router.post("/workbench/batch-download-files", summary="Batch Download Task Files")
async def batch_download_files(
        zip_name: str = Body(..., description="Package name"),
        file_info_list: List[DownloadFilesSchema] = Body(..., description="File Information List"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Batch Download Task Files
    :param zip_name:
    :param file_info_list:
    :param login_user:
    :return:
    """

    try:
        # Call to implement class processing batch download
        zip_bytes = await LinsightWorkbenchImpl.batch_download_files(file_info_list)

        zip_name = zip_name if os.path.splitext(zip_name)[-1] == ".zip" else f"{zip_name}.zip"
        # Convert to unicode String
        zip_name = parse.quote(zip_name)
        return StreamingResponse(
            iter([zip_bytes]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={zip_name}"
            }
        )
    except Exception as e:
        logger.error(f"Failed to download file in bulk: {str(e)}")
        return ResourceDownloadError.return_resp(data=str(e))


# Get Queue Queue Status
@router.get("/workbench/queue-status", summary="Get Ideas Queue Queue Status", response_model=UnifiedResponseModel)
async def get_queue_status(
        session_version_id: str = Query(..., description="Inspiration Conversation VersionID"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    Get Ideas Queue Queue Status
    :param session_version_id:
    :param login_user:
    :return:
    """
    from bisheng.linsight.worker import LinsightQueue
    redis_client = await get_redis_client()
    queue = LinsightQueue('queue', namespace="linsight", redis=redis_client)
    try:
        index = await queue.index(session_version_id)
        return resp_200(data={"index": index}, message="Get Ideas queue queue status successfully")
    except Exception as e:
        logger.error(f"Failed to get Ideas queue queue status: {str(e)}")
        return LinsightQueueStatusError.return_resp(data=str(e))


# InspirationmdTransferpdf or docx Mengunduh
@router.post("/workbench/download-md-to-pdf-or-docx", summary="InspirationmdTransferpdf or docx Mengunduh")
async def download_md_to_pdf_or_docx(
        file_info: DownloadFilesSchema = Body(..., description="File information"),
        to_type: Literal["pdf", "docx"] = Body(..., description="the target file type of the conversion,pdfORdocx"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    InspirationmdTransferpdf or docx Mengunduh
    :param file_info:
    :param to_type:
    :param login_user:
    :return:
    """
    try:
        # Call the implementation class to process the file download
        file_name, file_bytes = await LinsightWorkbenchImpl.download_file(file_info)

        md_str = file_bytes.decode('utf-8')

        # Filename Removal Extension
        file_name = os.path.splitext(file_name)[0]

        if to_type == "pdf":
            from bisheng.common.utils.markdown_cmpnt.md_to_pdf import md_to_pdf_bytes
            converted_bytes = await util.sync_func_to_async(md_to_pdf_bytes)(md_str)
            file_name = f"{file_name}.pdf"
            content_type = "application/pdf"
        else:
            from bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx import MarkDocx
            mark_docx = MarkDocx()
            converted_bytes, _ = await util.sync_func_to_async(mark_docx)(md_str)
            file_name = f"{file_name}.docx"
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        # Convert to unicode String
        file_name = parse.quote(file_name)
        return StreamingResponse(
            iter([converted_bytes]),
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={file_name}"
            }
        )
    except Exception as e:
        logger.error(f"This content failed to load: {str(e)}")
        return ResourceDownloadError.return_resp(data=str(e))


@router.post("/sop/add", summary="Add InspirationSOP", response_model=UnifiedResponseModel)
async def add_sop(
        sop_obj: SOPManagementSchema = Body(..., description="SOPObjects"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    Add InspirationSOP
    :return:
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()

    return await SOPManageService.add_sop(sop_obj, user_id=login_user.user_id)


@router.post("/sop/update", summary="Update IdeasSOP", response_model=UnifiedResponseModel)
async def update_sop(
        sop_obj: SOPManagementUpdateSchema = Body(..., description="SOPObjects"),
        login_user: UserPayload = Depends(UserPayload.get_admin_user)) -> UnifiedResponseModel:
    """
    Update IdeasSOP
    :return:
    """
    sop_obj.user_id = login_user.user_id
    return await SOPManageService.update_sop(sop_obj, update_version_id=False)


@router.get("/sop/list", summary="Get IdeasSOPVertical", response_model=UnifiedResponseModel)
async def get_sop_list(
        keywords: str = Query(None, description="Keywords Search"),
        showcase: bool = Query(None, description="Get featured cases only?"),
        page: int = Query(1, ge=1, description="Page"),
        page_size: int = Query(10, ge=1, le=100, description="Items per page"),
        sort: Literal["asc", "desc"] = Query("desc", description="Sort ByascORdesc"),
        login_user: UserPayload = Depends(UserPayload.get_admin_user)) -> UnifiedResponseModel:
    """
    Get IdeasSOPVertical
    :return:
    """

    sop_pages = await SOPManageService.get_sop_list(keywords=keywords, showcase=showcase, page=page,
                                                    page_size=page_size,
                                                    sort=sort)
    return resp_200(data=sop_pages)


@router.get("/sop/record", summary="Get IdeasSOPRecord", response_model=UnifiedResponseModel)
async def get_sop_record(login_user: UserPayload = Depends(UserPayload.get_admin_user),
                         keyword: str = Query(None, description="Search keyword ..."),
                         sort: str = Query(default='desc', description="Sort ByascORdesc"),
                         page: int = Query(1, ge=1, description="Page"),
                         page_size: int = Query(10, ge=1, le=100, description="Items per page")):
    res, count = await SOPManageService.get_sop_record(keyword, sort, page, page_size)
    return resp_200(PageList(total=count, list=res))


@router.post("/sop/record/sync", summary="SynchronoussopRecord toSOPGallery", response_model=UnifiedResponseModel)
async def sync_sop_record(
        login_user: UserPayload = Depends(UserPayload.get_admin_user),
        record_ids: list[int] = Body(..., description="sopThe only one in the record sheetid"),
        override: Optional[bool] = Body(default=False,
                                        description="Force override or not"),
        save_new: Optional[bool] = Body(default=False,
                                        description="Do you want to save as newsop")) -> UnifiedResponseModel:
    """
    SynchronousSOP"Log to"SOPGallery
    """
    repeat_name = await SOPManageService.sync_sop_record(record_ids, override, save_new)
    return resp_200(data={
        "repeat_name": repeat_name,
    }, message="success")


@router.post("/sop/upload", summary="Batch importSOPWarehousing", response_model=UnifiedResponseModel)
async def upload_sop_file(
        file: UploadFile = File(..., description="Uploaded bySOPDoc."),
        override: Optional[bool] = Body(default=False, description="Force override or not"),
        save_new: Optional[bool] = Body(default=False, description="Do you want to save as newsop"),
        ignore_error: Optional[bool] = Body(default=False, description="Whether to ignore the file and find the wrong record"),
        login_user: UserPayload = Depends(UserPayload.get_admin_user)) -> UnifiedResponseModel:
    """
    Batch importSOPWarehousing
    """

    success_rows, error_rows, repeat_rows = await SOPManageService.upload_sop_file(login_user, file, ignore_error,
                                                                                   override, save_new)

    return resp_200(data={
        "success_rows": success_rows,
        "error_rows": error_rows,
        "repeat_rows": repeat_rows,
    })


@router.delete("/sop/remove", summary="Delete IdeasSOP", response_model=UnifiedResponseModel)
async def remove_sop(
        sop_ids: List[int] = Body(..., description="SOPUniqueness quantificationIDVertical", embed=True),
        login_user: UserPayload = Depends(UserPayload.get_admin_user)) -> UnifiedResponseModel:
    """
    Delete IdeasSOP
    :return:
    """

    return await SOPManageService.remove_sop(sop_ids, login_user)


@router.get("/sop/showcase", summary="InspirationsopLibrary's Featured Cases", response_model=UnifiedResponseModel)
async def get_sop_banner(
        page: int = Query(1, ge=1, description="Page"),
        page_size: int = Query(10, ge=1, le=100, description="Items per page"),
        sort: Literal["asc", "desc"] = Query("desc", description="Sort ByascORdesc"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    """
    Set or cancel IdeasSOPLibrary's Featured Cases
    :return:
    """
    sop_pages = await SOPManageService.get_sop_list(showcase=True, page=page, page_size=page_size, sort=sort)
    return resp_200(data=sop_pages)


@router.post("/sop/showcase", summary="Set or unset a featured case for Inspirations", response_model=UnifiedResponseModel)
async def set_sop_banner(
        sop_id: int = Body(..., description="SOPUniqueness quantificationID"),
        showcase: bool = Body(..., description="Set as featured case or not"),
        login_user: UserPayload = Depends(UserPayload.get_admin_user)) -> UnifiedResponseModel:
    """
    Set or cancel IdeasSOPLibrary's Featured Cases
    :return:
    """
    # CorrectionSOPpresence or does it
    existing_sop = await LinsightSOPDao.get_sops_by_ids([sop_id])
    if not existing_sop:
        raise NotFoundError.http_exception(msg="sop not found")
    if showcase:
        # Setting as featured case requires checking for run results
        existing_sop = existing_sop[0]
        if not existing_sop.linsight_version_id:
            raise SopShowcaseError.http_exception()
        execute_task_models = await LinsightWorkbenchImpl.get_execute_task_detail(existing_sop.linsight_version_id)
        if not execute_task_models:
            raise SopShowcaseError.http_exception()

    await LinsightSOPDao.set_sop_showcase(sop_id, showcase)
    return resp_200()


@router.get("/sop/showcase/result", summary="Obtain the results of the execution of the selected cases of Lingsi", response_model=UnifiedResponseModel)
async def get_sop_showcase_result(
        sop_id: int = Query(None, description="SOPUniqueness quantificationID"),
        linsight_version_id: str = Query(None, description="Inspiration Conversation VersionID, use this parameter first"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)) -> UnifiedResponseModel:
    if not linsight_version_id:
        # CorrectionSOPpresence or does it
        existing_sop = await LinsightSOPDao.get_sops_by_ids([sop_id])
        if not existing_sop:
            raise NotFoundError.http_exception(msg="sop not found")
        linsight_version_id = existing_sop[0].linsight_version_id
    if not linsight_version_id:
        return resp_200(data={"version_info": None, "execute_tasks": []})
    version_info = await LinsightSessionVersionDao.get_by_id(linsight_version_id)
    # Outstanding sessions do not return execution results
    if not version_info or version_info.status != SessionVersionStatusEnum.COMPLETED:
        return resp_200(data={
            "version_info": None,
            "execute_tasks": []
        })
    execute_task_models = await LinsightWorkbenchImpl.get_execute_task_detail(linsight_version_id)
    return resp_200(data={
        "version_info": version_info,
        "execute_tasks": execute_task_models
    })


class IntegratedExecuteRequestBody(BaseModel):
    query: Optional[str] = Body(None, description="User Submitted Questions")
    sop_content: Optional[str] = Body(None, description="User SubmittedSOPContents")
    tool_ids: List[int] = Body(None, description="Selected ToolsIDVertical")
    org_knowledge_enabled: bool = Body(False, description="Whether to enable organization knowledge base")
    personal_knowledge_enabled: bool = Body(False, description="Whether or not to enable Personal Knowledge Base")
    # Generate Inspiration OnlySOPNo
    only_generate_sop: bool = Body(False, description="Whether to generate onlySOPNo")


# Lingsi Integrated Execution Interface
@router.post("/integrated-execute", summary="Lingsi Integrated Execution Interface")
async def integrated_execute(
        request: Request,
        body_param: str = Form(..., description="Request Body Parameters,JSONString",
                               example='{"query": "Please write one for mePythonfunction that calculates the sum of two numbers.", "tool_ids": [1, 2], "org_knowledge_enabled": true, "personal_knowledge_enabled": false}'),
        files: List[UploadFile] = File(None, description="Uploaded files list:"),
        login_user: UserPayload = Depends(UserPayload.get_login_user)
) -> EventSourceResponse:
    """
    Lingsi Integrated Execution Interface
    :param body_param: Request Body Parameters,JSONString
    :param request: Request object
    :param files: Uploaded files list:
    :param login_user: Logged in user information
    :return: SSEEvent Flow Response
    """

    # ======================== Parameter Validation ========================
    try:
        body_param = IntegratedExecuteRequestBody.model_validate_json(body_param)

        if not body_param.query and not body_param.sop_content:
            logger.error(f"Users {login_user.user_id} Bad request body parameters: queryAndsop_contentCannot be empty at the same time")
            return EventSourceResponse(iter([{
                "event": "error",
                "data": json.dumps({
                    "error": "Bad request body parameters",
                    "message": "queryAndsop_contentCannot be empty at the same time",
                    "code": "PARAM_ERROR"
                })
            }]))

    except ValidationError as e:
        logger.error(f"Users {login_user.user_id} Request body parameter parsing failed: {str(e)}")
        return EventSourceResponse(iter([{
            "event": "error",
            "data": json.dumps({
                "error": "Request body parameter parsing failed",
                "message": str(e),
                "code": "PARAM_VALIDATION_ERROR"
            })
        }]))
    except Exception as e:
        logger.error(f"Users {login_user.user_id} Parameter parsing exception: {str(e)}")
        return EventSourceResponse(iter([{
            "event": "error",
            "data": json.dumps({
                "error": "Parameter parsing exception",
                "message": str(e),
                "code": "PARAM_PARSE_ERROR"
            })
        }]))

    logger.info(f"Users {login_user.user_id} Submit an Idea Question: {body_param.query}")

    # ======================== Upload file and parse ========================
    upload_file_results = []
    if files:
        logger.info(f"Users {login_user.user_id} Start Upload {len(files)} files")

        for idx, file in enumerate(files):
            try:
                # File size and type validation
                if file.size and file.size > 100 * 1024 * 1024:  # 100MBLimit
                    raise ValueError(f"Doc. {file.filename} Size exceeds limit(100MB)")

                if not file.filename:
                    raise ValueError(f"Doc. {idx + 1} The uploaded file has no filename")

                logger.debug(f"Starting file upload: {file.filename}")
                upload_result = await LinsightWorkbenchImpl.upload_file(file)

                if not upload_result:
                    raise ValueError(f"Doc. {file.filename} Upload failed, return result is empty")

                # Parse files asynchronously to increase timeout control
                parse_result = await asyncio.wait_for(
                    LinsightWorkbenchImpl.parse_file(upload_result, login_user.user_id),
                    timeout=300  # 5Minute Timeout
                )

                if not parse_result:
                    raise ValueError(f"Doc. {file.filename} Parsing failed, returned empty result")

                upload_file_results.append(parse_result)
                logger.debug(f"Doc. {file.filename} Upload parsing complete")

            except asyncio.TimeoutError:
                error_msg = f"Doc. {file.filename} Resolve Timeout"
                logger.error(f"Users {login_user.user_id} {error_msg}")
                return EventSourceResponse(iter([{
                    "event": "error",
                    "data": json.dumps({
                        "error": "File parsing timeout",
                        "message": error_msg,
                        "code": "FILE_PARSE_TIMEOUT"
                    })
                }]))


            except Exception as e:
                error_msg = f"Doc. {getattr(file, 'filename', f'{idx + 1} No filename')} Upload parsing error: {str(e)}"
                logger.error(f"Users {login_user.user_id} {error_msg}")
                return EventSourceResponse(iter([{
                    "event": "error",
                    "data": json.dumps({
                        "error": "Upload Failed",
                        "message": error_msg,
                        "code": "FILE_UPLOAD_ERROR"
                    })
                }]))

        # Check file parsing results
        if upload_file_results:
            failed_files = [
                f.get("original_filename", "Unknown file")
                for f in upload_file_results
                if f.get("parsing_status") == "failed"
            ]

            if failed_files:
                error_msg = f"The following files failed to be parsed: {', '.join(failed_files)}"
                logger.error(f"Users {login_user.user_id} {error_msg}")
                return EventSourceResponse(iter([{
                    "event": "error",
                    "data": json.dumps({
                        "error": "File parsing failed",
                        "message": error_msg,
                        "code": "FILE_PARSE_FAILED",
                        "failed_files": failed_files
                    })
                }]))

    async def event_generator():
        """
        Event generator for generatingSSE events
        """
        linsight_session_version_model = None
        state_message_manager = None

        try:

            # ======================== Submit an Idea Question ========================
            try:
                submit_files = []
                if upload_file_results:
                    for f in upload_file_results:
                        if not f.get("file_id"):
                            logger.warning(f"Doc. {f.get('original_filename', 'Unknown')} missing? file_id")
                            continue
                        submit_files.append(SubmitFileSchema(
                            file_id=f.get("file_id"),
                            file_name=f.get("original_filename"),
                            parsing_status=f.get("parsing_status")
                        ))

                submit_tools = None
                if body_param.tool_ids:
                    try:
                        submit_tools = [LinsightToolSchema(
                            id="1",
                            is_preset=1,
                            children=[
                                ToolChildrenSchema(id=int(tool_id))
                                for tool_id in body_param.tool_ids
                            ]
                        )]
                    except (ValueError, TypeError) as e:
                        logger.error(f"Users {login_user.user_id} ToolsIDfailed to transform: {str(e)}")
                        yield {
                            "event": "error",
                            "data": json.dumps({
                                "error": "ToolsIDFormat salah.",
                                "message": f"ToolsIDMust be numeric: {str(e)}",
                                "code": "INVALID_TOOL_ID"
                            })
                        }
                        return

                submit_obj = LinsightQuestionSubmitSchema(
                    question=body_param.query if body_param.query else "User did not provide a question",
                    org_knowledge_enabled=body_param.org_knowledge_enabled,
                    personal_knowledge_enabled=body_param.personal_knowledge_enabled,
                    files=submit_files,
                    tools=submit_tools
                )

                _, linsight_session_version_model = await LinsightWorkbenchImpl.submit_user_question(
                    submit_obj, login_user
                )

                if not linsight_session_version_model:
                    raise ValueError("Failed to submit the idea question, the return result is empty")

                yield {
                    "event": "linsight_workbench_submit",
                    "data": linsight_session_version_model.model_dump_json()
                }

            except Exception as e:
                error_msg = f"Failed to submit Idea Question: {str(e)}"
                logger.error(f"Users {login_user.user_id} {error_msg}")
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "error": "Failed to submit question",
                        "message": error_msg,
                        "code": "SUBMIT_QUESTION_ERROR"
                    })
                }
                return

            # ======================== BuatSOP ========================
            if body_param.sop_content:
                # User Submitted DirectlySOPcontent, skipping generationSOPStep
                await LinsightSessionVersionDao.modify_sop_content(
                    linsight_session_version_id=linsight_session_version_model.id,
                    sop_content=body_param.sop_content
                )
            else:
                try:
                    knowledge_res = []
                    linsight_conf = settings.get_linsight_conf()

                    # Get the organization's knowledge base
                    if (linsight_session_version_model.org_knowledge_enabled and
                            linsight_conf and linsight_conf.max_knowledge_num > 0):
                        try:
                            org_knowledge, _ = await KnowledgeService.get_knowledge(
                                request, login_user, KnowledgeTypeEnum.NORMAL, None, 1,
                                linsight_conf.max_knowledge_num
                            )
                            if org_knowledge:
                                knowledge_res.extend(org_knowledge)
                                logger.debug(f"Get {len(org_knowledge)} organization knowledge")
                        except Exception as e:
                            logger.warning(f"Users {login_user.user_id} Failed to get organization knowledge base: {str(e)}")
                            # Proceed without interrupting the process

                    # Get your own knowledge base
                    if linsight_session_version_model.personal_knowledge_enabled:
                        try:
                            personal_knowledge = await KnowledgeDao.aget_user_knowledge(
                                login_user.user_id, None, KnowledgeTypeEnum.PRIVATE
                            )
                            if personal_knowledge:
                                knowledge_res.extend(personal_knowledge)
                                logger.debug(f"Get {len(personal_knowledge)} personal knowledge")
                        except Exception as e:
                            logger.warning(f"Users {login_user.user_id} Failed to get personal knowledge base: {str(e)}")
                            # Proceed without interrupting the process

                    # BuatSOP
                    sop_generate = LinsightWorkbenchImpl.generate_sop(
                        linsight_session_version_id=linsight_session_version_model.id,
                        previous_session_version_id=None,
                        feedback_content=None,
                        reexecute=False,
                        login_user=login_user,
                        knowledge_list=knowledge_res
                    )

                    async for event in sop_generate:
                        if event.get("event") == "error":
                            yield event
                            return
                        yield event

                    yield {
                        "event": "sop_generate_complete",
                        "data": json.dumps({"message": "SOPBuild Complete"})
                    }

                except Exception as e:
                    error_msg = f"SOPGeneration Failed: {str(e)}"
                    logger.error(f"Users {login_user.user_id} {error_msg}")
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "error": "SOPGeneration Failed",
                            "message": error_msg,
                            "code": "SOP_GENERATE_ERROR"
                        })
                    }
                    return

            if body_param.only_generate_sop:
                return

            # ======================== to process ========================
            try:
                from bisheng.linsight.worker import LinsightQueue
                redis_client = await get_redis_client()
                queue = LinsightQueue('queue', namespace="linsight", redis=redis_client)
                await queue.put(data=linsight_session_version_model.id)

                yield {
                    "event": "linsight_execute_submitted",
                    "data": json.dumps({"message": "Idea Execution Task Submitted"})
                }

            except Exception as e:
                error_msg = f"Failed to submit execution task: {str(e)}"
                logger.error(f"Users {login_user.user_id} {error_msg}")
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "error": "Failed to submit execution task",
                        "message": error_msg,
                        "code": "SUBMIT_TASK_ERROR"
                    })
                }
                return

            # ======================== Consumer Message Flow ========================
            try:
                state_message_manager = LinsightStateMessageManager(
                    session_version_id=linsight_session_version_model.id
                )
                final_result_message = None
                message_count = 0
                max_messages = 10000  # Prevents infinite loops
                max_wait_time = 60 * 60  # Maximum Wait1Jam
                start_time = time.time()

                while message_count < max_messages:
                    # Check timeout
                    if time.time() - start_time > max_wait_time:
                        logger.warning(f"Users {login_user.user_id} Message consumption timed out")
                        yield {
                            "event": "warning",
                            "data": json.dumps({
                                "message": "The execution time is longer and may take more time to complete",
                                "code": "EXECUTION_TIMEOUT_WARNING"
                            })
                        }
                        break

                    try:
                        message = await asyncio.wait_for(
                            state_message_manager.pop_message(),
                            timeout=10.0  # 10seconds timeout
                        )
                    except asyncio.TimeoutError:

                        linsight_session_version_model = await state_message_manager.get_session_version_info()

                        if linsight_session_version_model.status in [
                            SessionVersionStatusEnum.COMPLETED,
                            SessionVersionStatusEnum.TERMINATED,
                            SessionVersionStatusEnum.FAILED
                        ]:
                            message = MessageData(
                                event_type=MessageEventType.FINAL_RESULT if linsight_session_version_model.status == SessionVersionStatusEnum.COMPLETED else MessageEventType.TASK_TERMINATED,
                                data=linsight_session_version_model.model_dump()
                            )

                            if message.event_type == MessageEventType.FINAL_RESULT:
                                final_result_message = message

                            yield {
                                "event": "linsight_execute_message",
                                "data": message.model_dump_json()
                            }

                            logger.info(f"Users {login_user.user_id} Idea execution has ended, stop getting messages")
                            break

                        # Timeout to continue waiting
                        continue
                    except Exception as e:
                        logger.error(f"Users {login_user.user_id} Failed to fetch messages: {str(e)}")
                        break

                    if message:
                        message_count += 1
                        yield {
                            "event": "linsight_execute_message",
                            "data": message.model_dump_json()
                        }

                        # Save final result message
                        if message.event_type == MessageEventType.FINAL_RESULT:
                            final_result_message = message

                        # Check termination conditions
                        if message.event_type in [
                            MessageEventType.ERROR_MESSAGE,
                            MessageEventType.TASK_TERMINATED,
                            MessageEventType.FINAL_RESULT
                        ]:
                            break
                    else:
                        await asyncio.sleep(1)

                # Process final result message
                final_files = []
                all_from_session_files = []

                if final_result_message and final_result_message.data:
                    try:
                        session_version_model = LinsightSessionVersion.model_validate(final_result_message.data)

                        if session_version_model.output_result:
                            final_files = session_version_model.output_result.get("final_files", [])
                            all_from_session_files = session_version_model.output_result.get("all_from_session_files",
                                                                                             [])

                            minio_client = await get_minio_storage()

                            # Generate file sharing link
                            for final_file in final_files:
                                if final_file.get("url"):
                                    try:
                                        final_file["url"] = await minio_client.get_share_link(final_file["url"],
                                                                                              clear_host=False)
                                    except Exception as e:
                                        logger.warning(f"Failed to generate final file share link: {str(e)}")

                            for session_file in all_from_session_files:
                                if session_file.get("url"):
                                    try:
                                        session_file["url"] = await minio_client.get_share_link(session_file["url"],
                                                                                                clear_host=False)
                                    except Exception as e:
                                        logger.warning(f"Failed to generate session file share link: {str(e)}")

                    except Exception as e:
                        logger.error(f"Users {login_user.user_id} Failed to process final result: {str(e)}")

                yield {
                    "event": "final_result_files",
                    "data": json.dumps({
                        "final_files": final_files,
                        "all_from_session_files": all_from_session_files
                    })
                }

            except Exception as e:
                error_msg = f"Message consumption failed: {str(e)}"
                logger.error(f"Users {login_user.user_id} {error_msg}")
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "error": "Message consumption failed",
                        "message": error_msg,
                        "code": "MESSAGE_CONSUME_ERROR"
                    })
                }
                return

        except Exception as e:
            # Catch all unhandled exceptions
            error_msg = f"Interface Execution Exception: {str(e)}"
            logger.error(f"Users {login_user.user_id} {error_msg}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({
                    "error": "System Exception",
                    "message": error_msg,
                    "code": "SYSTEM_ERROR"
                })
            }

        finally:
            pass

    return EventSourceResponse(event_generator())
