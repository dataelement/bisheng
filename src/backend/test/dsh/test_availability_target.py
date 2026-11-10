"""Account switches must authorize only the target tool's category."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionInvalidResourceError,
    PermissionPublishNotReadyError,
    PermissionServiceUnavailableError,
)
from bisheng.core.context import tenant
from bisheng.dsh.domain.services.capability_catalog import CapabilityCatalogService
from bisheng.permission.application import business_authorization
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService


@pytest.fixture
def target(monkeypatch):
    monkeypatch.setattr(tenant, "get_current_tenant_id", lambda: 2)
    row = SimpleNamespace(id=124, type=14, tenant_id=2, is_delete=0, is_preset=2)
    category = SimpleNamespace(id=14, tenant_id=2, is_delete=0)
    load = AsyncMock(return_value=row)
    load_category = AsyncMock(return_value=category)
    permission = AsyncMock(return_value=True)
    save = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool", load)
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", load_category)
    monkeypatch.setattr(business_authorization, "check_business_action", permission)
    monkeypatch.setattr(UserToolAvailabilityService, "save", save)
    # Any regression to full catalog discovery must fail, not silently use a mock list.
    module = ModuleType("bisheng.tool.domain.services.tool")
    module.ToolServices = AsyncMock(side_effect=AssertionError("Full tool enumeration is forbidden"))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    user = SimpleNamespace(user_id=7, tenant_id=2, is_global_super=False)
    service = CapabilityCatalogService(user, SimpleNamespace(publications=SimpleNamespace(audit=audit)))
    return SimpleNamespace(
        service=service,
        row=row,
        category=category,
        load=load,
        load_category=load_category,
        permission=permission,
        save=save,
        audit=audit,
    )


@pytest.mark.parametrize("kind", [0, 1, 2])
@pytest.mark.parametrize("enabled", [False, True])
async def test_switch_checks_only_owning_category(target, kind, enabled):
    target.row.is_preset = kind
    assert await target.service.set_availability(124, enabled) == {"tool_id": 124, "enabled": enabled}
    target.load.assert_awaited_once_with(124)
    target.load_category.assert_awaited_once_with(14)
    target.permission.assert_awaited_once_with(target.service.user, resource_type="tool", resource_id=14, action="use")
    target.save.assert_awaited_once_with(124, enabled)
    target.audit.assert_awaited_once_with(target.service.user, "availability", "tool", 124, {"enabled": enabled})


@pytest.mark.parametrize(
    "invalid",
    [
        "missing_tool",
        "deleted_tool",
        "foreign_tool",
        "unsupported",
        "missing_category",
        "deleted_category",
        "foreign_category",
    ],
)
async def test_invalid_target_never_authorizes_or_writes(target, invalid):
    if invalid == "missing_tool":
        target.load.return_value = None
    elif invalid == "deleted_tool":
        target.row.is_delete = 1
    elif invalid == "foreign_tool":
        target.row.tenant_id = 3
    elif invalid == "unsupported":
        target.row.is_preset = 99
    elif invalid == "missing_category":
        target.load_category.return_value = None
    elif invalid == "deleted_category":
        target.category.is_delete = 1
    elif invalid == "foreign_category":
        target.category.tenant_id = 3
    with pytest.raises(HTTPException) as error:
        await target.service.set_availability(124, False)
    assert error.value.status_code == 404
    target.permission.assert_not_awaited()
    target.save.assert_not_awaited()
    target.audit.assert_not_awaited()


async def test_revoked_permission_preserves_not_found_response(target):
    target.permission.return_value = False
    with pytest.raises(HTTPException) as error:
        await target.service.set_availability(124, True)
    assert error.value.status_code == 404
    target.save.assert_not_awaited()
    target.audit.assert_not_awaited()


@pytest.mark.parametrize("error_type", [RuntimeError, PermissionServiceUnavailableError])
async def test_permission_failure_is_not_swallowed_or_saved(target, error_type):
    target.permission.side_effect = error_type()
    with pytest.raises(error_type):
        await target.service.set_availability(124, False)
    target.save.assert_not_awaited()
    target.audit.assert_not_awaited()


@pytest.mark.parametrize(
    "error_type", [InvalidCatalogActionError, PermissionInvalidResourceError, PermissionPublishNotReadyError]
)
async def test_unavailable_permission_target_keeps_404(target, error_type):
    target.permission.side_effect = error_type()
    with pytest.raises(HTTPException) as error:
        await target.service.set_availability(124, True)
    assert error.value.status_code == 404
    target.save.assert_not_awaited()
    target.audit.assert_not_awaited()
