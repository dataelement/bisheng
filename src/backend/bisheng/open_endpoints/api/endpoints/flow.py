from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger

from bisheng.api.services.flow import FlowService
from bisheng.common.services.config_service import settings
from bisheng.open_endpoints.api.endpoints.assistant import get_default_operator

router = APIRouter(prefix='/flows', tags=['OpenAPI', 'FlowV2'])


@router.get('/{flow_id}', status_code=200)
async def get_flow(request: Request, flow_id: UUID):
    """
    Exposed interfaces for obtaining skill information
    """
    flow_id = flow_id.hex
    logger.info(f'public_get_flow  ip: {request.client.host} flow_id:{flow_id}')
    # Determine if the configuration under is turned on
    if not settings.get_from_db("default_operator").get("enable_guest_access"):
        raise HTTPException(status_code=403, detail="No permission to access")
    default_user = get_default_operator()

    return await FlowService.get_one_flow(default_user, flow_id)


@router.get('', status_code=200)
def get_flow_list(request: Request,
                  name: str = Query(default=None, description='accordingnameFind databases with fuzzy searches for descriptions'),
                  tag_id: int = Query(default=None, description='labelID'),
                  page_size: int = Query(default=10, description='Items per page'),
                  page_num: int = Query(default=1, description='Page'),
                  status: int = None,
                  user_id: int = None):
    """
    Exposed interfaces for obtaining skill information
    """
    logger.info(f'public_get_flow_list  ip: {request.client.host} user_id={user_id}')
    login_user = get_default_operator()

    try:
        return FlowService.get_all_flows(login_user, name, status, tag_id, page_num, page_size)
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail='Failed to get skills list')
