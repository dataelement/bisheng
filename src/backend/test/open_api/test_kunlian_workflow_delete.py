"""昆联开放接口 DELETE /workflows/{workflow_id} 路由与业务行为测试。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.flow import WorkflowRegistrationConflict
from bisheng.database.models.flow import FlowDao, FlowStatus
from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError
from bisheng.open_endpoints.api.endpoints import kunlian_workflow_api as routes
from bisheng.workflow.application import kunlian_workflow_management
from bisheng.workflow.application.kunlian_workflow_api import KunlianWorkflowApi


def _make_formal_app(management):
    app = FastAPI()
    capabilities = []

    class Access:
        @asynccontextmanager
        async def use_user(self, authorization, user_account, *, capability):
            capabilities.append(capability)
            yield SimpleNamespace(
                user=SimpleNamespace(user_id=17, tenant_id=7),
                credential=SimpleNamespace(integration_id="partner"),
            )

    app.state.kunlian_access_service = Access()
    app.state.kunlian_request_limiter = AsyncMock(return_value=None)
    app.state.kunlian_audit_service = SimpleNamespace(
        begin=AsyncMock(return_value=1), finish=AsyncMock(return_value=True)
    )
    app.state.kunlian_workflow_api = management
    app.include_router(routes.router)
    return app, capabilities


async def test_delete_workflow_route_requires_write_capability_and_returns_200():
    management = SimpleNamespace(delete=AsyncMock(return_value=None))
    app, capabilities = _make_formal_app(management)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.delete(
            "/api/v2/kunlian/workflows/wf-1",
            params={"user_account": "account-a"},
            headers={"Authorization": "Bearer synthetic"},
        )

    assert response.status_code == 200
    assert response.json() == {"status_code": 200, "status_message": "SUCCESS", "data": None}
    assert capabilities == ["write"]
    management.delete.assert_awaited_once()
    call_args = management.delete.await_args.args
    assert call_args[0].user_id == 17
    assert call_args[2] == "wf-1"


async def test_delete_workflow_offline_without_scope_deletes_flow_and_runs_hook(monkeypatch):
    user = SimpleNamespace(user_id=17, tenant_id=7)
    request = object()
    db_flow = SimpleNamespace(id="wf-1", tenant_id=7, flow_type=10, status=FlowStatus.OFFLINE.value)
    flow_service = SimpleNamespace(
        project_flow_delete=AsyncMock(return_value=None),
        delete_flow_hook=MagicMock(return_value=True),
    )
    repository = SimpleNamespace(delete_offline=MagicMock())
    api = KunlianWorkflowApi(
        target_reader=AsyncMock(return_value={"id": "wf-1", "tenant_id": 7, "flow_type": 10}),
        flow_service=flow_service,
        repository=repository,
    )

    delete_flow_mock = MagicMock(return_value=db_flow)
    monkeypatch.setattr(FlowDao, "get_flow_by_id", MagicMock(return_value=db_flow))
    monkeypatch.setattr(FlowDao, "delete_flow", delete_flow_mock)
    monkeypatch.setattr(kunlian_workflow_management, "workflow_scope", MagicMock(return_value=None))

    await api.delete(user, request, "wf-1")

    flow_service.project_flow_delete.assert_awaited_once_with(user, db_flow)
    delete_flow_mock.assert_called_once_with(db_flow)
    repository.delete_offline.assert_not_called()
    flow_service.delete_flow_hook.assert_called_once_with(request, user, db_flow)


async def test_delete_workflow_offline_with_scope_uses_delete_offline(monkeypatch):
    user = SimpleNamespace(user_id=17, tenant_id=7)
    request = object()
    scope = object()
    db_flow = SimpleNamespace(id="wf-1", tenant_id=7, flow_type=10, status=FlowStatus.OFFLINE.value)
    flow_service = SimpleNamespace(
        project_flow_delete=AsyncMock(return_value=None),
        delete_flow_hook=MagicMock(return_value=True),
    )
    repository = SimpleNamespace(delete_offline=MagicMock())
    api = KunlianWorkflowApi(
        target_reader=AsyncMock(return_value={"id": "wf-1", "tenant_id": 7, "flow_type": 10}),
        flow_service=flow_service,
        repository=repository,
    )

    delete_flow_mock = MagicMock()
    monkeypatch.setattr(FlowDao, "get_flow_by_id", MagicMock(return_value=db_flow))
    monkeypatch.setattr(FlowDao, "delete_flow", delete_flow_mock)
    monkeypatch.setattr(kunlian_workflow_management, "workflow_scope", MagicMock(return_value=scope))

    await api.delete(user, request, "wf-1")

    flow_service.project_flow_delete.assert_awaited_once_with(user, db_flow)
    repository.delete_offline.assert_called_once_with(scope, "wf-1")
    delete_flow_mock.assert_not_called()
    flow_service.delete_flow_hook.assert_called_once_with(request, user, db_flow)


async def test_delete_workflow_rejects_online_workflow(monkeypatch):
    user = SimpleNamespace(user_id=17, tenant_id=7)
    db_flow = SimpleNamespace(id="wf-1", tenant_id=7, flow_type=10, status=FlowStatus.ONLINE.value)
    flow_service = SimpleNamespace(
        project_flow_delete=AsyncMock(),
        delete_flow_hook=MagicMock(),
    )
    api = KunlianWorkflowApi(
        target_reader=AsyncMock(return_value={"id": "wf-1", "tenant_id": 7, "flow_type": 10}),
        flow_service=flow_service,
        repository=SimpleNamespace(delete_offline=MagicMock()),
    )

    monkeypatch.setattr(FlowDao, "get_flow_by_id", MagicMock(return_value=db_flow))

    with pytest.raises(WorkflowRegistrationConflict):
        await api.delete(user, object(), "wf-1")

    flow_service.project_flow_delete.assert_not_awaited()
    flow_service.delete_flow_hook.assert_not_called()


async def test_delete_workflow_rejects_missing_or_cross_tenant_target():
    user = SimpleNamespace(user_id=17, tenant_id=7)
    api = KunlianWorkflowApi(target_reader=AsyncMock(return_value={"id": "wf-1", "tenant_id": 99, "flow_type": 10}))

    with pytest.raises(KunlianAccessError) as exc_info:
        await api.delete(user, object(), "wf-1")

    assert exc_info.value.code == "NOT_FOUND"
