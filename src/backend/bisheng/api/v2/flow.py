from uuid import UUID

from bisheng.api.services.flow import FlowService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v2.assistant import get_default_operator
from bisheng.settings import settings
from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger

router = APIRouter(prefix='/flows', tags=['OpenAPI', 'FlowV2'])


@router.get('/{flow_id}', status_code=200)
def get_flow(request: Request, flow_id: UUID):
    """
    公开的获取技能信息的接口
    """
    logger.info(f'public_get_flow  ip: {request.client.host} flow_id:{flow_id}')
    # 判断下配置是否打开
    if not settings.get_from_db("default_operator").get("enable_guest_access"):
        raise HTTPException(status_code=403, detail="无权限访问")
    default_user = get_default_operator()
    login_user = UserPayload(**{
        'user_id': default_user.user_id,
        'user_name': default_user.user_name,
        'role': ''
    })

    return FlowService.get_one_flow(login_user, flow_id.hex)


@router.get('', status_code=200)
def get_flow_list(request: Request,
                  name: str = Query(default=None, description='根据name查找数据库，包含描述的模糊搜索'),
                  tag_id: int = Query(default=None, description='标签ID'),
                  page_size: int = Query(default=10, description='每页数量'),
                  page_num: int = Query(default=1, description='页数'),
                  status: int = None,
                  user_id: int = None):
    """
    公开的获取技能信息的接口
    """
    logger.info(f'public_get_flow_list  ip: {request.client.host} user_id={user_id}')

    user_id = user_id if user_id else settings.get_from_db('default_operator').get('user')
    login_user = UserPayload(**{'user_id': user_id, 'role': ''})
    try:
        return FlowService.get_all_flows(login_user, name, status, tag_id, page_num, page_size)
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail='获取技能列表失败')
