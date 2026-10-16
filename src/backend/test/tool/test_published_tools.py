"""Tenant facts precede permission shortcuts, including administrators."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.dsh import DshToolPermissionDeniedError, DshToolPublicationInvalidError
from bisheng.tool.domain.services.published_tools import PublishedToolService


@pytest.mark.parametrize("tool_tenant,category_tenant,deleted", [(1, 2, 0), (2, 1, 0), (2, 2, 1)])
async def test_invalid_facts_before_permission(tool_tenant, category_tenant, deleted):
    tool = SimpleNamespace(tenant_id=tool_tenant, is_delete=deleted, is_preset=0, type=5)
    category = SimpleNamespace(tenant_id=category_tenant, is_delete=0, is_preset=0, id=5)
    permission = AsyncMock(return_value=True)
    service = PublishedToolService(SimpleNamespace(snapshot=AsyncMock(return_value=(tool, category))), permission)
    with pytest.raises(DshToolPublicationInvalidError):
        await service.verify(2, 7, SimpleNamespace(), "edit")
    permission.assert_not_awaited()


async def test_denied_current_category_permission():
    tool = SimpleNamespace(tenant_id=2, is_delete=0, is_preset=0, type=5)
    category = SimpleNamespace(tenant_id=2, is_delete=0, is_preset=0, id=5)
    service = PublishedToolService(
        SimpleNamespace(snapshot=AsyncMock(return_value=(tool, category))), AsyncMock(return_value=False)
    )
    with pytest.raises(DshToolPermissionDeniedError):
        await service.verify(2, 7, SimpleNamespace(), "use")


@pytest.mark.parametrize("extra", ["model", "commands", "maxResults"])
async def test_search_publication_rejects_extra_or_required_controls(extra):
    """AC-05, AC-22: search permits query plus only optional maxResults."""
    from test.tool.test_published_schema import saved_schema

    tool, category = saved_schema({"query": {"type": "string"}, extra: {"type": "integer"}})
    tool.tenant_id, tool.is_delete, tool.is_preset, tool.type = 2, 0, 0, 5
    category.tenant_id, category.is_delete, category.is_preset, category.id = 2, 0, 0, 5
    service = PublishedToolService(
        SimpleNamespace(snapshot=AsyncMock(return_value=(tool, category))), AsyncMock(return_value=True)
    )
    with pytest.raises(DshToolPublicationInvalidError):
        await service.verify(2, 7, SimpleNamespace(), "edit", "bs_web_search")


async def test_permission_outage_is_unavailable_not_denial():
    """AC-12, AC-20: permission infrastructure failure remains distinguishable."""
    from bisheng.common.errcode.dsh import DshToolServiceUnavailableError
    from bisheng.common.errcode.permission import PermissionFGAUnavailableError

    tool = SimpleNamespace(tenant_id=2, is_delete=0, is_preset=0, type=5)
    category = SimpleNamespace(tenant_id=2, is_delete=0, is_preset=0, id=5)
    service = PublishedToolService(
        SimpleNamespace(snapshot=AsyncMock(return_value=(tool, category))),
        AsyncMock(side_effect=PermissionFGAUnavailableError()),
    )
    with pytest.raises(DshToolServiceUnavailableError):
        await service.verify(2, 7, SimpleNamespace(), "use")
