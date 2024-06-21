from uuid import UUID
from loguru import logger

from fastapi import APIRouter, Request, HTTPException

from bisheng.api.v1.schemas import resp_200
from bisheng.database.models.flow import FlowDao
from bisheng.settings import settings
router = APIRouter(prefix='/flows', tags=['FlowV2'])


@router.get("/{flow_id}", status_code=200)
def get_flow(request: Request, flow_id: UUID):
    """
    公开的获取技能信息的接口
    """
    logger.info(f"public_get_flow  ip: {request.client.host} flow_id:{flow_id}")
    # 判断下配置是否打开
    if settings.get_from_db("default_operator").get("api_need_login"):
        raise HTTPException(status_code=403, detail="无权限访问")

    db_flow = FlowDao.get_flow_by_id(flow_id.hex)
    if not db_flow:
        raise HTTPException(status_code=404, detail='Flow not found')
    return resp_200(db_flow)
