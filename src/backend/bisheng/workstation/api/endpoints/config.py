from fastapi import APIRouter, Body, Depends, Request

from bisheng.api.v1.schemas import (
    KnowledgeSpaceConfig,
    LinsightConfig,
    SubscriptionConfig,
    UnifiedResponseModel,
    WorkstationConfig,
    resp_200,
)
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.workstation.domain.services import WorkStationService

from ..dependencies import LoginUserDep

router = APIRouter()


@router.get('/config', summary='Get workbench configuration', response_model=UnifiedResponseModel)
async def get_config(request: Request, login_user=LoginUserDep):
    ret = await WorkStationService.get_daily_chat_config()
    linsight_config = await WorkStationService.get_linsight_config()
    etl_for_lm_url = (await bisheng_settings.async_get_knowledge()).etl4lm.url
    ret = ret.model_dump(exclude_unset=True) if ret else {}
    ret['linsightConfig'] = linsight_config.model_dump() if linsight_config else {}
    ret['enable_etl4lm'] = bool(etl_for_lm_url)
    linsight_invitation_code = (await bisheng_settings.aget_all_config()).get('linsight_invitation_code', None)
    ret['linsight_invitation_code'] = linsight_invitation_code if linsight_invitation_code else False
    ret['linsight_cache_dir'] = './'
    ret['waiting_list_url'] = (await bisheng_settings.aget_linsight_conf()).waiting_list_url
    # 首钢部署专属命名空间：整段透传给前端 (deployment_label / portal_admin_url 等),
    # 同时基于 prefix 派生 enabled 标志,供文件编码 (FileTable) 等功能门控使用。
    shougang_raw = (await bisheng_settings.aget_all_config()).get('shougang', None)
    if isinstance(shougang_raw, dict):
        prefix = shougang_raw.get('prefix')
        enabled = bool(prefix and str(prefix).strip())
        ret['shougang'] = {**shougang_raw, 'enabled': enabled}
    else:
        ret['shougang'] = None
    # 知识空间目录树展示开关：透传给前端 sidebar (KnowledgeSpaceItem) 做门控。
    # 缺省视为 true；中粮场内部署设 false 时只展示空间、不展开文件夹树。
    ks_raw = (await bisheng_settings.aget_all_config()).get('knowledge_space', None)
    tree_display = True
    if isinstance(ks_raw, dict):
        tree_display = bool(ks_raw.get('tree_structured_directory_display', True))
    ret['knowledge_space'] = {'tree_structured_directory_display': tree_display}
    return resp_200(data=ret)


@router.get('/config/daily', summary='Get daily workbench configuration', response_model=UnifiedResponseModel)
async def get_daily_config(request: Request, login_user=LoginUserDep):
    ret, inherited, source_tenant_id, has_override = await WorkStationService.get_daily_chat_config_with_meta()
    return resp_200(data={
        'data': ret.model_dump(exclude_unset=True) if ret else None,
        'inherited_from_root': inherited,
        'source_tenant_id': source_tenant_id,
        'has_override': has_override,
    })


@router.post('/config/daily', summary='Update daily workbench configuration', response_model=UnifiedResponseModel)
async def update_daily_config(
    request: Request,
    data: WorkstationConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = await WorkStationService.update_daily_chat_config(data)
    return resp_200(data=ret)


@router.get('/config/linsight', summary='Get linsight configuration', response_model=UnifiedResponseModel)
async def get_linsight_config(request: Request, login_user=LoginUserDep):
    ret, inherited, source_tenant_id, has_override = await WorkStationService.get_linsight_config_with_meta()
    return resp_200(data={
        'data': ret.model_dump(exclude_unset=True) if ret else None,
        'inherited_from_root': inherited,
        'source_tenant_id': source_tenant_id,
        'has_override': has_override,
    })


@router.post('/config/linsight', summary='Update linsight configuration', response_model=UnifiedResponseModel)
async def update_linsight_config(
    request: Request,
    data: LinsightConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = await WorkStationService.update_linsight_config(data)
    return resp_200(data=ret)


@router.get('/config/subscription', summary='Get subscription configuration', response_model=UnifiedResponseModel)
async def get_subscription_config(request: Request, login_user=LoginUserDep):
    ret, inherited, source_tenant_id, has_override = await WorkStationService.get_subscription_config_with_meta()
    return resp_200(data={
        'data': ret.model_dump(exclude_unset=True) if ret else None,
        'inherited_from_root': inherited,
        'source_tenant_id': source_tenant_id,
        'has_override': has_override,
    })


@router.post('/config/subscription', summary='Update subscription configuration', response_model=UnifiedResponseModel)
async def update_subscription_config(
    request: Request,
    data: SubscriptionConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = await WorkStationService.update_subscription_config(data)
    return resp_200(data=ret)


@router.get('/config/knowledge_space', summary='Get knowledge_space configuration', response_model=UnifiedResponseModel)
async def get_knowledge_space_config(request: Request, login_user=LoginUserDep):
    ret, inherited, source_tenant_id, has_override = await WorkStationService.get_knowledge_space_config_with_meta()
    return resp_200(data={
        'data': ret.model_dump(exclude_unset=True) if ret else None,
        'inherited_from_root': inherited,
        'source_tenant_id': source_tenant_id,
        'has_override': has_override,
    })


@router.post('/config/knowledge_space', summary='Update knowledge_space configuration', response_model=UnifiedResponseModel)
async def update_knowledge_space_config(
    request: Request,
    data: KnowledgeSpaceConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = await WorkStationService.update_knowledge_space_config(data)
    return resp_200(data=ret)
