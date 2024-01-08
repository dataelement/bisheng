from bisheng.api.utils import remove_api_keys
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.base import get_session
from bisheng.database.models.flow import Flow
from bisheng.database.models.template import Template, TemplateCreate, TemplateRead, TemplateUpdate
from bisheng.settings import settings
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/skill', tags=['Skills'])
ORDER_GAP = 65535


@router.post('/template/create',
             response_model=UnifiedResponseModel[TemplateRead],
             status_code=201)
def create_template(*, session: Session = Depends(get_session), template: TemplateCreate):
    """Create a new flow."""
    db_template = Template.from_orm(template)
    if not db_template.data:
        db_flow = session.get(Flow, template.flow_id)
        db_template.data = db_flow.data
    # 校验name
    name_repeat = session.exec(select(Template).where(Template.name == db_template.name)).first()
    if name_repeat:
        raise HTTPException(status_code=500, detail='Repeat name, please choose another name')
    # 增加 order_num  x,x+65535
    max_order = session.exec(select(Template).order_by(Template.order_num.desc()).limit(1)).first()
    # 如果没有数据，就从 65535 开始
    db_template.order_num = max_order.order_num + ORDER_GAP if max_order else ORDER_GAP
    session.add(db_template)
    session.commit()
    session.refresh(db_template)
    return resp_200(db_template)


@router.get('/template/', response_model=UnifiedResponseModel[list[Template]], status_code=200)
def read_template(*, session: Session = Depends(get_session)):
    """Read all flows."""
    try:
        templates = session.exec(select(Template).order_by(Template.order_num.desc())).all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return resp_200(templates)


@router.post('/template/{id}', response_model=UnifiedResponseModel[TemplateRead], status_code=200)
def update_template(*, session: Session = Depends(get_session), id: int, template: TemplateUpdate):
    """Update a flow."""
    db_template = session.get(Template, id)
    if not db_template:
        raise HTTPException(status_code=404, detail='Template not found')
    template_data = template.dict(exclude_unset=True)
    if settings.remove_api_keys:
        template_data = remove_api_keys(template_data)
    for key, value in template_data.items():
        setattr(db_template, key, value)
    session.add(db_template)
    session.commit()
    session.refresh(db_template)
    return resp_200(db_template)


@router.delete('/template/{id}', status_code=200)
def delete_template(*, session: Session = Depends(get_session), id: int):
    """Delete a flow."""
    db_template = session.get(Template, id)
    if not db_template:
        raise HTTPException(status_code=404, detail='Template not found')
    session.delete(db_template)
    session.commit()
    return resp_200()
