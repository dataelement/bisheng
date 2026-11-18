"""Tool enumeration/execution retain visibility and account boundaries. AC-79/82/83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.application import business_authorization as business
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_ALL
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.tool.domain.services.tool import ToolServices
from test.knowledge_unification.test_perm_runtime import decision


async def test_default_tool_list_keeps_visible_only_api_preset_and_mcp(monkeypatch):
    rows = [
        GptsToolsType(id=10 + kind, tenant_id=101, user_id=7, name=f"tool-{kind}", is_preset=kind) for kind in (0, 1, 2)
    ]
    actor = PermissionActor(user_id=7, tenant_id=101)
    runtime = SimpleNamespace(
        list_visible_objects=AsyncMock(return_value=SimpleNamespace(object_ids=("10", "11", "12")))
    )
    decisions = AsyncMock(return_value={str(row.id): frozenset({"visible"}) for row in rows})
    monkeypatch.setattr("bisheng.tool.domain.services.tool.get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr("bisheng.tool.domain.services.tool.resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr("bisheng.tool.domain.services.tool.batch_check_business_actions", decisions)
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.GptsToolsDao.aget_tenant_tool_type", AsyncMock(return_value=rows)
    )
    monkeypatch.setattr("bisheng.tool.domain.services.tool.GptsToolsDao.aget_list_by_type", AsyncMock(return_value=[]))
    token = set_current_tenant_id(101)
    try:
        result = await ToolServices(login_user=UserPayload(user_id=7, tenant_id=101, user_role=[])).get_tool_list()
    finally:
        current_tenant_id.reset(token)
    assert [row.id for row in result] == [10, 11, 12]
    assert decisions.await_args.kwargs["actions"] == ("visible",)
    assert all(not row.write and not row.delete for row in result)


@pytest.fixture
def execution(monkeypatch):
    runtime, fga = decision()
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=101, resource_type="tool", resource_id="10", resource_version=1, context_version="tool-current"
    )
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(
        business,
        "get_f048_resource_registry",
        AsyncMock(return_value=SimpleNamespace(resolve=AsyncMock(return_value=target))),
    )
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "bisheng.tool.domain.services.executor.GptsToolsDao.aget_one_tool",
        AsyncMock(return_value=SimpleNamespace(id=1, type=10)),
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.executor.GptsToolsDao.aget_one_tool_type",
        AsyncMock(return_value=SimpleNamespace(id=10, tenant_id=101)),
    )
    initialize = Mock(return_value="initialized-tool")
    monkeypatch.setattr(ToolExecutor, "_init_by_tool_and_type_with_context", initialize)
    return SimpleNamespace(fga=fga, initialize=initialize)


async def invoke():
    return await ToolExecutor.init_by_tool_id(
        tool_id=1, app_id="desktop-work", app_name="Work", app_type=ApplicationTypeEnum.DSH_DESKTOP, user_id=7
    )


@pytest.mark.parametrize("subject_type", ["user", "service_account"])
async def test_executor_preserves_contextual_identity(execution, subject_type):
    actor = PermissionActor(subject_type=subject_type, subject_id=42, tenant_id=101)
    token = set_current_permission_actor(actor)
    try:
        assert await invoke() == "initialized-tool"
    finally:
        reset_current_permission_actor(token)
    assert execution.fga.check.await_args.kwargs["user"] == actor.fga_subject
    assert execution.fga.check.await_args.kwargs["relation"] == "visible"
    execution.initialize.assert_called_once()


@pytest.mark.parametrize("denial", ["hidden", "tenant", "scope"])
async def test_executor_denies_before_provider_initialization(execution, monkeypatch, denial):
    execution.fga.check.return_value = denial != "hidden"
    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_action_service.get_data_scope_resolver", lambda: None
    )
    actor = PermissionActor(
        user_id=42,
        tenant_id=202 if denial == "tenant" else 101,
        data_scope="OWNED" if denial == "scope" else DATA_SCOPE_ALL,
    )
    token = set_current_permission_actor(actor)
    try:
        with pytest.raises(PersonalTokenDataScopeError if denial == "scope" else PermissionError):
            await invoke()
    finally:
        reset_current_permission_actor(token)
    execution.initialize.assert_not_called()
