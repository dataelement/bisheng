from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.channel.domain.services.channel_authorization_service import (
    ChannelAuthorizationService,
)
from bisheng.common.errcode.channel import ChannelPermissionDeniedError

CHANNEL_ID = "channel-1"
CHANNEL_TENANT_ID = 42


class _User:
    user_id = 7
    tenant_id = 1

    def is_admin(self) -> bool:
        return False


def _query_service() -> SimpleNamespace:
    return SimpleNamespace(
        list_users=AsyncMock(),
        list_departments_children=AsyncMock(),
        search_departments=AsyncMock(),
        get_departments_path_tree=AsyncMock(),
        list_user_groups=AsyncMock(),
    )


def _channel_service(query_service: SimpleNamespace) -> ChannelAuthorizationService:
    service = ChannelAuthorizationService(
        channel_repository=MagicMock(),
        space_channel_member_repository=MagicMock(),
        membership_sync_service=MagicMock(),
        grant_subject_query_service=query_service,
    )
    service._require_manage_access = AsyncMock()
    service._resolve_channel_tenant = AsyncMock(return_value=CHANNEL_TENANT_ID)
    return service


@pytest.mark.parametrize(
    ("channel_method", "channel_kwargs", "query_method", "query_kwargs", "expected"),
    [
        (
            "list_grant_users",
            {"keyword": "ali", "page": 2, "page_size": 25},
            "list_users",
            {"keyword": "ali", "page": 2, "page_size": 25},
            [{"user_id": 11}],
        ),
        (
            "list_grant_departments_children",
            {"parent_id": 101},
            "list_departments_children",
            {"parent_id": 101},
            [{"id": 102}],
        ),
        (
            "search_grant_departments",
            {"keyword": "研发", "limit": 30},
            "search_departments",
            {"keyword": "研发", "limit": 30},
            {"roots": [{"id": 101}], "total_matches": 1, "truncated": False},
        ),
        (
            "get_grant_departments_path_tree",
            {"dept_id": 103},
            "get_departments_path_tree",
            {"dept_id": 103},
            {"roots": [{"id": 101}], "total_matches": 1, "truncated": False},
        ),
        (
            "list_grant_user_groups",
            {"keyword": "项目"},
            "list_user_groups",
            {"keyword": "项目"},
            [{"id": 201}],
        ),
    ],
)
async def test_channel_grant_subject_queries_delegate_with_channel_tenant_and_manage_gate(
    channel_method: str,
    channel_kwargs: dict,
    query_method: str,
    query_kwargs: dict,
    expected,
):
    query_service = _query_service()
    query_mock = getattr(query_service, query_method)
    query_mock.return_value = expected
    service = _channel_service(query_service)
    login_user = _User()

    result = await getattr(service, channel_method)(CHANNEL_ID, login_user, **channel_kwargs)

    assert result == expected
    service._require_manage_access.assert_awaited_once_with(CHANNEL_ID, login_user)
    service._resolve_channel_tenant.assert_awaited_once_with(CHANNEL_ID, login_user)
    query_mock.assert_awaited_once()
    delegated_kwargs = query_mock.await_args.kwargs
    assert delegated_kwargs["tenant_id"] == CHANNEL_TENANT_ID
    assert {key: delegated_kwargs[key] for key in query_kwargs} == query_kwargs
    if query_method == "list_users":
        assert delegated_kwargs.get("restrict_dept_path") is None
    if query_method in {
        "list_departments_children",
        "search_departments",
        "get_departments_path_tree",
    }:
        assert delegated_kwargs.get("restrict_root_path") is None
    if query_method == "list_user_groups":
        assert delegated_kwargs["login_user"] is login_user


@pytest.mark.parametrize(
    ("channel_method", "channel_kwargs"),
    [
        ("list_grant_users", {"keyword": "", "page": 1, "page_size": 20}),
        ("list_grant_departments_children", {"parent_id": None}),
        ("search_grant_departments", {"keyword": "研发", "limit": 50}),
        ("get_grant_departments_path_tree", {"dept_id": 103}),
        ("list_grant_user_groups", {"keyword": ""}),
    ],
)
async def test_channel_grant_subject_queries_propagate_manage_denial(
    channel_method: str,
    channel_kwargs: dict,
):
    query_service = _query_service()
    service = _channel_service(query_service)
    denial = ChannelPermissionDeniedError()
    service._require_manage_access = AsyncMock(side_effect=denial)
    login_user = _User()

    with pytest.raises(ChannelPermissionDeniedError) as exc_info:
        await getattr(service, channel_method)(CHANNEL_ID, login_user, **channel_kwargs)

    assert exc_info.value is denial
    service._resolve_channel_tenant.assert_not_awaited()
    for query_mock in vars(query_service).values():
        query_mock.assert_not_awaited()


async def test_channel_grant_subject_query_service_denial_is_not_swallowed():
    query_service = _query_service()
    denial = ChannelPermissionDeniedError()
    query_service.list_users.side_effect = denial
    service = _channel_service(query_service)

    with pytest.raises(ChannelPermissionDeniedError) as exc_info:
        await service.list_grant_users(CHANNEL_ID, _User(), keyword="ali", page=1, page_size=20)

    assert exc_info.value is denial


def test_channel_domain_does_not_import_permission_api_endpoint():
    source = inspect.getsource(inspect.getmodule(ChannelAuthorizationService))
    tree = ast.parse(source)
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "bisheng.permission.api.endpoints.resource_permission" not in imported_modules
