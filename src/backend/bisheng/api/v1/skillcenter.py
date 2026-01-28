from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select

from bisheng.api.utils import remove_api_keys
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import FlowTemplateNameError
from bisheng.common.services.config_service import settings
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.flow import Flow
from bisheng.database.models.template import Template, TemplateCreate, TemplateUpdate

# build router
router = APIRouter(prefix='/skill', tags=['Skills'], dependencies=[Depends(UserPayload.get_login_user)])
ORDER_GAP = 65535


@router.post('/template/create')
def create_template(*, template: TemplateCreate):
    """Create a new flow."""
    db_template = Template.model_validate(template)
    if not db_template.data:
        with get_sync_db_session() as session:
            db_flow = session.get(Flow, template.flow_id)
        db_template.data = db_flow.data
    # Correctionname
    with get_sync_db_session() as session:
        name_repeat = session.exec(
            select(Template).where(Template.name == db_template.name)).first()
    if name_repeat:
        raise FlowTemplateNameError.http_exception()
    # Boost order_num  x,x+65535
    with get_sync_db_session() as session:
        max_order = session.exec(select(Template).order_by(
            Template.order_num.desc()).limit(1)).first()
    # If no data is available, proceed from 65535 Getting Started
    db_template.order_num = max_order.order_num + ORDER_GAP if max_order else ORDER_GAP
    with get_sync_db_session() as session:
        session.add(db_template)
        session.commit()
        session.refresh(db_template)
    return resp_200(db_template)


@router.get('/template')
def read_template(page_size: Optional[int] = None,
                  page_name: Optional[int] = None,
                  flow_type: Optional[int] = None,
                  id: Optional[int] = None,
                  name: Optional[str] = None):
    """Read all flows."""
    sql = select(Template.id, Template.name, Template.description, Template.update_time, Template.order_num)
    if id:
        with get_sync_db_session() as session:
            template = session.get(Template, id)
        return resp_200([template])
    if name:
        sql = sql.where(Template.name == name)
    if flow_type:
        sql = sql.where(Template.flow_type == flow_type)

    sql = sql.order_by(Template.order_num.desc())
    if page_size and page_name:
        sql = sql.offset(page_size * (page_name - 1)).limit(page_size)
    try:
        with get_sync_db_session() as session:
            template_session = session.exec(sql)
        templates = template_session.mappings().all()
        res = []
        for one in templates:
            res.append(Template.model_validate(one))
        return resp_200(res)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post('/template/{id}')
def update_template(*, id: int, template: TemplateUpdate):
    """Update a flow."""
    with get_sync_db_session() as session:
        db_template = session.get(Template, id)
    if not db_template:
        raise HTTPException(status_code=404, detail='Template not found')
    template_data = template.model_dump(exclude_unset=True)
    if settings.remove_api_keys:
        template_data = remove_api_keys(template_data)
    for key, value in template_data.items():
        setattr(db_template, key, value)
    with get_sync_db_session() as session:
        session.add(db_template)
        session.commit()
        session.refresh(db_template)
    return resp_200(db_template)


@router.delete('/template/{id}', status_code=200)
def delete_template(*, id: int):
    """Delete a flow."""
    with get_sync_db_session() as session:
        db_template = session.get(Template, id)
    if not db_template:
        raise HTTPException(status_code=404, detail='Template not found')
    with get_sync_db_session() as session:
        session.delete(db_template)
        session.commit()
    return resp_200()
