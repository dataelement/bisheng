import json
from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from starlette.responses import StreamingResponse

from bisheng.api.services.flow import FlowService
from bisheng.api.utils import build_flow_no_yield, remove_api_keys
from bisheng.api.v1.schemas import (FlowCompareReq, FlowVersionCreate, StreamData, resp_200)
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import FlowOnlineEditError, FlowNameExistsError
from bisheng.common.errcode.http_error import UnAuthorizedError, ServerError, NotFoundError
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.database import get_async_db_session
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import (Flow, FlowCreate, FlowDao, FlowRead, FlowType, FlowUpdate)
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.role_access import AccessType
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink

# build router
router = APIRouter(prefix='/flows', tags=['Flows'], dependencies=[Depends(UserPayload.get_login_user)])


@router.post('/', status_code=201)
def create_flow(*, request: Request, flow: FlowCreate, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Create a new flow."""
    # Determine if the user repeats the skill name
    exist_flow = FlowDao.get_flow_by_name(login_user.user_id, flow.name)
    if exist_flow:
        raise FlowNameExistsError()
    flow.user_id = login_user.user_id
    db_flow = Flow.model_validate(flow)
    # Create New Skill
    db_flow = FlowDao.create_flow(db_flow, FlowType.FLOW.value)

    current_version = FlowVersionDao.get_version_by_flow(db_flow.id)
    ret = FlowRead.model_validate(db_flow)
    ret.version_id = current_version.id
    FlowService.create_flow_hook(request, login_user, db_flow, ret.version_id)
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
async def change_version(*,
                         request: Request,
                         flow_id: str = Query(default=None, description='Skill UniqueID'),
                         version_id: int = Query(default=None, description='Current version that needs to be setID'),
                         login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Modify Current Version
    """
    return await FlowService.change_current_version(request, login_user, flow_id, version_id)


@router.get('/', status_code=200)
def read_flows(*,
               name: str = Query(default=None, description='accordingnameFind databases with fuzzy searches for descriptions'),
               tag_id: int = Query(default=None, description='labelID'),
               page_size: int = Query(default=10, description='Items per page'),
               page_num: int = Query(default=1, description='Page'),
               status: int = None,
               login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Read all flows."""
    return FlowService.get_all_flows(login_user, name, status, tag_id, page_num, page_size)


@router.get('/{flow_id}')
async def read_flow(*, flow_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user),
                    share_link: Union['ShareLink', None] = Depends(header_share_token_parser)):
    """Read a flow."""
    return await FlowService.get_one_flow(login_user, flow_id, share_link)


@router.patch('/{flow_id}')
async def update_flow(*,
                      request: Request,
                      flow_id: str,
                      flow: FlowUpdate,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Update a flow."""
    db_flow = await FlowDao.aget_flow_by_id(flow_id)
    if not db_flow:
        raise HTTPException(status_code=404, detail='Flow not found')

    if not await login_user.async_access_check(db_flow.user_id, flow_id, AccessType.FLOW_WRITE):
        return UnAuthorizedError.return_resp()

    flow_data = flow.model_dump(exclude_unset=True)

    if 'status' in flow_data and flow_data['status'] == 2 and db_flow.status == 1:
        # On-line verification
        try:
            art = {}
            await build_flow_no_yield(graph_data=db_flow.data,
                                      artifacts=art,
                                      process_file=False,
                                      flow_id=flow_id)
        except Exception as exc:
            logger.exception(exc)
            raise ServerError(exception=exc)

    if db_flow.status == 2 and ('status' not in flow_data or flow_data['status'] != 1):
        raise FlowOnlineEditError.http_exception()

    if settings.remove_api_keys:
        flow_data = remove_api_keys(flow_data)
    for key, value in flow_data.items():
        if key in ['data', 'create_time', 'update_time']:
            continue
        if key == 'logo' and not value:
            continue
        setattr(db_flow, key, value)
    async with get_async_db_session() as session:
        session.add(db_flow)
        await session.commit()
        await session.refresh(db_flow)
    await FlowService.update_flow_hook(request, login_user, db_flow)
    return resp_200(db_flow)


@router.delete('/{flow_id}', status_code=200)
def delete_flow(*,
                request: Request,
                flow_id: str,
                login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Delete a flow."""

    db_flow = FlowDao.get_flow_by_id(flow_id)
    if not db_flow:
        raise NotFoundError()
    access_type = AccessType.FLOW_WRITE
    if db_flow.flow_type == FlowType.WORKFLOW.value:
        access_type = AccessType.WORKFLOW_WRITE
    if not login_user.access_check(db_flow.user_id, flow_id, access_type):
        return UnAuthorizedError.return_resp()
    FlowDao.delete_flow(db_flow)
    telemetry_service.log_event_sync(
        user_id=login_user.user_id,
        event_type=BaseTelemetryTypeEnum.DELETE_APPLICATION,
        trace_id=trace_id_var.get()
    )
    FlowService.delete_flow_hook(request, login_user, db_flow)
    return resp_200()


@router.post('/compare')
async def compare_flow_node(*, item: FlowCompareReq, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Skills Multiple Versions Comparison """
    return await FlowService.compare_flow_node(login_user, item)


@router.get('/compare/stream', status_code=200, response_class=StreamingResponse)
async def compare_flow_node_stream(*,
                                   data: Any = Query(description='Comparing the required datajsonSerialized string'),
                                   login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Skills Multiple Versions Comparison """
    item = FlowCompareReq(**json.loads(data))

    async def event_stream(req: FlowCompareReq):
        yield str(StreamData(event='message', data={'type': 'start', 'data': 'start'}))
        try:
            async for one in FlowService.compare_flow_stream(login_user, req):
                yield one
            yield str(StreamData(event='message', data={'type': 'end', 'data': ''}))
        except Exception as e:
            logger.exception('compare flow stream error')
            yield ServerError(exception=e).to_sse_event_instance_str()

    try:
        return StreamingResponse(event_stream(item), media_type='text/event-stream')
    except Exception as exc:
        logger.error(exc)
        raise ServerError()
