from fastapi import APIRouter, Body, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import AutomotiveSheetIntroSyncConfig
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_admin_service import (
    AutomotiveSheetIntroSyncAdminService,
)

router = APIRouter(prefix="/admin/developer-tokens/automotive-sheet-intro-sync", tags=["developer-token"])


@router.get("")
async def get_automotive_sheet_intro_sync_config(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await AutomotiveSheetIntroSyncAdminService.get_config(login_user)
    return resp_200(data=data)


@router.put("")
async def update_automotive_sheet_intro_sync_config(
    payload: AutomotiveSheetIntroSyncConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await AutomotiveSheetIntroSyncAdminService.save_config(login_user, payload)
    return resp_200(data=data)


@router.post("/test")
async def test_automotive_sheet_intro_sync(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await AutomotiveSheetIntroSyncAdminService.trigger_test(login_user)
    return resp_200(data=data)


@router.get("/runs")
async def list_automotive_sheet_intro_sync_runs(
    page: int = Query(1, ge=1),
    limit: int = Query(5, ge=1, le=200),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await AutomotiveSheetIntroSyncAdminService.list_runs(login_user, page=page, limit=limit)
    return resp_200(data=data)
