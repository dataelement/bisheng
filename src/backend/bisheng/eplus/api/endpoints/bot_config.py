"""Assistant-bound E+ robot configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.eplus.domain.schemas.config import EPlusBotConfigUpsert
from bisheng.eplus.domain.services.bot_config_service import EPlusBotConfigService
from bisheng.eplus.infrastructure.config_adapters import (
    BusinessAssistantPermissionChecker,
    RedisConfigNotifier,
    SqlAssistantReader,
    SqlSpaceReader,
)
from bisheng.eplus.infrastructure.credential_store import MinioCertificateStore, PlatformCredentialStore

router = APIRouter()


async def get_eplus_bot_config_service(
    session: AsyncSession = Depends(get_db_session),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> EPlusBotConfigService:
    minio = await get_minio_storage()
    redis_client = await get_redis_client()
    return EPlusBotConfigService(
        session,
        permission_checker=BusinessAssistantPermissionChecker(login_user),
        assistant_reader=SqlAssistantReader(session),
        space_reader=SqlSpaceReader(session),
        credential_store=PlatformCredentialStore(),
        certificate_store=MinioCertificateStore(minio),
        notifier=RedisConfigNotifier(redis_client),
    )


def _tenant_id(login_user: UserPayload) -> int:
    return int(get_current_tenant_id() or login_user.tenant_id)


@router.get("/assistants/{assistant_id}/bot")
async def get_bot_config(
    assistant_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: EPlusBotConfigService = Depends(get_eplus_bot_config_service),
):
    data = await service.get_config(
        tenant_id=_tenant_id(login_user),
        assistant_id=assistant_id,
        operator_id=login_user.user_id,
    )
    return resp_200(data=data)


@router.put("/assistants/{assistant_id}/bot")
async def save_bot_config(
    assistant_id: str,
    data: EPlusBotConfigUpsert,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: EPlusBotConfigService = Depends(get_eplus_bot_config_service),
):
    try:
        view = await service.save_config(
            tenant_id=_tenant_id(login_user),
            assistant_id=assistant_id,
            operator_id=login_user.user_id,
            request=data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return resp_200(data=view)


@router.get("/assistants/{assistant_id}/bot/spaces")
async def list_bindable_spaces(
    assistant_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: EPlusBotConfigService = Depends(get_eplus_bot_config_service),
):
    spaces = await service.list_bindable_spaces(
        tenant_id=_tenant_id(login_user),
        assistant_id=assistant_id,
        operator_id=login_user.user_id,
    )
    return resp_200(data=spaces)


@router.delete("/assistants/{assistant_id}/bot")
async def disable_bot_config(
    assistant_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: EPlusBotConfigService = Depends(get_eplus_bot_config_service),
):
    disabled = await service.disable_config(
        tenant_id=_tenant_id(login_user),
        assistant_id=assistant_id,
        operator_id=login_user.user_id,
    )
    return resp_200(data=disabled)
