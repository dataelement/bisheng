import json
from typing import List
from uuid import UUID

from bisheng.api.utils import build_flow_no_yield, remove_api_keys
from bisheng.api.v1.schemas import FlowListCreate, FlowListRead
from bisheng.database.base import get_session
from bisheng.database.models.flow import (Flow, FlowCreate, FlowRead,
                                          FlowReadWithStyle, FlowUpdate)
from bisheng.settings import settings
from bisheng.utils.logger import logger
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/flows', tags=['Flows'])


@router.post('/', response_model=FlowRead, status_code=201)
def create_flow(*, session: Session = Depends(get_session), flow: FlowCreate):
    """Create a new flow."""
    if flow.flow_id:
        # copy from template
        temp_flow = session.get(Flow, flow.flow_id)
        flow.data = temp_flow.data
    db_flow = Flow.from_orm(flow)
    session.add(db_flow)
    session.commit()
    session.refresh(db_flow)
    return db_flow


@router.get('/', response_model=list[FlowReadWithStyle], status_code=200)
def read_flows(*, session: Session = Depends(get_session),
    name: str = Query(default=None,description='根据name查找数据库'),
    page_size: int = Query(default=None,description='根据pagesize查找数据库'),
    page_num: int = Query(default=None,description='根据pagenum查找数据库'),
    status: int = None):
    """Read all flows."""
    try:
        sql = select(Flow)
        if name:
            sql = sql.where(Flow.name.like(f'%{name}%'))
        if status:
            sql = sql.where(Flow.status == status)

        sql = sql.order_by(Flow.update_time.desc())
        if page_num and page_size:
            sql = sql.offset((page_num-1)*page_size).limit(page_size)

        flows = session.exec(sql).all()
        return [jsonable_encoder(flow) for flow in flows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get('/{flow_id}', response_model=FlowReadWithStyle, status_code=200)
def read_flow(*, session: Session = Depends(get_session), flow_id: UUID):
    """Read a flow."""
    if flow := session.get(Flow, flow_id):
        return flow
    else:
        raise HTTPException(status_code=404, detail='Flow not found')


@router.patch('/{flow_id}', response_model=FlowRead, status_code=200)
def update_flow(
    *, session: Session = Depends(get_session), flow_id: UUID, flow: FlowUpdate
):
    """Update a flow."""
    db_flow = session.get(Flow, flow_id)
    if not db_flow:
        raise HTTPException(status_code=404, detail='Flow not found')
    flow_data = flow.dict(exclude_unset=True)

    if 'status' in flow_data and flow_data['status'] == 2 and db_flow.status == 1:
        #上线校验
        try:
            art={}
            build_flow_no_yield(graph_data=db_flow.data, artifacts=art, process_file=False)
        except Exception as exc:
            raise HTTPException(status_code=500, detail='Flow 编译不通过') from exc

    if settings.remove_api_keys:
        flow_data = remove_api_keys(flow_data)
    for key, value in flow_data.items():
        setattr(db_flow, key, value)
    session.add(db_flow)
    session.commit()
    session.refresh(db_flow)
    return db_flow


@router.delete('/{flow_id}', status_code=200)
def delete_flow(*, session: Session = Depends(get_session), flow_id: UUID):
    """Delete a flow."""
    flow = session.get(Flow, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail='Flow not found')
    session.delete(flow)
    session.commit()
    return {'message': 'Flow deleted successfully'}


# Define a new model to handle multiple flows


@router.post('/batch/', response_model=List[FlowRead], status_code=201)
def create_flows(*, session: Session = Depends(get_session), flow_list: FlowListCreate):
    """Create multiple new flows."""
    db_flows = []
    for flow in flow_list.flows:
        db_flow = Flow.from_orm(flow)
        session.add(db_flow)
        db_flows.append(db_flow)
    session.commit()
    for db_flow in db_flows:
        session.refresh(db_flow)
    return db_flows


@router.post('/upload/', response_model=List[FlowRead], status_code=201)
async def upload_file(
    *, session: Session = Depends(get_session), file: UploadFile = File(...)
):
    """Upload flows from a file."""
    contents = await file.read()
    data = json.loads(contents)
    if 'flows' in data:
        flow_list = FlowListCreate(**data)
    else:
        flow_list = FlowListCreate(flows=[FlowCreate(**flow) for flow in data])
    return create_flows(session=session, flow_list=flow_list)


@router.get('/download/', response_model=FlowListRead, status_code=200)
async def download_file(*, session: Session = Depends(get_session)):
    """Download all flows as a file."""
    flows = read_flows(session=session)
    return FlowListRead(flows=flows)
