import json
from typing import List
from uuid import UUID

from bisheng.api.utils import (access_check, build_flow_no_yield, get_L2_param_from_flow,
                               remove_api_keys)
from bisheng.api.v1.schemas import FlowListCreate, FlowListRead, UnifiedResponseModel, resp_200
from bisheng.database.base import get_session
from bisheng.database.models.flow import Flow, FlowCreate, FlowRead, FlowReadWithStyle, FlowUpdate
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.user import User
from bisheng.settings import settings
from bisheng.utils.logger import logger
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import func, or_
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/flows', tags=['Flows'])


@router.post('/', status_code=201)
def create_flow(*,
                session: Session = Depends(get_session),
                flow: FlowCreate,
                Authorize: AuthJWT = Depends()):
    """Create a new flow."""
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    flow.user_id = payload.get('user_id')
    db_flow = Flow.model_validate(flow)
    session.add(db_flow)
    session.commit()
    session.refresh(db_flow)
    return resp_200(data=FlowRead.model_validate(db_flow))


@router.get('/', status_code=200)
def read_flows(*,
               session: Session = Depends(get_session),
               name: str = Query(default=None, description='根据name查找数据库'),
               page_size: int = Query(default=None, description='根据pagesize查找数据库'),
               page_num: int = Query(default=None, description='根据pagenum查找数据库'),
               status: int = None,
               Authorize: AuthJWT = Depends()):
    """Read all flows."""
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    try:
        sql = select(Flow.id, Flow.user_id, Flow.name, Flow.status, Flow.create_time,
                     Flow.update_time, Flow.description)
        count_sql = select(func.count(Flow.id))
        if 'admin' != payload.get('role'):
            rol_flow_id = session.exec(
                select(RoleAccess).where(RoleAccess.role_id.in_(payload.get('role')))).all()
            if rol_flow_id:
                flow_ids = [
                    acess.third_id for acess in rol_flow_id if acess.type == AccessType.FLOW.value
                ]
                sql = sql.where(or_(Flow.user_id == payload.get('user_id'), Flow.id.in_(flow_ids)))
                count_sql = count_sql.where(
                    or_(Flow.user_id == payload.get('user_id'), Flow.id.in_(flow_ids)))
            else:
                sql = sql.where(Flow.user_id == payload.get('user_id'))
                count_sql = count_sql.where(Flow.user_id == payload.get('user_id'))
        if name:
            sql = sql.where(Flow.name.like(f'%{name}%'))
            count_sql = count_sql.where(Flow.name.like(f'%{name}%'))
        if status:
            sql = sql.where(Flow.status == status)
            count_sql = count_sql.where(Flow.status == status)
        total_count = session.scalar(count_sql)
        sql = sql.order_by(Flow.update_time.desc())
        if page_num and page_size:
            sql = sql.offset((page_num - 1) * page_size).limit(page_size)
        flows = session.exec(sql)
        flows_partial = flows.mappings().all()
        flows = [Flow.model_validate(f) for f in flows_partial]
        # # get flow data
        # if flows:
        #     flows = session.exec(
        #         select(Flow).where(Flow.id.in_(flows)).order_by(Flow.update_time.desc())).all()
        res = [jsonable_encoder(flow) for flow in flows]
        if flows:
            db_user_ids = {flow.user_id for flow in flows}
            db_user = session.exec(select(User).where(User.user_id.in_(db_user_ids))).all()
            userMap = {user.user_id: user.user_name for user in db_user}
            for r in res:
                r['user_name'] = userMap[r['user_id']]
                r['write'] = True if 'admin' == payload.get('role') or r.get(
                    'user_id') == payload.get('user_id') else False

        return resp_200(data={'data': res, 'total': total_count})

    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get('/{flow_id}', response_model=UnifiedResponseModel[FlowReadWithStyle], status_code=200)
def read_flow(*, session: Session = Depends(get_session), flow_id: UUID):
    """Read a flow."""
    if flow := session.get(Flow, flow_id):
        return resp_200(flow)
    else:
        raise HTTPException(status_code=404, detail='Flow not found')


@router.patch('/{flow_id}', response_model=UnifiedResponseModel[FlowRead], status_code=200)
async def update_flow(*,
                      session: Session = Depends(get_session),
                      flow_id: UUID,
                      flow: FlowUpdate,
                      Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    """Update a flow."""
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
def delete_flow(*,
                session: Session = Depends(get_session),
                flow_id: UUID,
                Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    """Delete a flow."""
    flow = session.get(Flow, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail='Flow not found')
    if 'admin' != payload.get('role') and flow.user_id != payload.get('user_id'):
        raise HTTPException(status_code=500, detail='没有权限删除此技能')

    session.delete(flow)
    session.commit()
    return resp_200(message='删除成功')


# Define a new model to handle multiple flows
@router.post('/batch/', response_model=UnifiedResponseModel[List[FlowRead]], status_code=201)
def create_flows(*,
                 session: Session = Depends(get_session),
                 flow_list: FlowListCreate,
                 Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    """Create multiple new flows."""
    db_flows = []
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
async def upload_file(*,
                      session: Session = Depends(get_session),
                      file: UploadFile = File(...),
                      Authorize: AuthJWT = Depends()):
    """Upload flows from a file."""
    contents = await file.read()
    data = json.loads(contents)
    if 'flows' in data:
        flow_list = FlowListCreate(**data)
    else:
        flow_list = FlowListCreate(flows=[FlowCreate(**flow) for flow in data])
    return create_flows(session=session, flow_list=flow_list, Authorize=Authorize)


@router.get('/download/', response_model=UnifiedResponseModel[FlowListRead], status_code=200)
async def download_file(*, session: Session = Depends(get_session)):
    """Download all flows as a file."""
    flows = read_flows(session=session)
    return resp_200(FlowListRead(flows=flows))
