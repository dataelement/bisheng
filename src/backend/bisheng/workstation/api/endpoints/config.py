from fastapi import APIRouter, Body, Request

from bisheng.api.v1.schemas import (
    KnowledgeSpaceConfig,
    LinsightConfig,
    SubscriptionConfig,
    UnifiedResponseModel,
    WorkstationConfig,
    resp_200,
)
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.workstation.domain.services import WorkStationService

from ..dependencies import AdminUserDep, LoginUserDep

router = APIRouter()


@router.get('/config', summary='Get workbench configuration', response_model=UnifiedResponseModel)
async def get_config(request: Request, login_user=LoginUserDep):
    ret = await WorkStationService.get_daily_chat_config()
    linsight_config = await WorkStationService.get_linsight_config()
    etl_for_lm_url = (await bisheng_settings.async_get_knowledge()).etl4lm.url
    ret = ret.model_dump() if ret else {}
    ret['linsightConfig'] = linsight_config.model_dump() if linsight_config else {}
    ret['enable_etl4lm'] = bool(etl_for_lm_url)
    linsight_invitation_code = (await bisheng_settings.aget_all_config()).get('linsight_invitation_code', None)
    ret['linsight_invitation_code'] = linsight_invitation_code if linsight_invitation_code else False
    ret['linsight_cache_dir'] = './'
    ret['waiting_list_url'] = (await bisheng_settings.aget_linsight_conf()).waiting_list_url
    return resp_200(data=ret)


@router.get('/config/daily', summary='Get daily workbench configuration', response_model=UnifiedResponseModel)
async def get_daily_config(request: Request, login_user=LoginUserDep):
    ret = await WorkStationService.get_daily_chat_config()
    return resp_200(data=ret)


@router.post('/config/daily', summary='Update daily workbench configuration', response_model=UnifiedResponseModel)
async def update_daily_config(request: Request, data: WorkstationConfig = Body(...), login_user=AdminUserDep):
    ret = await WorkStationService.update_daily_chat_config(data)
    return resp_200(data=ret)


@router.get('/config/linsight', summary='Get linsight configuration', response_model=UnifiedResponseModel)
async def get_linsight_config(request: Request, login_user=LoginUserDep):
    ret = await WorkStationService.get_linsight_config()
    return resp_200(data=ret)


@router.post('/config/linsight', summary='Update linsight configuration', response_model=UnifiedResponseModel)
async def update_linsight_config(request: Request, data: LinsightConfig = Body(...), login_user=AdminUserDep):
    ret = await WorkStationService.update_linsight_config(data)
    return resp_200(data=ret)


@router.get('/config/subscription', summary='Get subscription configuration', response_model=UnifiedResponseModel)
async def get_subscription_config(request: Request, login_user=LoginUserDep):
    ret = await WorkStationService.get_subscription_config()
    return resp_200(data=ret)


@router.post('/config/subscription', summary='Update subscription configuration', response_model=UnifiedResponseModel)
async def update_subscription_config(
    request: Request,
    data: SubscriptionConfig = Body(...),
    login_user=AdminUserDep,
):
    ret = await WorkStationService.update_subscription_config(data)
    return resp_200(data=ret)


@router.get('/config/knowledge_space', summary='Get knowledge_space configuration', response_model=UnifiedResponseModel)
async def get_knowledge_space_config(request: Request, login_user=LoginUserDep):
    ret = await WorkStationService.get_knowledge_space_config()
    return resp_200(data=ret)


@router.post('/config/knowledge_space', summary='Update knowledge_space configuration', response_model=UnifiedResponseModel)
async def update_knowledge_space_config(
    request: Request,
    data: KnowledgeSpaceConfig = Body(...),
    login_user=AdminUserDep,
):
    ret = await WorkStationService.update_knowledge_space_config(data)
    return resp_200(data=ret)
