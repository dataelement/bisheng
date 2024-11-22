from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select

from bisheng.api.services.user_service import get_login_user
from bisheng.api.utils import remove_api_keys
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.base import session_getter
from bisheng.database.models.flow import Flow
from bisheng.database.models.template import Template, TemplateCreate, TemplateRead, TemplateUpdate
from bisheng.settings import settings

# build router
router = APIRouter(prefix='/skill', tags=['Skills'], dependencies=[Depends(get_login_user)])
ORDER_GAP = 65535


@router.post('/template/create',
             response_model=UnifiedResponseModel[TemplateRead],
             status_code=201)
def create_template(*, template: TemplateCreate):
    """Create a new flow."""
    db_template = Template.model_validate(template)
    if not db_template.data:
        with session_getter() as session:
            db_flow = session.get(Flow, template.flow_id)
        db_template.data = db_flow.data
    # 校验name
    with session_getter() as session:
        name_repeat = session.exec(
            select(Template).where(Template.name == db_template.name)).first()
    if name_repeat:
        raise HTTPException(status_code=500, detail='Repeat name, please choose another name')
    # 增加 order_num  x,x+65535
    with session_getter() as session:
        max_order = session.exec(select(Template).order_by(
            Template.order_num.desc()).limit(1)).first()
    # 如果没有数据，就从 65535 开始
    db_template.order_num = max_order.order_num + ORDER_GAP if max_order else ORDER_GAP
    with session_getter() as session:
        session.add(db_template)
        session.commit()
        session.refresh(db_template)
    return resp_200(db_template)


@router.get('/template', response_model=UnifiedResponseModel[list[Template]], status_code=200)
def read_template(page_size: Optional[int] = None,
                  page_name: Optional[int] = None,
                  flow_type: Optional[int] = None,
                  id: Optional[int] = None,
                  name: Optional[str] = None):
    """Read all flows."""
    sql = select(Template.id, Template.name, Template.description, Template.update_time)
    if id:
        with session_getter() as session:
            template = session.get(Template, id)
        return resp_200([template])
    if name:
        sql = sql.where(Template.name == name)
    if flow_type:
        sql = sql.where(Template.flow_type == flow_type)

    sql.order_by(Template.order_num.desc())
    if page_size and page_name:
        sql.offset(page_size * (page_name - 1)).limit(page_size)
    try:
        with session_getter() as session:
            template_session = session.exec(sql)
        templates = template_session.mappings().all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return resp_200(templates)


@router.post('/template/{id}', response_model=UnifiedResponseModel[TemplateRead], status_code=200)
def update_template(*, id: int, template: TemplateUpdate):
    """Update a flow."""
    with session_getter() as session:
        db_template = session.get(Template, id)
    if not db_template:
        raise HTTPException(status_code=404, detail='Template not found')
    template_data = template.model_dump(exclude_unset=True)
    if settings.remove_api_keys:
        template_data = remove_api_keys(template_data)
    for key, value in template_data.items():
        setattr(db_template, key, value)
    with session_getter() as session:
        session.add(db_template)
        session.commit()
        session.refresh(db_template)
    return resp_200(db_template)


@router.delete('/template/{id}', status_code=200)
def delete_template(*, id: int):
    """Delete a flow."""
    with session_getter() as session:
        db_template = session.get(Template, id)
    if not db_template:
        raise HTTPException(status_code=404, detail='Template not found')
    with session_getter() as session:
        session.delete(db_template)
        session.commit()
    return resp_200()
