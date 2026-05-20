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


class ScenarioUpdateReq(BaseModel):
    scenario_name: str | None = None
    enabled: bool | None = None
    display_name: str | None = None


class ExceptionRetryReq(BaseModel):
    action: str = Field(default='retry')
    approver_user_ids: list[int] = Field(default_factory=list)


class RouteCreateReq(BaseModel):
    route_name: str
    route_type: str
    sort_order: int = 0
    flow_definition_id: int | None = None
    match_config: dict = Field(default_factory=dict)


class FlowCreateReq(BaseModel):
    flow_code: str
    flow_name: str
    is_active: bool = True


class NodeCreateReq(BaseModel):
    node_code: str
    node_name: str
    node_order: int = 0
    node_mode: str
    approver_config: dict = Field(default_factory=dict)
    extra_config: dict = Field(default_factory=dict)


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
    return resp_200(
        await ApprovalScenarioAdminService.create_scenario(
            tenant_id=login_user.tenant_id,
            payload=req.model_dump(),
            operator_user_id=login_user.user_id,
            operator_user_name=login_user.user_name,
        )
    )


@router.put('/scenarios/{scenario_id}')
async def update_scenario(
    scenario_id: int,
    req: ScenarioUpdateReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalScenarioAdminService.update_scenario(
            tenant_id=login_user.tenant_id,
            scenario_id=scenario_id,
            payload=req.model_dump(exclude_none=True),
        )
    )


@router.get('/scenarios/{scenario_id}/routes')
async def list_routes(scenario_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    return resp_200(await ApprovalScenarioAdminService.list_routes(tenant_id=login_user.tenant_id, scenario_id=scenario_id))


@router.post('/scenarios/{scenario_id}/routes')
async def create_route(
    scenario_id: int,
    req: RouteCreateReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalScenarioAdminService.create_route(
            tenant_id=login_user.tenant_id,
            scenario_id=scenario_id,
            payload=req.model_dump(),
        )
    )


@router.get('/scenarios/{scenario_id}/flows')
async def list_flows(scenario_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    return resp_200(await ApprovalScenarioAdminService.list_flows(tenant_id=login_user.tenant_id, scenario_id=scenario_id))


@router.post('/scenarios/{scenario_id}/flows')
async def create_flow(
    scenario_id: int,
    req: FlowCreateReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalScenarioAdminService.create_flow(
            tenant_id=login_user.tenant_id,
            scenario_id=scenario_id,
            payload=req.model_dump(),
        )
    )


@router.get('/flows/{flow_definition_id}/nodes')
async def list_nodes(flow_definition_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    return resp_200(await ApprovalScenarioAdminService.list_nodes(tenant_id=login_user.tenant_id, flow_definition_id=flow_definition_id))


@router.post('/flows/{flow_definition_id}/nodes')
async def create_node(
    flow_definition_id: int,
    req: NodeCreateReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalScenarioAdminService.create_node(
            tenant_id=login_user.tenant_id,
            flow_definition_id=flow_definition_id,
            payload=req.model_dump(),
        )
    )


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
            approver_user_ids=req.approver_user_ids,
        )
    )
