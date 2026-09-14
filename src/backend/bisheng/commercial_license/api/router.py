from datetime import datetime

from fastapi import APIRouter, Body, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.commercial_license.domain.mappers import map_gateway_payload
from bisheng.commercial_license.domain.models.license_info import LicenseInfo  # noqa: F401 — register table
from bisheng.commercial_license.domain.repositories.license_info_repository import LicenseInfoRepository
from bisheng.commercial_license.domain.services.aggregator import list_license_status
from bisheng.commercial_license.domain.services.etl_sync import sync_etl_license
from bisheng.commercial_license.domain.services.upsert import upsert_mapped
from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.commercial_license import CommercialLicenseInvalidPayloadError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200

router = APIRouter(prefix="/commercial-licenses", tags=["CommercialLicense"])


@router.get("/status", response_model=UnifiedResponseModel)
async def get_commercial_license_status(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    now = datetime.now()
    if not bool(getattr(login_user, "is_global_super", False)):
        return resp_200({"licenses": [], "checked_at": now.isoformat()})
    repo = LicenseInfoRepository(session)

    async def _etl_sync() -> None:
        await sync_etl_license(repo)

    data = await list_license_status(now, repo=repo, etl_sync=_etl_sync)
    return resp_200(data)


@router.post("/gateway", response_model=UnifiedResponseModel)
async def report_gateway_license(
    body: dict = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    if not bool(getattr(login_user, "is_global_super", False)):
        return resp_200({})
    try:
        mapped = map_gateway_payload(body)
    except (TypeError, ValueError):
        raise CommercialLicenseInvalidPayloadError()
    repo = LicenseInfoRepository(session)
    await upsert_mapped(repo, mapped)
    return resp_200({})
