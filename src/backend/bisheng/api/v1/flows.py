import json
from typing import Any
from uuid import UUID

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.errcode.flow import FlowOnlineEditError
from bisheng.api.services.flow import FlowService
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.utils import build_flow_no_yield, get_L2_param_from_flow, remove_api_keys
from bisheng.api.v1.schemas import (FlowCompareReq, FlowListRead, FlowVersionCreate, StreamData,
                                    UnifiedResponseModel, resp_200)
from bisheng.database.base import session_getter
from bisheng.database.models.flow import (Flow, FlowCreate, FlowDao, FlowRead, FlowReadWithStyle, FlowType,
                                          FlowUpdate)
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.role_access import AccessType
from bisheng.settings import settings
from bisheng.utils.logger import logger
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi_jwt_auth import AuthJWT
from sqlmodel import select
from starlette.responses import StreamingResponse

# build router
router = APIRouter(prefix='/flows', tags=['Flows'], dependencies=[Depends(get_login_user)])


@router.post('/', status_code=201)
def create_flow(*, request: Request, flow: FlowCreate, login_user: UserPayload = Depends(get_login_user)):
    """Create a new flow."""
    # 判断用户是否重复技能名
    with session_getter() as session:
        if session.exec(
                select(Flow).where(Flow.name == flow.name,
                                   Flow.user_id == login_user.user_id)).first():
            raise HTTPException(status_code=500, detail='技能名重复')
    flow.user_id = login_user.user_id
    db_flow = Flow.model_validate(flow)
    # 创建新的技能
    db_flow = FlowDao.create_flow(db_flow,FlowType.FLOW.value)

    current_version = FlowVersionDao.get_version_by_flow(db_flow.id.hex)
    ret = FlowRead.model_validate(db_flow)
    ret.version_id = current_version.id
    FlowService.create_flow_hook(request, login_user, db_flow, ret.version_id)
    return resp_200(data=ret)


@router.get('/versions', status_code=200)
def get_versions(*, flow_id: UUID, Authorize: AuthJWT = Depends()):
    """
    获取技能对应的版本列表
    """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    flow_id = flow_id.hex
    return FlowService.get_version_list_by_flow(user, flow_id)


@router.post('/versions', status_code=200)
def create_versions(*,
                    flow_id: UUID,
                    flow_version: FlowVersionCreate,
                    Authorize: AuthJWT = Depends()):
    """
    创建新的技能版本
    """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    flow_id = flow_id.hex
    return FlowService.create_new_version(user, flow_id, flow_version)


@router.put('/versions/{version_id}', status_code=200)
def update_versions(*,
                    request: Request,
                    version_id: int,
                    flow_version: FlowVersionCreate,
                    login_user: UserPayload = Depends(get_login_user)):
    """
    更新版本
    """
    return FlowService.update_version_info(request, login_user, version_id, flow_version)


@router.delete('/versions/{version_id}', status_code=200)
def delete_versions(*, version_id: int, Authorize: AuthJWT = Depends()):
    """
    删除版本
    """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    return FlowService.delete_version(user, version_id)


@router.get('/versions/{version_id}', status_code=200)
def get_version_info(*, version_id: int, Authorize: AuthJWT = Depends()):
    """
    获取版本信息
    """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    return FlowService.get_version_info(user, version_id)


@router.post('/change_version', status_code=200)
def change_version(*,
                   request: Request,
                   flow_id: UUID = Query(default=None, description='技能唯一ID'),
                   version_id: int = Query(default=None, description='需要设置的当前版本ID'),
                   login_user: UserPayload = Depends(get_login_user)):
    """
    修改当前版本
    """
    flow_id = flow_id.hex
    return FlowService.change_current_version(request, login_user, flow_id, version_id)


@router.get('/', status_code=200)
def read_flows(*,
               name: str = Query(default=None, description='根据name查找数据库，包含描述的模糊搜索'),
               tag_id: int = Query(default=None, description='标签ID'),
               page_size: int = Query(default=10, description='每页数量'),
               page_num: int = Query(default=1, description='页数'),
               status: int = None,
               Authorize: AuthJWT = Depends()):
    """Read all flows."""
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    try:
        return FlowService.get_all_flows(user, name, status, tag_id, page_num, page_size)
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get('/{flow_id}', response_model=UnifiedResponseModel[FlowReadWithStyle], status_code=200)
def read_flow(*, flow_id: UUID, login_user: UserPayload = Depends(get_login_user)):
    """Read a flow."""
    return FlowService.get_one_flow(login_user, flow_id.hex)


@router.patch('/{flow_id}', response_model=UnifiedResponseModel[FlowRead], status_code=200)
async def update_flow(*,
                      request: Request,
                      flow_id: UUID,
                      flow: FlowUpdate,
                      login_user: UserPayload = Depends(get_login_user)):
    """Update a flow."""
    flow_id = flow_id.hex
    with session_getter() as session:
        db_flow = session.get(Flow, flow_id)
    if not db_flow:
        raise HTTPException(status_code=404, detail='Flow not found')

    if not login_user.access_check(db_flow.user_id, flow_id, AccessType.FLOW_WRITE):
        return UnAuthorizedError.return_resp()

    flow_data = flow.model_dump(exclude_unset=True)

    if 'status' in flow_data and flow_data['status'] == 2 and db_flow.status == 1:
        # 上线校验
        try:
            art = {}
            await build_flow_no_yield(graph_data=db_flow.data,
                                      artifacts=art,
                                      process_file=False,
                                      flow_id=flow_id)
        except Exception as exc:
            logger.exception(exc)
            raise HTTPException(status_code=500, detail=f'Flow build error, {str(exc)}')

    if db_flow.status == 2 and ('status' not in flow_data or flow_data['status'] != 1):
        raise FlowOnlineEditError.http_exception()

    if settings.remove_api_keys:
        flow_data = remove_api_keys(flow_data)
    for key, value in flow_data.items():
        setattr(db_flow, key, value)
    with session_getter() as session:
        session.add(db_flow)
        session.commit()
        session.refresh(db_flow)
    try:
        if not get_L2_param_from_flow(db_flow.data, db_flow.id):
            logger.error(f'flow_id={db_flow.id} extract file_node fail')
    except Exception:
        pass
    FlowService.update_flow_hook(request, login_user, db_flow)
    return resp_200(db_flow)


@router.delete('/{flow_id}', status_code=200)
def delete_flow(*,
                request: Request,
                flow_id: UUID,
                login_user: UserPayload = Depends(get_login_user)):
    """Delete a flow."""

    db_flow = FlowDao.get_flow_by_id(flow_id.hex)
    if not db_flow:
        raise HTTPException(status_code=404, detail='Flow not found')
    if not login_user.access_check(db_flow.user_id, flow_id.hex, AccessType.FLOW_WRITE):
        return UnAuthorizedError.return_resp()
    FlowDao.delete_flow(db_flow)
    FlowService.delete_flow_hook(request, login_user, db_flow)
    return resp_200(message='删除成功')


@router.get('/download/', response_model=UnifiedResponseModel[FlowListRead], status_code=200)
async def download_file():
    """Download all flows as a file."""
    flows = read_flows()
    return resp_200(FlowListRead(flows=flows))


@router.post('/compare', response_model=UnifiedResponseModel, status_code=200)
async def compare_flow_node(*, item: FlowCompareReq, Authorize: AuthJWT = Depends()):
    """ 技能多版本对比 """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    return await FlowService.compare_flow_node(user, item)


@router.get('/compare/stream', status_code=200, response_class=StreamingResponse)
async def compare_flow_node_stream(*,
                                   data: Any = Query(description='对比所需数据的json序列化后的字符串'),
                                   Authorize: AuthJWT = Depends()):
    """ 技能多版本对比 """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    item = FlowCompareReq(**json.loads(data))

    async def event_stream(req: FlowCompareReq):
        yield str(StreamData(event='message', data={'type': 'start', 'data': 'start'}))
        try:
            async for one in FlowService.compare_flow_stream(user, req):
                yield one
            yield str(StreamData(event='message', data={'type': 'end', 'data': ''}))
        except Exception as e:
            logger.exception('compare flow stream error')
            yield str(StreamData(event='message', data={'type': 'end', 'message': str(e)}))

    try:
        return StreamingResponse(event_stream(item), media_type='text/event-stream')
    except Exception as exc:
        logger.error(exc)
        raise HTTPException(status_code=500, detail=str(exc))
