from uuid import UUID

from fastapi import APIRouter, Request
from loguru import logger

from bisheng.api.services.flow import FlowService
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_endpoints.domain.utils import get_open_api_operator

router = APIRouter(prefix='/flows', tags=['OpenAPI', 'FlowV2'])


@router.get('/{flow_id}', status_code=200)
@open_api_scope("workflow:read")
async def get_flow(request: Request, flow_id: UUID):
    """
    Exposed interfaces for obtaining skill information
    """
    flow_id = flow_id.hex
    logger.info(f'public_get_flow  ip: {request.client.host} flow_id:{flow_id}')
    default_user = get_open_api_operator()

    return await FlowService.get_one_flow(default_user, flow_id)
