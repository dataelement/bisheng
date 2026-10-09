from fastapi import APIRouter, Depends, Query

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
    redact_portal_admin_config,
    resolve_portal_watermark_horizontal_text,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)

router = APIRouter(prefix="/shougang-portal/config", tags=["shougang-portal-config"])


def _current_admin_tenant_id(admin_user: UserPayload) -> int:
    return int(get_current_tenant_id() or admin_user.tenant_id)


@router.get("")
async def get_shougang_portal_config(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    config = await ShougangPortalConfigService.get_config(
        tenant_id=_current_admin_tenant_id(admin_user),
    )
    return resp_200(redact_portal_admin_config(config) if config else None)


@router.get("/internal")
async def get_shougang_portal_config_internal():
    return resp_200(await ShougangPortalConfigService.get_config())


@router.get("/watermark")
async def get_shougang_portal_watermark_config():
    config = await ShougangPortalConfigService.get_config()
    watermark = config.portal.watermark if config is not None else None
    return resp_200({"horizontal_text": resolve_portal_watermark_horizontal_text(watermark)})


@router.put("")
async def save_shougang_portal_config(
    payload: ShougangPortalAdminConfig,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    saved = await ShougangPortalConfigService.save_config(
        payload,
        tenant_id=_current_admin_tenant_id(admin_user),
        create_user=admin_user.user_id,
    )
    return resp_200(redact_portal_admin_config(saved))


async def _manual_service():
    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.repositories.implementations.portal_manual_recommendation_repository_impl import (
        PortalManualRecommendationRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.portal_manual_recommendation_service import PortalManualRecommendationService

    async with get_async_db_session() as session:
        yield PortalManualRecommendationService(PortalManualRecommendationRepositoryImpl(session))


@router.get('/recommendation/spaces')
async def manual_recommendation_spaces(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
    service=Depends(_manual_service),
):
    return resp_200(await service.list_spaces())


@router.get('/recommendation/files')
async def manual_recommendation_files(
    space_id: int = Query(gt=0), q: str = Query(default='', max_length=200),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
    service=Depends(_manual_service),
):
    return resp_200(await service.list_files(space_id, q.strip(), page, page_size))


@router.get('/recommendation/selected')
async def manual_recommendation_selected(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
    service=Depends(_manual_service),
):
    config = await ShougangPortalConfigService.get_config(tenant_id=_current_admin_tenant_id(admin_user))
    refs = [item.model_dump() for item in config.portal.recommendation.manual_items] if config else []
    return resp_200(await service.selected_items(refs))
