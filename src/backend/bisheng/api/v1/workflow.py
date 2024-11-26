import json
import os
from typing import Optional
from uuid import UUID

from bisheng.api.v1.skillcenter import ORDER_GAP
from bisheng.database.models.template import Template, TemplateCreate, TemplateRead
from sqlmodel import select
from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.errcode.flow import FlowOnlineEditError
from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.utils import get_L2_param_from_flow
from bisheng.database.base import session_getter
from bisheng.database.models.flow import Flow, FlowCreate, FlowDao, FlowRead, FlowReadWithStyle, FlowType, FlowUpdate
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.role_access import AccessType
from uuid import uuid4

from bisheng_langchain.utils.requests import Requests
from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketException, Request
from fastapi import status as http_status
from fastapi_jwt_auth import AuthJWT
from loguru import logger

from bisheng.api.services.flow import FlowService
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schemas import FlowVersionCreate, UnifiedResponseModel, resp_200
from bisheng.chat.types import WorkType
from bisheng.utils.minio_client import MinioClient

router = APIRouter(prefix='/workflow', tags=['Workflow'])


@router.get('/template', response_model=UnifiedResponseModel, status_code=200)
def get_template():
    """ 获取节点模板的接口 """
    # todo: 改为template class 管理
    current_path = os.path.dirname(os.path.abspath(__file__))
    with open(f"{current_path}/workflow_template.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    return resp_200(data=data)


@router.get("/report/file", response_model=UnifiedResponseModel, status_code=200)
async def get_report_file(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
        version_key: str = Query("", description="minio的object_name")):
    """ 获取report节点的模板文件 """
    if not version_key:
        # 重新生成一个version_key
        version_key = uuid4().hex
    file_url = ""
    object_name = f"workflow/report/{version_key}.docx"
    minio_client = MinioClient()
    if minio_client.object_exists(minio_client.bucket, object_name):
        file_url = minio_client.get_share_link(object_name)

    return resp_200(data={
        'url': file_url,
        'version_key': version_key,
    })


@router.post('/report/callback', status_code=200)
async def upload_report_file(
        request: Request,
        data: dict = Body(...)):
    """ office 回调接口保存 report节点的模板文件 """
    status = data.get('status')
    file_url = data.get('url')
    key = data.get('key')
    logger.debug(f'callback={data}')
    if status not in {2, 6}:
        # 非保存回调不处理
        return {'error': 0}
    logger.info(f'office_callback url={file_url}')
    file = Requests().get(url=file_url)

    minio_client = MinioClient()
    object_name = f"workflow/report/{key}.docx"
    minio_client.upload_minio_data(
        object_name, file._content, len(file._content),
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return {'error': 0}


@router.websocket('/chat/{workflow_id}')
async def workflow_ws(*,
                      workflow_id: str,
                      websocket: WebSocket,
                      t: Optional[str] = None,
                      chat_id: Optional[str] = None,
                      Authorize: AuthJWT = Depends()):
    try:
        # if t:
        #     Authorize.jwt_required(auth_from='websocket', token=t)
        #     Authorize._token = t
        # else:
        #     Authorize.jwt_required(auth_from='websocket', websocket=websocket)
        #
        # payload = Authorize.get_jwt_subject()
        # payload = json.loads(payload)
        payload = {
            'user_id': 1,
            'user_name': 'admin',
            'role': 'admin',
        }
        login_user = UserPayload(**payload)
        await chat_manager.dispatch_client(websocket, workflow_id, chat_id, login_user, WorkType.WORKFLOW, websocket)
    except WebSocketException as exc:
        logger.error(f'Websocket exception: {str(exc)}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))

@router.post('/create', status_code=201)
def create_flow(*, request: Request, flow: FlowCreate, login_user: UserPayload = Depends(get_login_user)):
    """Create a new flow."""
    # 判断用户是否重复技能名
    with session_getter() as session:
        if session.exec(
                select(Flow).where(Flow.name == flow.name,Flow.flow_type == FlowType.WORKFLOW.value,
                                   Flow.user_id == login_user.user_id)).first():
            raise HTTPException(status_code=500, detail='工作流名重复')
    flow.user_id = login_user.user_id
    db_flow = Flow.model_validate(flow)
    db_flow.flow_type = FlowType.WORKFLOW.value
    # 创建新的技能
    db_flow = FlowDao.create_flow(db_flow,FlowType.WORKFLOW.value)

    current_version = FlowVersionDao.get_version_by_flow(db_flow.id.hex)
    ret = FlowRead.model_validate(db_flow)
    ret.version_id = current_version.id
    FlowService.create_flow_hook(request, login_user, db_flow, ret.version_id,FlowType.WORKFLOW.value)
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
    flow_version.flow_type = FlowType.WORKFLOW.value
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


@router.get('/get_one_flow/{flow_id}', response_model=UnifiedResponseModel[FlowReadWithStyle], status_code=200)
def read_flow(*, flow_id: UUID, login_user: UserPayload = Depends(get_login_user)):
    """Read a flow."""
    return FlowService.get_one_flow(login_user, flow_id.hex)


@router.patch('/update/{flow_id}', response_model=UnifiedResponseModel[FlowRead], status_code=200)
async def update_flow(*,
                      request: Request,
                      flow_id: UUID,
                      flow: FlowUpdate,
                      login_user: UserPayload = Depends(get_login_user)):
    """online offline"""
    flow_id = flow_id.hex
    with session_getter() as session:
        db_flow = session.get(Flow, flow_id)
    if not db_flow:
        raise HTTPException(status_code=404, detail='Flow not found')

    if not login_user.access_check(db_flow.user_id, flow_id, AccessType.WORK_FLOW_WRITE):
        return UnAuthorizedError.return_resp()

    flow_data = flow.model_dump(exclude_unset=True)

    # TODO:  验证工作流是否可以使用

    if db_flow.status == 2 and ('status' not in flow_data or flow_data['status'] != 1):
        raise FlowOnlineEditError.http_exception()

    # if settings.remove_api_keys:
    #     flow_data = remove_api_keys(flow_data)
    for key, value in flow_data.items():
        setattr(db_flow, key, value)
    with session_getter() as session:
        session.add(db_flow)
        session.commit()
        session.refresh(db_flow)
    # try:
    #     if not get_L2_param_from_flow(db_flow.data, db_flow.id):
    #         logger.error(f'flow_id={db_flow.id} extract file_node fail')
    # except Exception:
    #     pass
    FlowService.update_flow_hook(request, login_user, db_flow)
    return resp_200(db_flow)


@router.get('/list', status_code=200)
def read_flows(*,
               name: str = Query(default=None, description='根据name查找数据库，包含描述的模糊搜索'),
               tag_id: int = Query(default=None, description='标签ID'),
               flow_type: int = Query(default=None, description='类型 1 flow 5 assitant 10 workflow '),
               page_size: int = Query(default=10, description='每页数量'),
               page_num: int = Query(default=1, description='页数'),
               status: int = None,
               Authorize: AuthJWT = Depends()):
    """Read all flows."""
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    try:
        return WorkFlowService.get_all_flows(user, name, status, tag_id,flow_type, page_num, page_size)
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post('/template/create',
             response_model=UnifiedResponseModel[TemplateRead],
             status_code=201)
def create_template(*, template: TemplateCreate):
    """Create a new workflow or assitant."""
    template.flow_type = FlowType.WORKFLOW.value
    db_template = Template.model_validate(template)
    # TODO: if assitant need more data 
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
