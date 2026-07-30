from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from loguru import logger

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.shougang_portal_config.domain.services.portal_asset_service import (
    PortalAssetValidationError,
    ShougangPortalAssetService,
)

router = APIRouter(
    prefix="/shougang-portal/assets",
    tags=["shougang-portal-assets"],
)


@router.post("/{category}")
async def upload_shougang_portal_asset(
    category: str,
    file: UploadFile = File(...),
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = int(get_current_tenant_id() or admin_user.tenant_id)
    try:
        result = await ShougangPortalAssetService.upload(
            file=file,
            category=category,
            tenant_id=tenant_id,
        )
        return resp_200(result)
    except PortalAssetValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        logger.exception(
            "portal asset upload failed tenant={} category={}",
            tenant_id,
            category,
        )
        raise HTTPException(status_code=503, detail="公共资源存储暂不可用") from exc
    finally:
        await file.close()
