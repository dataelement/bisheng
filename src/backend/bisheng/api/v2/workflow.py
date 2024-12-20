import uuid

from fastapi import APIRouter, Request, Body

from bisheng.api.errcode.base import NotFoundError
from bisheng.api.v2.utils import get_default_operator
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.worker.workflow.tasks import execute_workflow

router = APIRouter(prefix='/workflow', tags=['OpenAPI', 'Workflow'])


@router.post('/invoke')
async def invoke_workflow(request: Request,
                          workflow_id: str = Body(..., description='工作流唯一ID'),
                          stream: bool = Body(default=False, description='是否流式调用'),
                          user_input: dict = Body(default=None, description='用户输入'),
                          session_id: str = Body(default=None, description='会话ID,一次workflow调用的唯一标识')):
    workflow_info = FlowDao.get_flow_by_id(workflow_id)
    if not workflow_info:
        raise NotFoundError.http_exception()
    if workflow_info.flow_type != FlowType.WORKFLOW.value:
        raise NotFoundError.http_exception()

    login_user = get_default_operator()

    if not session_id:
        chat_id = str(uuid.uuid4())
        unique_id = f'{chat_id}_async_task_id'
    else:
        chat_id = session_id.split('_', 1)[0]
        unique_id = session_id
    workflow = RedisCallback(unique_id, workflow_id, chat_id, str(login_user.user_id))

    # 查询工作流状态
    status_info = workflow.get_workflow_status()
    if not status_info:
        # 初始化工作流
        workflow.set_workflow_data(workflow_info.data)
        workflow.set_workflow_status(WorkflowStatus.WAITING.value)
        # 发起异步任务
        execute_workflow.delay(unique_id, workflow_id, chat_id, str(login_user.user_id))


@router.websocket('/chat/{workflow_id}')
async def workflow_ws(*,
                      workflow_id: str,
                      websocket: WebSocket,
                      chat_id: Optional[str] = None):
    try:
        # Authorize.jwt_required(auth_from='websocket', websocket=websocket)
        # payload = Authorize.get_jwt_subject()
        login_user = get_default_operator()
        await chat_manager.dispatch_client(websocket, workflow_id, chat_id, login_user, WorkType.WORKFLOW, websocket)
    except WebSocketException as exc:
        logger.error(f'Websocket exception: {str(exc)}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
