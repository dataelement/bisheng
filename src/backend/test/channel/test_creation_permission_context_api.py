"""Channel creation permission context and candidate API contracts."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.api.endpoints import channel_manager as endpoints
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelCreateLimitExceededError


class _Prospective:
    def __init__(self) -> None:
        self.calls = []

    async def get_context(self, **kwargs):
        self.calls.append(("context", kwargs))
        return {"catalog_release_id": 42, "can_configure_initial_permissions": True, "grantable_models": []}

    async def list_users(self, **kwargs):
        self.calls.append(("users", kwargs))
        return {"data": [], "total": 0}

    async def list_user_groups(self, **kwargs):
        self.calls.append(("groups", kwargs))
        return {"data": [], "total": 0}

    async def list_department_children(self, **kwargs):
        self.calls.append(("children", kwargs))
        return []

    async def search_departments(self, **kwargs):
        self.calls.append(("search", kwargs))
        return {"roots": [], "total_matches": 0, "truncated": False}

    async def get_department_path(self, **kwargs):
        self.calls.append(("path", kwargs))
        return {"roots": [], "total_matches": 0, "truncated": False}


def _service(prospective: _Prospective):
    channels = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[]))
    members = SimpleNamespace(find_channel_memberships=AsyncMock(return_value=[]))
    service = ChannelService(
        channel_repository=channels,
        space_channel_member_repository=members,
        channel_info_source_repository=SimpleNamespace(),
        prospective_grant_application=prospective,
    )
    return service, channels, members


async def test_creation_context_and_candidates_use_server_tenant_and_same_shape() -> None:
    prospective = _Prospective()
    service, _, _ = _service(prospective)
    login_user = SimpleNamespace(user_id=7, tenant_id=3)
    with (
        patch(
            "bisheng.channel.domain.services.channel_service.QuotaService.get_effective_quota",
            new=AsyncMock(return_value=-1),
        ),
        patch(
            "bisheng.channel.domain.services.channel_service.resolve_permission_actor",
            new=AsyncMock(return_value=SimpleNamespace(user_id=7, current_tenant_id=3)),
        ),
    ):
        context = await service.get_creation_permission_context(login_user)
        users = await service.list_creation_grant_users(login_user, keyword="A", page=2, page_size=25)
        await service.list_creation_grant_user_groups(login_user, keyword="G", page=1, page_size=20)
        await service.list_creation_grant_department_children(login_user, parent_id=5)
        await service.search_creation_grant_departments(login_user, keyword="R", limit=10)
        await service.get_creation_grant_department_path(login_user, 9)

    assert context["catalog_release_id"] == 42
    assert users == {"data": [], "total": 0}
    assert [name for name, _ in prospective.calls] == [
        "context",
        "users",
        "groups",
        "children",
        "search",
        "path",
    ]
    assert all(call["tenant_id"] == 3 for _, call in prospective.calls)
    assert all(call["resource_type"] == "channel" for _, call in prospective.calls)


async def test_channel_quota_fails_closed_before_permission_directory() -> None:
    prospective = _Prospective()
    service, channels, members = _service(prospective)
    members.find_channel_memberships.return_value = [SimpleNamespace(business_id="channel-1")]
    channels.find_channels_by_ids.return_value = [SimpleNamespace(id="channel-1")]
    with patch(
        "bisheng.channel.domain.services.channel_service.QuotaService.get_effective_quota",
        new=AsyncMock(return_value=1),
    ):
        with pytest.raises(ChannelCreateLimitExceededError):
            await service.get_creation_permission_context(SimpleNamespace(user_id=7, tenant_id=3))

    assert prospective.calls == []


def test_creation_routes_exist_and_do_not_accept_tenant_id() -> None:
    paths = {route.path for route in endpoints.router.routes}
    assert {
        "/manager/creation-permission-context",
        "/manager/creation-grant-subjects/users",
        "/manager/creation-grant-subjects/user-groups",
        "/manager/creation-grant-subjects/departments/children",
        "/manager/creation-grant-subjects/departments/search",
        "/manager/creation-grant-subjects/departments/{department_id}/path-tree",
    } <= paths
    for endpoint in (
        endpoints.get_creation_permission_context,
        endpoints.list_creation_grant_users,
        endpoints.list_creation_grant_user_groups,
        endpoints.list_creation_grant_department_children,
        endpoints.search_creation_grant_departments,
        endpoints.get_creation_grant_department_path,
    ):
        assert "tenant_id" not in inspect.signature(endpoint).parameters
