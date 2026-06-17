import json
import os
import time
from datetime import datetime
from typing import Literal, Union
from urllib import parse

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Query, UploadFile
from loguru import logger
from sse_starlette import EventSourceResponse
from starlette.responses import StreamingResponse
from starlette.websockets import WebSocket

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.api.v1.schema.base_schema import PageList
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.linsight import (
    FileUploadError,
    LinsightQuestionError,
    LinsightQueueStatusError,
    LinsightSessionVersionRunningError,
    LinsightStartTaskError,
    LinsightUseUpError,
    SopShowcaseError,
)
from bisheng.common.errcode.server import InvalidOperationError, ResourceDownloadError
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationAliveEventData, ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.session import MessageSessionDao
from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersionDao,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.models.linsight_sop import LinsightSOPDao, LinsightSOPRecord
from bisheng.linsight.domain.schemas.inspiration_schema import SOPManagementSchema, SOPManagementUpdateSchema
from bisheng.linsight.domain.schemas.linsight_schema import (
    DownloadFilesSchema,
    LinsightQuestionSubmitSchema,
    SubmitFileSchema,
)
from bisheng.linsight.domain.services.message_stream_handle import MessageStreamHandle
from bisheng.linsight.domain.services.sop_manage import SOPManageService
from bisheng.linsight.domain.services.state_message_manager import (
    LinsightStateMessageManager,
    MessageData,
    MessageEventType,
)
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.utils import util

router = APIRouter()


# Inspiration Upload File
@router.post("/workbench/upload-file", summary="Inspiration Upload File", response_model=UnifiedResponseModel)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
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
        logger.error(f"Upload Failed: {e!s}")
        return FileUploadError.return_resp()
    finally:
        await file.close()

    # Back to upload results
    return resp_200(
        data=result,
        message="Key file uploaded successfully! and start parsing. Please check the resolution status later.",
    )


# Get file resolution status
@router.post(
    "/workbench/file-parsing-status", summary="Get file resolution status", response_model=UnifiedResponseModel
)
async def get_file_parsing_status(
    file_ids: list[str] = Body(..., description="Doc.IDVertical", embed=True),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
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
    share_link: Union["ShareLink", None] = Depends(header_share_token_parser),
) -> UnifiedResponseModel:
    session_version_model = await LinsightSessionVersionDao.get_by_id(session_version_id)
    if not session_version_model:
        raise NotFoundError()

    # judge permission
    if session_version_model.user_id != login_user.user_id and not login_user.is_admin():
        # Access by sharing a link
        if (
            share_link is None
            or share_link.meta_data is None
            or share_link.meta_data.get("versionId") != session_version_id
        ):
            raise UnAuthorizedError()

    minio_client = await get_minio_storage()
    file_url = file_url.lstrip("/")
    if file_url.startswith(minio_client.bucket):
        file_url = file_url[len(minio_client.bucket) + 1 :]
    file_share_url = await minio_client.get_share_link(file_url)
    return resp_200(data={"file_path": file_share_url})


# Submit an Idea User Issue Request
@router.post("/workbench/submit", summary="Submit an Idea User Issue Request")
async def submit_linsight_workbench(
    submit_obj: LinsightQuestionSubmitSchema = Body(..., description="Idea User Issue Submitter"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> EventSourceResponse:
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
                submit_obj, login_user
            )

            response_data = {
                "message_session": message_session_model.model_dump(),
                "linsight_session_version": linsight_session_version_model.model_dump(),
            }
        except Exception as e:
            yield LinsightQuestionError(exception=e).to_sse_event_instance()
            return

        yield {"event": "linsight_workbench_submit", "data": json.dumps(response_data)}

        # Task Title Generation
        title_data = await LinsightWorkbenchImpl.task_title_generate(
            question=submit_obj.question, chat_id=message_session_model.chat_id, login_user=login_user
        )

        linsight_session_version_model.title = title_data.get("task_title")
        await LinsightSessionVersionDao.insert_one(linsight_session_version_model)

        yield {"event": "linsight_workbench_title_generate", "data": json.dumps(title_data)}

    return EventSourceResponse(event_generator())


# workbench to process
@router.post("/workbench/start-execute", summary="Start Executing Reims", response_model=UnifiedResponseModel)
async def start_execute_sop(
    background_tasks: BackgroundTasks,
    linsight_session_version_id: str = Body(..., description="Inspiration Conversation VersionID", embed=True),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    """
    Start Executing ReimsSOP
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """

    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=linsight_session_version_id
    )
    if not session_version_model:
        return NotFoundError.return_resp()

    if login_user.user_id != session_version_model.user_id:
        return UnAuthorizedError.return_resp()

    if session_version_model.status in [
        SessionVersionStatusEnum.COMPLETED,
        SessionVersionStatusEnum.TERMINATED,
        SessionVersionStatusEnum.IN_PROGRESS,
    ]:
        # The Inspiration session version has been completed or is being executed and cannot be executed again
        return LinsightSessionVersionRunningError.return_resp()

    await MessageSessionDao.touch_session(session_version_model.session_id)

    from bisheng.linsight.worker import LinsightQueue

    try:
        redis_client = await get_redis_client()
        queue = LinsightQueue("queue", namespace="linsight", redis=redis_client)

        await queue.put(data=linsight_session_version_id)
        # Persist a SOP record only when the session actually carries SOP content.
        # Post-de-SOP (F035), session_version_model.sop can be None; writing it
        # would violate the linsight_sop_record.content NOT NULL constraint and
        # is meaningless without the removed "做同款" reuse flow.
        if session_version_model.sop:
            background_tasks.add_task(
                SOPManageService.add_sop_record,
                LinsightSOPRecord(
                    name=session_version_model.title,
                    description=None,
                    user_id=login_user.user_id,
                    content=session_version_model.sop,
                    linsight_version_id=session_version_model.id,
                    create_time=session_version_model.create_time,
                ),
            )

    except Exception as e:
        logger.error(f"Failed to start the Ideas task: {e!s}")
        await InviteCodeService.revoke_invite_code(user_id=login_user.user_id)
        return LinsightStartTaskError.return_resp(data=str(e))

    return resp_200(
        data=True, message="Ideas execution task has started, execution results will be returned via message flow"
    )


@router.post("/workbench/continue", summary="Continue a task-mode conversation with a new turn")
async def continue_conversation(
    session_version_id: str = Body(..., description="Existing session version id to continue", embed=True),
    question: str = Body(..., description="Follow-up user message", embed=True),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    """Continue an already-finished task-mode conversation (F035 multi-turn).

    A follow-up turn does NOT create a new session version: it re-enters the same
    session_version + same LangGraph thread so the agent keeps prior context. We
    flip the (terminal) session back to IN_PROGRESS — otherwise the worker's
    non-terminal guard would discard the queue item — then enqueue a
    continue-typed item. Answering a parked ask_user interrupt is a different
    flow (/workbench/user-input, resume); this endpoint is for new turns after a
    round has fully completed.
    """
    session_version_model = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id=session_version_id)
    if not session_version_model:
        return NotFoundError.return_resp()

    if login_user.user_id != session_version_model.user_id:
        return UnAuthorizedError.return_resp()

    if session_version_model.status not in [
        SessionVersionStatusEnum.COMPLETED,
        SessionVersionStatusEnum.FAILED,
    ]:
        # A running / parked session cannot take a new top-level turn; parked
        # tasks are continued via /workbench/user-input instead.
        return LinsightSessionVersionRunningError.return_resp()

    await MessageSessionDao.touch_session(session_version_model.session_id)

    # Flip back to IN_PROGRESS BEFORE enqueue so the worker's pre-flight
    # non-terminal guard accepts the continue item.
    await LinsightSessionVersionDao.batch_update_session_versions_status(
        [session_version_id], SessionVersionStatusEnum.IN_PROGRESS
    )

    try:
        from bisheng.linsight.worker import LinsightQueue, encode_queue_item

        redis_client = await get_redis_client()
        queue = LinsightQueue("queue", namespace="linsight", redis=redis_client)
        await queue.put(data=encode_queue_item(session_version_id, continue_question=question))
    except Exception as e:
        logger.error(f"Failed to continue the Ideas conversation: {e!s}")
        # Roll back the status flip so the conversation isn't stuck IN_PROGRESS.
        await LinsightSessionVersionDao.batch_update_session_versions_status(
            [session_version_id], SessionVersionStatusEnum.COMPLETED
        )
        return LinsightStartTaskError.return_resp(data=str(e))

    return resp_200(data=True, message="Follow-up turn accepted; results stream via the message flow")


# workbench User input
@router.post("/workbench/user-input", summary="User input Ideas", response_model=UnifiedResponseModel)
async def user_input(
    session_version_id: str = Body(..., description="Inspiration Conversation VersionID"),
    linsight_execute_task_id: str = Body(..., description="Inspiration Task ExecutionID"),
    input_content: str = Body(..., description="User input"),
    files: list[SubmitFileSchema] | None = Body(None, description="User-uploaded files"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    """
    User input
    :param files:
    :param session_version_id:
    :param input_content:
    :param linsight_execute_task_id:
    :param login_user:
    :return:
    """

    session_version_model = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id=session_version_id)
    if not session_version_model:
        return NotFoundError.return_resp()

    if login_user.user_id != session_version_model.user_id:
        return UnAuthorizedError.return_resp()

    await MessageSessionDao.touch_session(session_version_model.session_id)

    state_message_manager = LinsightStateMessageManager(session_version_id=session_version_id)

    # If there are documents Process files first
    processed_files = await LinsightWorkbenchImpl.human_participate_add_file(session_version_model, files=files)

    # Session-level clarify (ask_user fired before any todo exists): the interrupt
    # routes to the session pseudo task (task_id == session_version_id), which has
    # NO LinsightExecuteTask row, so set_user_input would 500. The resume only
    # needs the user_input VALUE (the worker reads it from the queue item, not the
    # task); persistence here is just for display/idempotency. So for the
    # session-level case we skip set_user_input and enqueue the resume directly.
    session_level = linsight_execute_task_id == session_version_id

    if session_level:
        already_completed = False
    else:
        # Idempotency guard: if the task is already USER_INPUT_COMPLETED, a resume
        # payload was already enqueued by the first submit; skip re-enqueue so a
        # double-submit cannot spawn two resume pick-ups for the same thread.
        existing_task = await state_message_manager.get_execution_task(linsight_execute_task_id)
        already_completed = (
            existing_task is not None and existing_task.status == ExecuteTaskStatusEnum.USER_INPUT_COMPLETED
        )

        await state_message_manager.set_user_input(
            task_id=linsight_execute_task_id, user_input=input_content, files=processed_files
        )

    # park-and-release (design §4.6): re-enqueue the parked task at the HEAD of
    # the queue so it resumes ahead of newly-queued tasks (PRD §4.4.4). A parked
    # task holds no worker slot; this lpush is what wakes it up. set_user_input
    # raises on failure, so reaching here means the input was persisted and the
    # task is now USER_INPUT_COMPLETED.
    if not already_completed:
        from bisheng.linsight.worker import LinsightQueue, encode_queue_item

        redis_client = await get_redis_client()
        queue = LinsightQueue("queue", namespace="linsight", redis=redis_client)
        await queue.put_head(encode_queue_item(session_version_id, resume=True, user_input=input_content))

    return resp_200(data=True, message="User input submitted")


# workbench Termination
@router.post(
    "/workbench/terminate-execute", summary="Termination of execution of Ideas", response_model=UnifiedResponseModel
)
async def terminate_execute(
    linsight_session_version_id: str = Body(..., description="Inspiration Conversation VersionID", embed=True),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    """
    Termination of execution of Ideas
    :param linsight_session_version_id:
    :param login_user:
    :return:
    """
    # The logic of executing Spirituality is now terminated
    session_version_model = await LinsightSessionVersionDao.get_by_id(
        linsight_session_version_id=linsight_session_version_id
    )

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

    await MessageSessionDao.touch_session(session_version_model.session_id)

    from bisheng.linsight.worker import LinsightQueue

    redis_client = await get_redis_client()
    queue = LinsightQueue("queue", namespace="linsight", redis=redis_client)

    try:
        # Remove task from queue
        await queue.remove(linsight_session_version_id)
    except Exception as e:
        logger.error(f"Failed to delete queue task: {e!s}")

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
                "terminated_at": datetime.now().isoformat(),
            },
        )
    )

    return resp_200(data=True, message="Idea Execution Terminated")


# Get all the Inspiration information for the current session
@router.get(
    "/workbench/session-version-list",
    summary="Get all the Inspiration information for the current session",
    response_model=UnifiedResponseModel,
)
async def get_linsight_session_version_list(
    session_id: str = Query(..., description="SessionsID"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    share_link: Union["ShareLink", None] = Depends(header_share_token_parser),
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
        if (
            share_link is None
            or share_link.meta_data is None
            or share_link.meta_data.get("versionId") not in session_version_ids
        ):
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
    share_link: Union["ShareLink", None] = Depends(header_share_token_parser),
) -> UnifiedResponseModel:
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
        if (
            share_link is None
            or share_link.meta_data is None
            or share_link.meta_data.get("versionId") != session_version_id
        ):
            return UnAuthorizedError.return_resp()

    return resp_200(execute_task_models)


# Creating an Idea Task Message Flow websocket
@router.websocket("/workbench/task-message-stream", name="task_message_stream")
async def task_message_stream(
    websocket: WebSocket,
    session_version_id: str = Query(..., description="Inspiration Conversation VersionID"),
    login_user: UserPayload = Depends(UserPayload.get_login_user_from_ws),
):
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

        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
            trace_id=trace_id_var.get(),
            event_data=ApplicationAliveEventData(
                app_id=ApplicationTypeEnum.LINSIGHT.value,
                app_name=ApplicationTypeEnum.LINSIGHT.value,
                app_type=ApplicationTypeEnum.LINSIGHT,
                chat_id=session_version_info.session_id if session_version_info else "",
                start_time=int(start_time),
                end_time=int(end_time),
            ),
        )
        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
            trace_id=trace_id_var.get(),
            event_data=ApplicationProcessEventData(
                app_id=ApplicationTypeEnum.LINSIGHT.value,
                app_name=ApplicationTypeEnum.LINSIGHT.value,
                app_type=ApplicationTypeEnum.LINSIGHT,
                chat_id=session_version_info.session_id if session_version_info else "",
                start_time=int(start_time),
                end_time=int(end_time),
                process_time=int((end_time - start_time) * 1000),
            ),
        )


# Batch Download Task Files
@router.post("/workbench/batch-download-files", summary="Batch Download Task Files")
async def batch_download_files(
    zip_name: str = Body(..., description="Package name"),
    file_info_list: list[DownloadFilesSchema] = Body(..., description="File Information List"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
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
            headers={"Content-Disposition": f"attachment; filename={zip_name}"},
        )
    except Exception as e:
        logger.error(f"Failed to download file in bulk: {e!s}")
        return ResourceDownloadError.return_resp(data=str(e))


# Get Queue Queue Status
@router.get("/workbench/queue-status", summary="Get Ideas Queue Queue Status", response_model=UnifiedResponseModel)
async def get_queue_status(
    session_version_id: str = Query(..., description="Inspiration Conversation VersionID"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    """
    Get Ideas Queue Queue Status
    :param session_version_id:
    :param login_user:
    :return:
    """
    from bisheng.linsight.worker import LinsightQueue

    redis_client = await get_redis_client()
    queue = LinsightQueue("queue", namespace="linsight", redis=redis_client)
    try:
        index = await queue.index(session_version_id)
        return resp_200(data={"index": index}, message="Get Ideas queue queue status successfully")
    except Exception as e:
        logger.error(f"Failed to get Ideas queue queue status: {e!s}")
        return LinsightQueueStatusError.return_resp(data=str(e))


# InspirationmdTransferpdf or docx Mengunduh
@router.post("/workbench/download-md-to-pdf-or-docx", summary="InspirationmdTransferpdf or docx Mengunduh")
async def download_md_to_pdf_or_docx(
    file_info: DownloadFilesSchema = Body(..., description="File information"),
    to_type: Literal["pdf", "docx"] = Body(..., description="the target file type of the conversion,pdfORdocx"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
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

        md_str = file_bytes.decode("utf-8")

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
            headers={"Content-Disposition": f"attachment; filename={file_name}"},
        )
    except Exception as e:
        logger.error(f"This content failed to load: {e!s}")
        return ResourceDownloadError.return_resp(data=str(e))


@router.post("/sop/add", summary="Add InspirationSOP", response_model=UnifiedResponseModel)
async def add_sop(
    sop_obj: SOPManagementSchema = Body(..., description="SOPObjects"),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    """
    Add InspirationSOP
    :return:
    """
    with strict_tenant_filter():
        return await SOPManageService.add_sop(sop_obj, user_id=login_user.user_id)


@router.post("/sop/update", summary="Update IdeasSOP", response_model=UnifiedResponseModel)
async def update_sop(
    sop_obj: SOPManagementUpdateSchema = Body(..., description="SOPObjects"),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    """
    Update IdeasSOP
    :return:
    """
    sop_obj.user_id = login_user.user_id
    with strict_tenant_filter():
        return await SOPManageService.update_sop(sop_obj, update_version_id=False)


@router.get("/sop/list", summary="Get IdeasSOPVertical", response_model=UnifiedResponseModel)
async def get_sop_list(
    keywords: str = Query(None, description="Keywords Search"),
    showcase: bool = Query(None, description="Get featured cases only?"),
    page: int = Query(1, ge=1, description="Page"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    sort: Literal["asc", "desc"] = Query("desc", description="Sort ByascORdesc"),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    """
    Get IdeasSOPVertical
    :return:
    """

    with strict_tenant_filter():
        sop_pages = await SOPManageService.get_sop_list(
            keywords=keywords, showcase=showcase, page=page, page_size=page_size, sort=sort
        )
    return resp_200(data=sop_pages)


@router.get("/sop/record", summary="Get IdeasSOPRecord", response_model=UnifiedResponseModel)
async def get_sop_record(
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
    keyword: str = Query(None, description="Search keyword ..."),
    sort: str = Query(default="desc", description="Sort ByascORdesc"),
    page: int = Query(1, ge=1, description="Page"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
):
    with strict_tenant_filter():
        res, count = await SOPManageService.get_sop_record(keyword, sort, page, page_size)
    return resp_200(PageList(total=count, list=res))


@router.post("/sop/record/sync", summary="SynchronoussopRecord toSOPGallery", response_model=UnifiedResponseModel)
async def sync_sop_record(
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
    record_ids: list[int] = Body(..., description="sopThe only one in the record sheetid"),
    override: bool | None = Body(default=False, description="Force override or not"),
    save_new: bool | None = Body(default=False, description="Do you want to save as newsop"),
) -> UnifiedResponseModel:
    """
    SynchronousSOP"Log to"SOPGallery
    """
    with strict_tenant_filter():
        repeat_name = await SOPManageService.sync_sop_record(record_ids, override, save_new)
    return resp_200(
        data={
            "repeat_name": repeat_name,
        },
        message="success",
    )


@router.post("/sop/upload", summary="Batch importSOPWarehousing", response_model=UnifiedResponseModel)
async def upload_sop_file(
    file: UploadFile = File(..., description="Uploaded bySOPDoc."),
    override: bool | None = Body(default=False, description="Force override or not"),
    save_new: bool | None = Body(default=False, description="Do you want to save as newsop"),
    ignore_error: bool | None = Body(default=False, description="Whether to ignore the file and find the wrong record"),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    """
    Batch importSOPWarehousing
    """

    try:
        with strict_tenant_filter():
            success_rows, error_rows, repeat_rows = await SOPManageService.upload_sop_file(
                login_user,
                file,
                ignore_error,
                override,
                save_new,
            )

        return resp_200(
            data={
                "success_rows": success_rows,
                "error_rows": error_rows,
                "repeat_rows": repeat_rows,
            }
        )
    except Exception as e:
        raise e
    finally:
        await file.close()


@router.delete("/sop/remove", summary="Delete IdeasSOP", response_model=UnifiedResponseModel)
async def remove_sop(
    sop_ids: list[int] = Body(..., description="SOPUniqueness quantificationIDVertical", embed=True),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    """
    Delete IdeasSOP
    :return:
    """

    with strict_tenant_filter():
        return await SOPManageService.remove_sop(sop_ids, login_user)


@router.get("/sop/showcase", summary="InspirationsopLibrary's Featured Cases", response_model=UnifiedResponseModel)
async def get_sop_banner(
    page: int = Query(1, ge=1, description="Page"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    sort: Literal["asc", "desc"] = Query("desc", description="Sort ByascORdesc"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    """
    Set or cancel IdeasSOPLibrary's Featured Cases
    :return:
    """
    sop_pages = await SOPManageService.get_sop_list(showcase=True, page=page, page_size=page_size, sort=sort)
    return resp_200(data=sop_pages)


@router.post(
    "/sop/showcase", summary="Set or unset a featured case for Inspirations", response_model=UnifiedResponseModel
)
async def set_sop_banner(
    sop_id: int = Body(..., description="SOPUniqueness quantificationID"),
    showcase: bool = Body(..., description="Set as featured case or not"),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    """
    Set or cancel IdeasSOPLibrary's Featured Cases
    :return:
    """
    # CorrectionSOPpresence or does it
    with strict_tenant_filter():
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


@router.get(
    "/sop/showcase/result",
    summary="Obtain the results of the execution of the selected cases of Lingsi",
    response_model=UnifiedResponseModel,
)
async def get_sop_showcase_result(
    sop_id: int = Query(None, description="SOPUniqueness quantificationID"),
    linsight_version_id: str = Query(None, description="Inspiration Conversation VersionID, use this parameter first"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
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
        return resp_200(data={"version_info": None, "execute_tasks": []})
    execute_task_models = await LinsightWorkbenchImpl.get_execute_task_detail(linsight_version_id)
    return resp_200(data={"version_info": version_info, "execute_tasks": execute_task_models})
