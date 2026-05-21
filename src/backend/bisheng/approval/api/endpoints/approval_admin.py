from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
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


class RouteUpdateReq(BaseModel):
    route_name: str | None = None
    route_type: str | None = None
    sort_order: int | None = None
    flow_definition_id: int | None = None
    match_config: dict | None = None
    enabled: bool | None = None


class FlowCreateReq(BaseModel):
    flow_name: str
    is_active: bool = True


class FlowUpdateReq(BaseModel):
    flow_name: str | None = None
    is_active: bool | None = None


class NodeCreateReq(BaseModel):
    node_name: str
    node_order: int = 0
    node_mode: str
    approver_config: dict = Field(default_factory=dict)
    extra_config: dict = Field(default_factory=dict)


class NodeUpdateReq(BaseModel):
    node_name: str | None = None
    node_order: int | None = None
    node_mode: str | None = None
    approver_config: dict | None = None
    extra_config: dict | None = None


class RouteReorderReq(BaseModel):
    ordered_route_ids: list[int]


class NodeListReq(BaseModel):
    nodes: list[dict]


def _ensure_admin(login_user: UserPayload) -> None:
    if not login_user.is_admin():
        raise HTTPException(status_code=403, detail='Admin access required')


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


@router.put('/routes/{route_rule_id}')
async def update_route(
    route_rule_id: int,
    req: RouteUpdateReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalScenarioAdminService.update_route(
            tenant_id=login_user.tenant_id,
            route_rule_id=route_rule_id,
            payload=req.model_dump(exclude_none=True),
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


@router.put('/flows/{flow_definition_id}')
async def update_flow(
    flow_definition_id: int,
    req: FlowUpdateReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalScenarioAdminService.update_flow(
            tenant_id=login_user.tenant_id,
            flow_definition_id=flow_definition_id,
            payload=req.model_dump(exclude_none=True),
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


@router.put('/nodes/{node_definition_id}')
async def update_node(
    node_definition_id: int,
    req: NodeUpdateReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalScenarioAdminService.update_node(
            tenant_id=login_user.tenant_id,
            node_definition_id=node_definition_id,
            payload=req.model_dump(exclude_none=True),
        )
    )


@router.delete('/scenarios/{scenario_id}')
async def delete_scenario(scenario_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    await ApprovalScenarioAdminService.delete_scenario(tenant_id=login_user.tenant_id, scenario_id=scenario_id)
    return resp_200({'deleted': scenario_id})


@router.delete('/routes/{route_rule_id}')
async def delete_route(route_rule_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    await ApprovalScenarioAdminService.delete_route(tenant_id=login_user.tenant_id, route_rule_id=route_rule_id)
    return resp_200({'deleted': route_rule_id})


@router.patch('/scenarios/{scenario_id}/routes/reorder')
async def reorder_routes(
    scenario_id: int,
    req: RouteReorderReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    await ApprovalScenarioAdminService.reorder_routes(
        tenant_id=login_user.tenant_id,
        scenario_id=scenario_id,
        ordered_route_ids=req.ordered_route_ids,
    )
    return resp_200({'reordered': req.ordered_route_ids})


@router.delete('/flows/{flow_definition_id}')
async def delete_flow(flow_definition_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    _ensure_admin(login_user)
    await ApprovalScenarioAdminService.delete_flow(tenant_id=login_user.tenant_id, flow_definition_id=flow_definition_id)
    return resp_200({'deleted': flow_definition_id})


@router.get('/flows/{flow_definition_id}/versions/{flow_version_id}')
async def get_flow_version(
    flow_definition_id: int,
    flow_version_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalScenarioAdminService.get_flow_version(
            tenant_id=login_user.tenant_id,
            flow_definition_id=flow_definition_id,
            flow_version_id=flow_version_id,
        )
    )


@router.put('/flows/{flow_definition_id}/nodes')
async def set_flow_nodes(
    flow_definition_id: int,
    req: NodeListReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _ensure_admin(login_user)
    return resp_200(
        await ApprovalScenarioAdminService.set_flow_nodes(
            tenant_id=login_user.tenant_id,
            flow_definition_id=flow_definition_id,
            nodes_payload=req.nodes,
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
