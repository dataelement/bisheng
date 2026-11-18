"""Discovery and subscription must not consume another tenant's channels."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.core.context.tenant import is_strict_tenant_filter, strict_tenant_filter


def _service(method):
    path = Path(__file__).resolve().parents[2] / "bisheng/channel/domain/services/channel_service.py"
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ChannelService")
    cls.body = [node for node in cls.body if getattr(node, "name", None) == method]
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls],
        type_ignores=[],
    )
    namespace = {
        "strict_tenant_filter": strict_tenant_filter,
        "ChannelNotFoundError": ChannelNotFoundError,
        "ChannelSquarePageResponse": SimpleNamespace,
        "SubscriptionStatusEnum": SimpleNamespace(SUBSCRIBED="subscribed"),
    }
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["ChannelService"]()


@pytest.mark.parametrize("recommended", [False, True])
async def test_channel_discovery_queries_are_tenant_local(recommended):
    async def query(**kwargs):
        assert is_strict_tenant_filter(), "Discovery must exclude channels from other tenants"
        return []

    async def count(**kwargs):
        assert is_strict_tenant_filter(), "Count and page must share the tenant boundary"
        return 0

    method = "get_recommended_channels" if recommended else "get_channel_square"
    service = _service(method)
    service.channel_repository = SimpleNamespace(
        find_square_channels=AsyncMock(side_effect=query),
        count_square_channels=AsyncMock(side_effect=count),
        find_public_recommend_channels=AsyncMock(side_effect=query),
    )
    service._build_square_items = AsyncMock(return_value=[])
    user = SimpleNamespace(user_id=841, tenant_id=69)
    if recommended:
        await service.get_recommended_channels(user)
    else:
        await service.get_channel_square(None, 1, 20, user)
    assert not is_strict_tenant_filter()


async def test_cross_tenant_subscription_rejected_before_access_or_membership():
    service = _service("subscribe_channel")
    service.channel_repository = SimpleNamespace(
        find_channels_by_ids=AsyncMock(return_value=[SimpleNamespace(tenant_id=1)])
    )
    service._has_channel_subscription_access = AsyncMock(return_value=True)
    with pytest.raises(ChannelNotFoundError):
        await service.subscribe_channel(
            SimpleNamespace(channel_id="root-channel"), SimpleNamespace(user_id=841, tenant_id=69)
        )
    service._has_channel_subscription_access.assert_not_awaited()
