import time
from typing import Optional, Union

from fastapi import APIRouter, Body, Depends, Query, WebSocket, WebSocketException, Request, \
    status as http_status
from loguru import logger
from sqlmodel import select

from bisheng.api.services.flow import FlowService
from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schemas import FlowVersionCreate, resp_200
from bisheng.chat.types import WorkType
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import WorkflowNameExistsError, WorkFlowOnlineEditError, AppWriteAuthError
from bisheng.common.errcode.http_error import UnAuthorizedError, NotFoundError
from bisheng.common.services import telemetry_service
from bisheng.core.database import get_sync_db_session
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import Flow, FlowCreate, FlowDao, FlowRead, FlowType, FlowUpdate, \
    FlowStatus
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.role_access import AccessType
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.utils import generate_uuid
from bisheng_langchain.utils.requests import Requests

router = APIRouter(prefix='/workflow', tags=['Workflow'])


@router.get("/write/auth")
async def check_app_write_auth(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        flow_id: str = Query(..., description="ApplicationsID"),
        flow_type: int = Query(..., description="Apply type")
):
    """ Check if the user has administrative rights to the app """
    check_auth_type = AccessType.FLOW_WRITE
    if flow_type == FlowType.ASSISTANT.value:
        check_auth_type = AccessType.ASSISTANT_WRITE
        flow_info = await AssistantDao.aget_one_assistant(flow_id)
    else:
        flow_info = await FlowDao.aget_flow_by_id(flow_id)
        if flow_info and flow_info.flow_type == FlowType.WORKFLOW.value:
            check_auth_type = AccessType.WORKFLOW_WRITE
    if not flow_info:
        raise NotFoundError.http_exception()
    owner_id = flow_info.user_id
    if await login_user.async_access_check(owner_id, flow_id, check_auth_type):
        return resp_200()
    return AppWriteAuthError.return_resp()


@router.get("/report/file")
async def get_report_file(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        version_key: str = Query("", description="minioright of privacyobject_name"),
        workflow_id: str = Query(..., description="The WorkflowID")
):
    """ DapatkanreportTemplate file for the node """

    # Check if the user has read access to the app
    flow_info = await FlowDao.aget_flow_by_id(workflow_id)
    if not flow_info:
        raise NotFoundError.http_exception()
    if not await login_user.async_access_check(flow_info.user_id, workflow_id, AccessType.WORKFLOW):
        return UnAuthorizedError.return_resp()

    if not version_key:
        #  Regenerate aversion_key
        version_key = generate_uuid()
    else:
        version_key = version_key.split('_', 1)[0]
    file_url = ""
    object_name = f"workflow/report/{version_key}.docx"
    minio_client = await get_minio_storage()
    if await minio_client.object_exists(minio_client.bucket, object_name):
        file_url = await minio_client.get_share_link(object_name, clear_host=False)

    return resp_200(data={
        'url': file_url,
        'version_key': f'{version_key}_{int(time.time() * 1000)}',
    })


@router.post('/report/copy', status_code=200)
async def copy_report_file(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        version_key: str = Body(..., embed=True, description="minioright of privacyobject_name")):
    """ SalinreportTemplate file for the node """
    version_key = version_key.split('_', 1)[0]
    new_version_key = generate_uuid()
    object_name = f"workflow/report/{version_key}.docx"
    new_object_name = f"workflow/report/{new_version_key}.docx"
    minio_client = await get_minio_storage()
    if await minio_client.object_exists(minio_client.bucket, object_name):
        await minio_client.copy_object(source_object=object_name, dest_object=new_object_name,
                                       source_bucket=minio_client.bucket, dest_bucket=minio_client.bucket)
    return resp_200(data={
        'version_key': f'{new_version_key}',
    })


@router.post('/report/callback', status_code=200)
async def upload_report_file(
        request: Request,
        data: dict = Body(...)):
    """ office Callback interface save reportTemplate file for the node """
    status = data.get('status')
    file_url = data.get('url')
    key = data.get('key')
    logger.debug(f'callback={data}')
    if status not in {2, 6}:
        # Non-saved callbacks are not processed
        return {'error': 0}
    logger.info(f'office_callback url={file_url}')
    file = Requests().get(url=file_url)
    version_key = key.split('_', 1)[0]

    minio_client = await get_minio_storage()
    object_name = f"workflow/report/{version_key}.docx"
    await minio_client.put_object(
        object_name=object_name, file=file._content, bucket_name=minio_client.bucket,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return {'error': 0}


@router.post('/run_once', status_code=200)
def run_once(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
             node_input: Optional[dict] = None,  # Input parameters of the node
             node_data: dict = None,
             workflow_id: str = Body(..., description='The WorkflowID')):
    """ Single node operation """
    result = WorkFlowService.run_once(login_user, node_input, node_data, workflow_id)

    return resp_200(data=result)


@router.websocket('/chat/{workflow_id}')
async def workflow_ws(*,
                      workflow_id: str,
                      websocket: WebSocket,
                      chat_id: Optional[str] = None,
                      login_user: UserPayload = Depends(UserPayload.get_login_user_from_ws)):
    try:
        await chat_manager.dispatch_client(websocket, workflow_id, chat_id, login_user, WorkType.WORKFLOW, websocket)
    except WebSocketException as exc:
        logger.error(f'Websocket exception: {str(exc)}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))


@router.post('/create', status_code=201)
def create_flow(*, request: Request, flow: FlowCreate, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Create a new flow."""
    # Determine if the user repeats the skill name
    with get_sync_db_session() as session:
        if session.exec(
                select(Flow).where(Flow.name == flow.name, Flow.flow_type == FlowType.WORKFLOW.value,
                                   Flow.user_id == login_user.user_id)).first():
            raise WorkflowNameExistsError.http_exception()
    flow.user_id = login_user.user_id
    db_flow = Flow.model_validate(flow)
    db_flow.create_time = None
    db_flow.update_time = None
    db_flow.flow_type = FlowType.WORKFLOW.value
    # Create New Skill
    db_flow = FlowDao.create_flow(db_flow, FlowType.WORKFLOW.value)

    current_version = FlowVersionDao.get_version_by_flow(db_flow.id)
    ret = FlowRead.model_validate(db_flow)
    ret.version_id = current_version.id
    FlowService.create_flow_hook(request, login_user, db_flow, ret.version_id, FlowType.WORKFLOW.value)
    return resp_200(data=ret)


@router.get('/versions', status_code=200)
def get_versions(*, flow_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get a list of versions for your skill
    """
    return FlowService.get_version_list_by_flow(login_user, flow_id)


@router.post('/versions', status_code=200)
async def create_versions(*,
                          flow_id: str,
                          flow_version: FlowVersionCreate,
                          login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Create New Skill Version
    """
    flow_version.flow_type = FlowType.WORKFLOW.value
    return await FlowService.create_new_version(login_user, flow_id, flow_version)


@router.put('/versions/{version_id}', status_code=200)
async def update_versions(*,
                          request: Request,
                          version_id: int,
                          flow_version: FlowVersionCreate,
                          login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Update to version
    """
    return await FlowService.update_version_info(request, login_user, version_id, flow_version)


@router.delete('/versions/{version_id}', status_code=200)
def delete_versions(*, version_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Remove Version
    """
    return FlowService.delete_version(login_user, version_id)


@router.get('/versions/{version_id}', status_code=200)
def get_version_info(*, version_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get Version Info
    """
    return FlowService.get_version_info(login_user, version_id)


@router.post('/change_version', status_code=200)
def change_version(*,
                   request: Request,
                   flow_id: str = Query(default=None, description='Skill UniqueID'),
                   version_id: int = Query(default=None, description='Current version that needs to be setID'),
                   login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Modify Current Version
    """
    return FlowService.change_current_version(request, login_user, flow_id, version_id)


@router.get('/get_one_flow/{flow_id}')
async def read_flow(*, flow_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user),
                    share_link: Union['ShareLink', None] = Depends(header_share_token_parser)):
    """Read a flow."""
    return await FlowService.get_one_flow(login_user, flow_id, share_link)


@router.patch('/update/{flow_id}')
async def update_flow(*,
                      request: Request,
                      flow_id: str,
                      flow: FlowUpdate,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """online offline"""
    db_flow = await FlowDao.aget_flow_by_id(flow_id)
    if not db_flow:
        raise NotFoundError()

    if not await login_user.async_access_check(db_flow.user_id, flow_id, AccessType.WORKFLOW_WRITE):
        return UnAuthorizedError.return_resp()

    flow_data = flow.model_dump(exclude_unset=True)

    if db_flow.status == FlowStatus.ONLINE.value and (
            'status' not in flow_data or flow_data['status'] != FlowStatus.OFFLINE.value):
        raise WorkFlowOnlineEditError.http_exception()

    for key, value in flow_data.items():
        if key in ['data', 'create_time', 'update_time']:
            continue
        if key == "logo" and not value:
            continue
        setattr(db_flow, key, value)
    db_flow = await FlowDao.aupdate_flow(db_flow)
    await telemetry_service.log_event(
        user_id=login_user.user_id,
        event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION,
        trace_id=trace_id_var.get()
    )
    await FlowService.update_flow_hook(request, login_user, db_flow)
    return resp_200(db_flow)


@router.patch('/status')
async def update_flow_status(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                             flow_id: str = Body(..., description='SkillID'),
                             version_id: int = Body(..., description='VersionID'),
                             status: int = Body(..., description='Status')):
    await WorkFlowService.update_flow_status(login_user, flow_id, version_id, status)
    return resp_200()


@router.get('/list', status_code=200)
def read_flows(*,
               login_user: UserPayload = Depends(UserPayload.get_login_user),
               name: str = Query(default=None, description='accordingnameFind databases with fuzzy searches for descriptions'),
               tag_id: int = Query(default=None, description='labelID'),
               flow_type: int = Query(default=None, description='Type 1 flow 5 assitant 10 workflow '),
               page_size: int = Query(default=10, description='Items per page'),
               page_num: int = Query(default=1, description='Page'),
               status: int = None,
               managed: bool = Query(default=False, description='Whether to query the list of apps with administrative permissions')):
    """Read all flows."""
    data, total = WorkFlowService.get_all_flows(login_user, name, status, tag_id, flow_type, page_num, page_size,
                                                managed)
    return resp_200(data={
        'data': data,
        'total': total
    })
