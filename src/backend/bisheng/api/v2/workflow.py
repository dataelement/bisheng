import uuid
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Request, Body, Path, WebSocket, WebSocketException
from fastapi import status as http_status
from fastapi.responses import ORJSONResponse
from loguru import logger
from starlette.responses import StreamingResponse

from fastapi import APIRouter, Request, Body, UploadFile, File, Path, WebSocket, WebSocketException, status as http_status
from loguru import logger

from bisheng.api.errcode.base import NotFoundError
from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schema.workflow import WorkflowStream, WorkflowEvent, WorkflowEventType
from bisheng.api.v1.schemas import resp_200
from bisheng.api.v2.utils import get_default_operator
from bisheng.chat.types import WorkType
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.worker.workflow.tasks import execute_workflow, continue_workflow
from bisheng.workflow.common.workflow import WorkflowStatus

router = APIRouter(prefix='/workflow', tags=['OpenAPI', 'Workflow'])


@router.post('/invoke')
async def invoke_workflow(request: Request,
                          workflow_id: UUID = Body(..., description='工作流唯一ID'),
                          stream: Optional[bool] = Body(default=True, description='是否流式调用'),
                          user_input: Optional[dict] = Body(default=None, description='用户输入', alias='input'),
                          message_id: Optional[int] = Body(default=None, description='消息ID'),
                          session_id: Optional[str] = Body(default=None,
                                                           description='会话ID,一次workflow调用的唯一标识')):
    login_user = get_default_operator()
    workflow_id = workflow_id.hex

    # 解析出chat_id和unique_id
    if not session_id:
        chat_id = uuid.uuid4().hex
        unique_id = f'{chat_id}_async_task_id'
        session_id = unique_id
    else:
        chat_id = session_id.split('_', 1)[0]
        unique_id = session_id
    logger.debug(f'invoke_workflow: {workflow_id}, {session_id}')
    workflow = RedisCallback(unique_id, workflow_id, chat_id, str(login_user.user_id))

    # 查询工作流信息
    workflow_info = FlowDao.get_flow_by_id(workflow_id)
    if not workflow_info:
        raise NotFoundError.http_exception()
    if workflow_info.flow_type != FlowType.WORKFLOW.value:
        raise NotFoundError.http_exception()

    # 查询工作流状态
    status_info = workflow.get_workflow_status()
    if not status_info:
        # 初始化工作流
        workflow.set_workflow_data(workflow_info.data)
        workflow.set_workflow_status(WorkflowStatus.WAITING.value)
        # 发起异步任务
        execute_workflow.delay(unique_id, workflow_id, chat_id, str(login_user.user_id))
    else:
        # 设置用户的输入
        if status_info['status'] == WorkflowStatus.INPUT.value and user_input:
            workflow.set_user_input(user_input, message_id)
            workflow.set_workflow_status(WorkflowStatus.INPUT_OVER.value)
            continue_workflow.delay(unique_id, workflow_id, chat_id, str(login_user.user_id))

    logger.debug(f'waiting workflow over or input: {workflow_id}, {session_id}')

    async def handle_workflow_event(event_list: List):
        async for event in workflow.get_response_until_break():
            if event.category == WorkflowEventType.NodeRun.value:
                continue
            logger.debug(f'handle_workflow_event workflow event: {event}')
            # 非流式请求，过滤掉节点产生的流式输出事件
            if not stream and event.category == WorkflowEventType.StreamMsg.value and event.type == 'stream':
                continue
            workflow_stream = WorkflowStream(session_id=session_id,
                                             data=WorkFlowService.convert_chat_response_to_workflow_event(event))
            event_list.append(workflow_stream.data)
            yield f'data: {workflow_stream.model_dump_json()}\n\n'
        tmp_status_info = workflow.get_workflow_status()
        if tmp_status_info['status'] in [WorkflowStatus.SUCCESS.value, WorkflowStatus.FAILED.value]:
            workflow.clear_workflow_status()
        if tmp_status_info['status'] == WorkflowStatus.SUCCESS.value:
            workflow_stream = WorkflowStream(session_id=session_id,
                                             data=WorkflowEvent(event=WorkflowEventType.Close.value))
            event_list.append(workflow_stream.data)
            yield f'data: {workflow_stream.model_dump_json()}\n\n'

    res = []
    # 非流式返回累计的事件列表
    if not stream:
        async for _ in handle_workflow_event(res):
            pass
        return resp_200(data={
            'session_id': session_id,
            'events': res
        })
    try:
        return StreamingResponse(handle_workflow_event(res), media_type='text/event-stream')
    except Exception as exc:
        logger.exception(f'invoke_workflow error: {str(exc)}')
        return ORJSONResponse(status_code=500, content=str(exc))

@router.post('/stop')
async def stop_workflow(request: Request,
                        workflow_id: UUID = Body(..., description='工作流唯一ID'),
                        session_id: str = Body(description='会话ID,一次workflow调用的唯一标识')):
    workflow_id = workflow_id.hex
    login_user = get_default_operator()
    chat_id = session_id.split('_', 1)[0]
    unique_id = session_id
    workflow = RedisCallback(unique_id, workflow_id, chat_id, str(login_user.user_id))
    workflow.set_workflow_stop()
    return resp_200()


@router.post('/stop')
async def stop_workflow(request: Request,
                        workflow_id: UUID = Body(..., description='工作流唯一ID'),
                        session_id: str = Body(description='会话ID,一次workflow调用的唯一标识')):
    workflow_id = workflow_id.hex
    login_user = get_default_operator()
    chat_id = session_id.split('_', 1)[0]
    unique_id = session_id
    workflow = RedisCallback(unique_id, workflow_id, chat_id, str(login_user.user_id))
    workflow.set_workflow_stop()
    return resp_200()


@router.websocket('/chat/{workflow_id}')
async def workflow_ws(*,
                      workflow_id: UUID = Path(..., description='工作流唯一ID'),
                      websocket: WebSocket,
                      chat_id: Optional[str] = None):
    """ 免登录链接使用 """
    try:
        workflow_id = workflow_id.hex
        # Authorize.jwt_required(auth_from='websocket', websocket=websocket)
        # payload = Authorize.get_jwt_subject()
        login_user = get_default_operator()
        await chat_manager.dispatch_client(websocket, workflow_id, chat_id, login_user, WorkType.WORKFLOW, websocket)
    except WebSocketException as exc:
        logger.error(f'Websocket exception: {str(exc)}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
    except Exception as e:
        logger.error(f'Websocket handle error: {str(e)}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(e))


@router.post('/input/file', status_code=200)
async def process_input_file(request: Request, file: UploadFile = File(...)):
    """ 处理对话框的文件上传, 将文件解析为对应的chunk """
    login_user = get_default_operator()
    res = await WorkFlowService.process_input_file(login_user, file)
    return resp_200(data=res)
