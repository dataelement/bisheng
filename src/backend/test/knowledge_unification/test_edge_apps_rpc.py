"""Real HTTP entry gates use visibility while retaining identity and state."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.permission.application.identity import get_current_permission_actor
from test.open_api.test_dependencies import natural_person_principal, service_account_principal

FLOW = "a" * 32


async def post(app, path, body, headers=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://asgi", trust_env=False
    ) as client:
        return await client.post(path, json=body, headers=headers)


@pytest.fixture
def workstation(monkeypatch):
    from bisheng.workstation.api.endpoints import apps as module

    user = UserPayload(user_id=12, user_name="original", tenant_id=9, user_role=[], is_global_super=False)
    case = SimpleNamespace(module=module, user=user, visible=True)

    async def check(identity, *, resource_type, resource_id, action):
        assert identity is user and resource_id == FLOW
        assert resource_type in {"app", "workflow", "assistant"}
        return action == "visible" and case.visible

    case.check = AsyncMock(side_effect=check)
    case.touch, case.pin = Mock(), Mock(return_value=(None, True))
    case.apps = AsyncMock(
        return_value=(
            [{"id": FLOW, "status": module.FlowStatus.ONLINE.value, "flow_type": module.FlowType.WORKFLOW.value}],
            1,
        )
    )
    monkeypatch.setattr(module, "check_business_action", case.check)
    monkeypatch.setattr(module.UserLinkDao, "touch_user_link", case.touch)
    monkeypatch.setattr(module.UserLinkDao, "add_user_link", case.pin)
    monkeypatch.setattr(module.FlowDao, "aget_all_apps", case.apps)
    case.app = FastAPI()
    case.app.include_router(module.router, prefix="/api/v1/workstation")
    case.app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    return case


@pytest.mark.parametrize("kind", ["record", "pin"])
async def test_visible_without_use_reaches_original_workstation_write(workstation, kind):
    case = workstation
    response = await post(case.app, f"/api/v1/workstation/app/used/{kind}", {"flow_id": FLOW})
    assert response.status_code == 200 and response.json()["status_code"] == 200
    (case.touch if kind == "record" else case.pin).assert_called_once()
    case.check.assert_awaited_once()


@pytest.mark.parametrize("kind", ["record", "pin"])
async def test_hidden_app_never_writes_recent_or_pin(workstation, kind):
    case = workstation
    case.visible = False
    response = await post(case.app, f"/api/v1/workstation/app/used/{kind}", {"flow_id": FLOW})
    assert response.json()["status_code"] != 200
    case.touch.assert_not_called()
    case.pin.assert_not_called()


@pytest.mark.parametrize("fault", ["missing", "offline", "unsupported_type"])
async def test_pin_keeps_original_catalog_state_rules_before_permission(workstation, fault):
    case = workstation
    if fault == "missing":
        case.apps.return_value = ([], 0)
    elif fault == "offline":
        case.apps.return_value[0][0]["status"] = -100
    else:
        case.apps.return_value[0][0]["flow_type"] = 35
    error = case.module.UsedAppNotOnlineError if fault == "offline" else case.module.UsedAppNotFoundError
    with pytest.raises(error):
        await post(case.app, "/api/v1/workstation/app/used/pin", {"flow_id": FLOW})
    case.check.assert_not_awaited()
    case.pin.assert_not_called()


async def test_pin_preserves_original_idempotent_result(workstation):
    workstation.pin.return_value = (None, False)
    response = await post(workstation.app, "/api/v1/workstation/app/used/pin", {"flow_id": FLOW})
    assert response.json()["status_code"] == 200
    assert response.json()["status_message"] == "Already pinned"


@pytest.fixture
def rpc(monkeypatch):
    from bisheng.open_api.domain.services import identity_service
    from bisheng.open_api.domain.services.tenant_setting_service import TenantPatPolicy
    from bisheng.open_endpoints.api.endpoints import workflow as module

    case = SimpleNamespace(
        module=module, principal=service_account_principal(scopes=frozenset({"workflow:invoke"})), visible=True, seen=[]
    )
    user = UserPayload(user_id=12, user_name="original", tenant_id=9, user_role=[], is_global_super=False)

    async def check(operator, *, resource_type, resource_id, action):
        current = get_current_open_api_principal()
        actor = get_current_permission_actor()
        assert operator is case.operator
        assert resource_type == "workflow" and resource_id == FLOW
        assert actor.subject_id == current.authorization_subject_id
        assert actor.subject_type == current.authorization_subject_type
        assert actor.current_tenant_id == current.tenant_id == operator.tenant_id
        case.seen.append((current, actor))
        if action != "visible" or not case.visible:
            raise PermissionDeniedError()

    def operator():
        current = get_current_open_api_principal()
        case.operator = user.model_copy(update={"user_id": current.effective_user_id or current.resource_owner_user_id})
        return case.operator

    async def events(invocation, *, stream):
        assert invocation is case.prepare.return_value and stream is False
        if False:
            yield None

    case.check = AsyncMock(side_effect=check)
    case.workflow = AsyncMock(return_value=SimpleNamespace(name="original"))
    case.prepare = AsyncMock(return_value=SimpleNamespace(session_id="original-session", start_time=0))
    case.lease = AsyncMock(return_value=(module.SlotOutcome.SKIPPED, None))
    monkeypatch.setattr(module, "get_open_api_operator", operator)
    monkeypatch.setattr(module, "require_business_action", case.check)
    monkeypatch.setattr(module.PublishedWorkflowService, "get_workflow", case.workflow)
    monkeypatch.setattr(module.PublishedWorkflowService, "prepare_invocation", case.prepare)
    monkeypatch.setattr(module.PublishedWorkflowService, "iter_events", events)
    monkeypatch.setattr(module.DepartmentFlowService, "ensure_lease", case.lease)
    monkeypatch.setattr(module.DepartmentFlowService, "stop_renewal", AsyncMock())
    monkeypatch.setattr(module.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer", AsyncMock(side_effect=lambda authorization: case.principal)
    )
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.TenantSettingService.get_policy",
        AsyncMock(return_value=TenantPatPolicy(True, 1)),
    )
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", True)
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(
        identity_service.OwnerRepository,
        "get_active_natural_person",
        AsyncMock(return_value=SimpleNamespace(tenant_id=9)),
    )
    monkeypatch.setattr(identity_service.DelegateScopeService, "target_allowed", AsyncMock(return_value=True))
    case.app = FastAPI()
    register_open_api_exception_handlers(case.app)
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])
    router.include_router(module.router)
    case.app.include_router(router)
    return case


@pytest.mark.parametrize("kind", ["sak", "pat", "obo"])
async def test_real_rpc_dependency_keeps_original_subject_scope_and_snapshot(rpc, kind):
    headers = {"Authorization": "Bearer original"}
    if kind == "pat":
        rpc.principal = natural_person_principal().model_copy(update={"scopes": frozenset({"workflow:invoke"})})
    elif kind == "obo":
        rpc.principal = rpc.principal.model_copy(update={"scopes": frozenset({"workflow:invoke", "delegate"})})
        headers["X-On-Behalf-Of"] = "44"
    response = await post(rpc.app, "/api/v2/workflow/invoke", {"workflow_id": FLOW, "stream": False}, headers)
    assert response.status_code == 200 and response.json()["data"] == {"session_id": "original-session", "events": []}
    current, actor = rpc.seen[0]
    snapshot = rpc.prepare.await_args.kwargs["execution_snapshot"]
    assert (snapshot.authorization_subject_type, snapshot.authorization_subject_id) == (
        actor.subject_type,
        actor.subject_id,
    )
    assert rpc.prepare.await_args.kwargs["operator"] is rpc.operator
    assert snapshot.mode == ("D" if kind == "obo" else "S")
    assert (current.authorization_subject_type, current.authorization_subject_id) == (
        ("user", 44)
        if kind == "obo"
        else (rpc.principal.authorization_subject_type, rpc.principal.authorization_subject_id)
    )


@pytest.mark.parametrize("fault", ["scope", "hidden", "unpublished", "department"])
async def test_rpc_failures_keep_original_gates_and_never_enqueue(rpc, fault):
    if fault == "scope":
        rpc.principal = rpc.principal.model_copy(update={"scopes": frozenset()})
    elif fault == "hidden":
        rpc.visible = False
    elif fault == "unpublished":
        rpc.workflow.side_effect = PermissionDeniedError()
    else:
        rpc.lease.return_value = (rpc.module.SlotOutcome.REJECTED, None)
    response = await post(
        rpc.app, "/api/v2/workflow/invoke", {"workflow_id": FLOW, "stream": False}, {"Authorization": "Bearer original"}
    )
    expected = (
        26003
        if fault == "scope"
        else (
            rpc.module.DepartmentDailyChatConcurrentLimitError.Code
            if fault == "department"
            else PermissionDeniedError.Code
        )
    )
    assert response.json()["status_code"] == expected
    if fault == "scope":
        assert response.status_code == 403
        rpc.workflow.assert_not_awaited()
    elif fault == "unpublished":
        rpc.check.assert_not_awaited()
    rpc.prepare.assert_not_awaited()
