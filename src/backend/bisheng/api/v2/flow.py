from uuid import UUID
from loguru import logger

from fastapi import APIRouter, Request, HTTPException

from bisheng.api.services.flow import FlowService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import resp_200
from bisheng.api.v2.assistant import get_default_operator
from bisheng.database.models.flow import FlowDao
from bisheng.settings import settings

router = APIRouter(prefix='/flows', tags=['OpenAPI', 'FlowV2'])


@router.get("/{flow_id}", status_code=200)
def get_flow(request: Request, flow_id: UUID):
    """
    公开的获取技能信息的接口
    """
    logger.info(f"public_get_flow  ip: {request.client.host} flow_id:{flow_id}")
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
