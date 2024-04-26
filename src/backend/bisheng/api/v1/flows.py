import json
from typing import List
from uuid import UUID

from bisheng.api.services.Flow import FlowService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import (access_check, build_flow_no_yield, get_L2_param_from_flow,
                               remove_api_keys)
from bisheng.api.v1.schemas import FlowListCreate, FlowListRead, UnifiedResponseModel, resp_200, FlowVersionCreate
from bisheng.database.base import session_getter
from bisheng.database.models.flow import Flow, FlowCreate, FlowRead, FlowReadWithStyle, FlowUpdate, FlowDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user import User
from bisheng.settings import settings
from bisheng.utils.logger import logger
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import func, or_
from sqlmodel import select

# build router
router = APIRouter(prefix='/flows', tags=['Flows'])


@router.post('/', status_code=201)
def create_flow(*, flow: FlowCreate, Authorize: AuthJWT = Depends()):
    """Create a new flow."""
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    # 判断用户是否重复技能名
    with session_getter() as session:
        if session.exec(
                select(Flow).where(Flow.name == flow.name,
                                   Flow.user_id == payload.get('user_id'))).first():
            raise HTTPException(status_code=500, detail='技能名重复')
    flow.user_id = payload.get('user_id')
    db_flow = Flow.model_validate(flow)
    # 创建新的技能
    db_flow = FlowDao.create_flow(db_flow)
    return resp_200(data=FlowRead.model_validate(db_flow))


@router.get('/versions', status_code=200)
def get_versions(*,
                 flow_id: UUID,
                 Authorize: AuthJWT = Depends()):
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
                    version_id: int,
                    flow_version: FlowVersionCreate,
                    Authorize: AuthJWT = Depends()):
    """
    更新版本
    """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    return FlowService.update_version_info(user, version_id, flow_version)


@router.delete('/versions/{version_id}', status_code=200)
def delete_versions(*,
                    version_id: int,
                    Authorize: AuthJWT = Depends()):
    """
    删除版本
    """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    return FlowService.delete_version(user, version_id)


@router.get('/versions/{version_id}', status_code=200)
def get_version_info(*,
                     version_id: int,
                     Authorize: AuthJWT = Depends()):
    """
    获取版本信息
    """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    return FlowService.get_version_info(user, version_id)


@router.post('/change_version', status_code=200)
def change_version(*,
                   flow_id: UUID = Query(default=None, description='技能唯一ID'),
                   version_id: int = Query(default=None, description='需要设置的当前版本ID'),
                   Authorize: AuthJWT = Depends()):
    """
    修改当前版本
    """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    flow_id = flow_id.hex
    return FlowService.change_current_version(user, flow_id, version_id)


@router.get('/', status_code=200)
def read_flows(*,
               name: str = Query(default=None, description='根据name查找数据库，包含描述的模糊搜索'),
               page_size: int = Query(default=10, description='根据pagesize查找数据库'),
               page_num: int = Query(default=1, description='根据pagenum查找数据库'),
               status: int = None,
               Authorize: AuthJWT = Depends()):
    """Read all flows."""
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    try:
        return FlowService.get_all_flows(user, name, status, page_num, page_size)
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get('/{flow_id}', response_model=UnifiedResponseModel[FlowReadWithStyle], status_code=200)
def read_flow(*, flow_id: UUID):
    """Read a flow."""
    with session_getter() as session:
        if flow := session.get(Flow, flow_id):
            return resp_200(flow)

    raise HTTPException(status_code=404, detail='Flow not found')


@router.patch('/{flow_id}', response_model=UnifiedResponseModel[FlowRead], status_code=200)
async def update_flow(*, flow_id: UUID, flow: FlowUpdate, Authorize: AuthJWT = Depends()):
    """Update a flow."""
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    with session_getter() as session:
        db_flow = session.get(Flow, flow_id)
    if not db_flow:
        raise HTTPException(status_code=404, detail='Flow not found')

    if not access_check(payload, db_flow.user_id, flow_id, AccessType.FLOW_WRITE):
        raise HTTPException(status_code=500, detail='No right access this flow')

    flow_data = flow.model_dump(exclude_unset=True)

    if 'status' in flow_data and flow_data['status'] == 2 and db_flow.status == 1:
        # 上线校验
        try:
            art = {}
            await build_flow_no_yield(graph_data=db_flow.data,
                                      artifacts=art,
                                      process_file=False,
                                      flow_id=flow_id.hex)
        except Exception as exc:
            logger.exception(exc)
            raise HTTPException(status_code=500, detail=f'Flow 编译不通过, {str(exc)}')

    if db_flow.status == 2 and ('status' not in flow_data or flow_data['status'] != 1):
        raise HTTPException(status_code=500, detail='上线中技能，不支持修改')

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
    return resp_200(db_flow)


@router.delete('/{flow_id}', status_code=200)
def delete_flow(*, flow_id: UUID, Authorize: AuthJWT = Depends()):
    """Delete a flow."""
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    with session_getter() as session:
        flow = session.get(Flow, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail='Flow not found')
    if 'admin' != payload.get('role') and flow.user_id != payload.get('user_id'):
        raise HTTPException(status_code=500, detail='没有权限删除此技能')
    with session_getter() as session:
        session.delete(flow)
        session.commit()
    return resp_200(message='删除成功')


# Define a new model to handle multiple flows
@router.post('/batch/', response_model=UnifiedResponseModel[List[FlowRead]], status_code=201)
def create_flows(*, flow_list: FlowListCreate, Authorize: AuthJWT = Depends()):
    """Create multiple new flows."""
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    db_flows = []
    with session_getter() as session:
        for flow in flow_list.flows:
            db_flow = Flow.from_orm(flow)
            db_flow.user_id = payload.get('user_id')
            session.add(db_flow)
            db_flows.append(db_flow)
        session.commit()
        for db_flow in db_flows:
            session.refresh(db_flow)
    return resp_200(db_flows)


@router.post('/upload/', response_model=UnifiedResponseModel[List[FlowRead]], status_code=201)
async def upload_file(*, file: UploadFile = File(...), Authorize: AuthJWT = Depends()):
    """Upload flows from a file."""
    contents = await file.read()
    data = json.loads(contents)
    if 'flows' in data:
        flow_list = FlowListCreate(**data)
    else:
        flow_list = FlowListCreate(flows=[FlowCreate(**flow) for flow in data])

    return create_flows(flow_list=flow_list, Authorize=Authorize)


@router.get('/download/', response_model=UnifiedResponseModel[FlowListRead], status_code=200)
async def download_file():
    """Download all flows as a file."""
    flows = read_flows()
    return resp_200(FlowListRead(flows=flows))
