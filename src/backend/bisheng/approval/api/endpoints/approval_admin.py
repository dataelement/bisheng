from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bisheng.approval.domain.services.approval_exception_service import ApprovalExceptionService
from bisheng.approval.domain.services.approval_scenario_admin_service import ApprovalScenarioAdminService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix='/approval/admin', tags=['approval'])


class ScenarioUpsertReq(BaseModel):
    scenario_code: str
    scenario_name: str
    enabled: bool = False


class ExceptionRetryReq(BaseModel):
    action: str = Field(default='retry')


def _ensure_admin(login_user: UserPayload) -> None:
    if not login_user.is_admin():
        raise PermissionError('admin only')


@router.get('/scenario-presets')
async def list_scenario_presets(login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    return resp_200(await ApprovalScenarioAdminService.list_presets())


@router.get('/scenarios')
async def list_scenarios(login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    return resp_200(await ApprovalScenarioAdminService.list_scenarios(tenant_id=login_user.tenant_id))


@router.post('/scenarios')
async def create_scenario(req: ScenarioUpsertReq, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    return resp_200(await ApprovalScenarioAdminService.create_scenario(tenant_id=login_user.tenant_id, payload=req.model_dump()))


@router.get('/scenarios/{scenario_id}/routes')
async def list_routes(scenario_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    return resp_200(await ApprovalScenarioAdminService.list_routes(tenant_id=login_user.tenant_id, scenario_id=scenario_id))


@router.get('/exceptions')
async def list_exceptions(login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    return resp_200(await ApprovalScenarioAdminService.list_open_exceptions(tenant_id=login_user.tenant_id))


@router.post('/exceptions/{exception_id}/retry')
async def retry_exception(
    exception_id: int,
    req: ExceptionRetryReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalExceptionService.retry_exception_api(
            exception_id=exception_id,
            action=req.action,
            operator_user_id=login_user.user_id,
        )
    )

