from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.common.cursor import CursorDecodeError
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.developer_token import DeveloperTokenInvalidFileSyncTargetCursorError
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.schemas import (
    DeveloperTokenFileSyncOptions,
    DeveloperTokenFileSyncTargetChildren,
    FileSyncOptionBusinessDomain,
    FileSyncOptionCategory,
    FileSyncOptionChild,
    FileSyncTargetFolderOption,
    FileSyncTargetSpaceGroup,
    FileSyncTargetSpaceGroupsPage,
    FileSyncTargetSpaceOption,
)
from bisheng.developer_token.domain.services.developer_token_service import DeveloperTokenService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services.permission_service import PermissionService

KNOWLEDGE_SERVICE_MOD = "bisheng.knowledge.domain.services.knowledge_space_service"

ENDPOINT_MOD = "bisheng.developer_token.api.endpoints.developer_token"


def _operator() -> MagicMock:
    user = MagicMock(spec=UserPayload)
    user.user_id = 10
    user.tenant_id = 5
    return user


def _app(login_user: UserPayload) -> FastAPI:
    from bisheng.admin.api.router import router as admin_router

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user
    return app


def _options_response() -> DeveloperTokenFileSyncOptions:
    return DeveloperTokenFileSyncOptions(
        tenant_id=5,
        user_id=7,
        categories=[
            FileSyncOptionCategory(
                code="POLICY",
                label="政策制度",
                children=[FileSyncOptionChild(code="MGMT_POLICY", label="管理政策")],
            )
        ],
        business_domains=[FileSyncOptionBusinessDomain(code="SA", name="安全")],
        target_space_groups=FileSyncTargetSpaceGroupsPage(
            data=[
                FileSyncTargetSpaceGroup(
                    space_type="department",
                    spaces=[
                        FileSyncTargetSpaceOption(
                            id=118,
                            name="安全库",
                            selectable=False,
                            has_children=True,
                        )
                    ],
                )
            ],
            has_more=False,
            next_cursor=None,
            page_size=50,
        ),
    )


def test_options_route_requires_bound_user_and_uses_cursor_contract() -> None:
    service = AsyncMock(return_value=_options_response())
    app = _app(_operator())

    with patch(f"{ENDPOINT_MOD}.DeveloperTokenService.get_file_sync_options", new=service):
        response = TestClient(app).get(
            "/api/v1/admin/developer-tokens/config/file-sync-options",
            params={
                "tenant_id": 5,
                "user_id": 7,
                "space_cursor": "next",
                "space_page_size": 25,
                "space_keyword": "安全",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["target_space_groups"] == {
        "data": [
            {
                "space_type": "department",
                "spaces": [
                    {
                        "id": 118,
                        "name": "安全库",
                        "selectable": False,
                        "has_children": True,
                    }
                ],
            }
        ],
        "has_more": False,
        "next_cursor": None,
        "page_size": 50,
    }
    assert service.await_args.kwargs == {
        "tenant_id": 5,
        "user_id": 7,
        "space_cursor": "next",
        "space_page_size": 25,
        "space_keyword": "安全",
    }


def test_folder_children_route_forwards_parent_and_cursor() -> None:
    result = DeveloperTokenFileSyncTargetChildren(
        data=[
            FileSyncTargetFolderOption(
                id=4096,
                name="管理办法",
                selectable=True,
                navigation_only=False,
                has_children=False,
            )
        ],
        has_more=False,
        next_cursor=None,
        page_size=50,
    )
    service = AsyncMock(return_value=result)
    app = _app(_operator())

    with patch(f"{ENDPOINT_MOD}.DeveloperTokenService.get_file_sync_target_children", new=service):
        response = TestClient(app).get(
            "/api/v1/admin/developer-tokens/config/file-sync-target-children",
            params={
                "tenant_id": 5,
                "user_id": 7,
                "knowledge_id": 118,
                "parent_id": 4000,
                "cursor": "next",
                "page_size": 25,
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["data"][0]["id"] == 4096
    assert service.await_args.kwargs == {
        "tenant_id": 5,
        "user_id": 7,
        "knowledge_id": 118,
        "parent_id": 4000,
        "cursor": "next",
        "page_size": 25,
    }


def test_deep_folder_permission_expands_only_necessary_ancestor_ids() -> None:
    selectable = [
        SimpleNamespace(
            id=30,
            knowledge_id=118,
            file_level_path="/10/20",
        )
    ]

    selectable_ids, visible_ids, space_ids = KnowledgeSpaceService._expand_file_sync_folder_visibility(selectable)

    assert selectable_ids == {30}
    assert visible_ids == {10, 20, 30}
    assert space_ids == {118}
    assert 40 not in visible_ids


@pytest.mark.asyncio
async def test_options_use_bound_user_target_permissions_not_operator_permissions(monkeypatch) -> None:
    config = SimpleNamespace(
        portal=SimpleNamespace(
            document_types=[
                SimpleNamespace(
                    code="POLICY",
                    label="政策制度",
                    children=[SimpleNamespace(code="MGMT_POLICY", label="管理政策")],
                )
            ],
            domains=[SimpleNamespace(code="SA", name="安全", enabled=True)],
        )
    )
    bound_user = UserPayload(user_id=7, user_name="bound", user_role=[2], tenant_id=5)
    list_targets = AsyncMock(
        return_value=SimpleNamespace(
            items=[
                SimpleNamespace(
                    id=118,
                    name="安全库",
                    space_type="department",
                    selectable=False,
                    has_children=True,
                )
            ],
            has_more=False,
            next_cursor=None,
        )
    )
    monkeypatch.setattr(DeveloperTokenService, "_assert_admin_scope", AsyncMock())
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_file_sync_portal_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_bound_user_payload",
        AsyncMock(return_value=bound_user),
        raising=False,
    )
    monkeypatch.setattr(
        KnowledgeSpaceService,
        "list_file_sync_target_spaces",
        list_targets,
        raising=False,
    )

    result = await DeveloperTokenService.get_file_sync_options(
        _operator(),
        tenant_id=5,
        user_id=7,
        space_page_size=50,
    )

    list_targets.assert_awaited_once_with(
        login_user=bound_user,
        cursor=None,
        page_size=50,
        keyword=None,
    )
    assert result.user_id == 7
    assert result.target_space_groups.data[0].spaces[0].selectable is False


@pytest.mark.asyncio
async def test_invalid_target_cursor_maps_to_19814_without_falling_back(monkeypatch) -> None:
    config = SimpleNamespace(portal=SimpleNamespace(document_types=[], domains=[]))
    bound_user = UserPayload(user_id=7, user_name="bound", user_role=[2], tenant_id=5)
    list_targets = AsyncMock(side_effect=CursorDecodeError("invalid cursor"))
    monkeypatch.setattr(DeveloperTokenService, "_assert_admin_scope", AsyncMock())
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_file_sync_portal_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_bound_user_payload",
        AsyncMock(return_value=bound_user),
        raising=False,
    )
    monkeypatch.setattr(
        KnowledgeSpaceService,
        "list_file_sync_target_spaces",
        list_targets,
        raising=False,
    )

    with pytest.raises(DeveloperTokenInvalidFileSyncTargetCursorError) as exc_info:
        await DeveloperTokenService.get_file_sync_options(
            _operator(),
            tenant_id=5,
            user_id=7,
            space_cursor="broken",
        )

    assert exc_info.value.code == 19814
    list_targets.assert_awaited_once()


@pytest.mark.asyncio
async def test_token_list_resolves_target_displays_once_for_the_page(monkeypatch) -> None:
    tokens = [
        DeveloperToken(
            id=1,
            tenant_id=5,
            user_id=7,
            name="one",
            token_hash="hash-1",
            token_ciphertext="cipher-1",
            token_prefix="bst_one",
        ),
        DeveloperToken(
            id=2,
            tenant_id=5,
            user_id=8,
            name="two",
            token_hash="hash-2",
            token_ciphertext="cipher-2",
            token_prefix="bst_two",
        ),
    ]

    class Repo:
        @staticmethod
        async def list_tokens(**_kwargs):
            return tokens, 2

    display_map = {1: SimpleNamespace(knowledge_id=118), 2: None}
    build_displays = AsyncMock(return_value=display_map)
    to_read = AsyncMock(side_effect=lambda token, **_kwargs: SimpleNamespace(id=token.id))
    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(DeveloperTokenService, "_resolve_list_tenant", AsyncMock(return_value=5))
    monkeypatch.setattr(
        DeveloperTokenService,
        "_build_file_sync_target_displays",
        build_displays,
        raising=False,
    )
    monkeypatch.setattr(DeveloperTokenService, "_to_read", to_read)

    result = await DeveloperTokenService.list_tokens(
        _operator(),
        SimpleNamespace(page=1, limit=20, keyword=None, tenant_id=5, user_id=None, enabled=None),
    )

    build_displays.assert_awaited_once_with(tokens)
    assert to_read.await_args_list[0].kwargs["file_sync_target_display"] is display_map[1]
    assert to_read.await_args_list[1].kwargs["file_sync_target_display"] is None
    assert result.total == 2


@pytest.mark.asyncio
async def test_target_spaces_use_only_bound_user_root_or_folder_permissions(monkeypatch) -> None:
    space = SimpleNamespace(id=118, name="Safety")
    deep_folder = SimpleNamespace(id=30, knowledge_id=118, file_level_path="/10/20")
    knowledge_repository = SimpleNamespace(find_file_sync_spaces=AsyncMock(return_value=[(space, "department")]))
    file_repository = SimpleNamespace(
        find_file_sync_folders_by_ids=AsyncMock(return_value=[deep_folder]),
        find_file_sync_space_ids_with_folders=AsyncMock(return_value={118}),
    )

    @asynccontextmanager
    async def session_context():
        yield object()

    async def list_ids(_user_id, _permission, object_type, **_kwargs):
        return [] if object_type == "knowledge_space" else ["30"]

    monkeypatch.setattr(f"{KNOWLEDGE_SERVICE_MOD}.get_async_db_session", session_context)
    monkeypatch.setattr(
        f"{KNOWLEDGE_SERVICE_MOD}.KnowledgeRepositoryImpl",
        lambda _session: knowledge_repository,
    )
    monkeypatch.setattr(
        f"{KNOWLEDGE_SERVICE_MOD}.KnowledgeFileRepositoryImpl",
        lambda _session: file_repository,
    )
    monkeypatch.setattr(
        PermissionService,
        "list_accessible_ids",
        AsyncMock(side_effect=list_ids),
    )

    page = await KnowledgeSpaceService.list_file_sync_target_spaces(
        login_user=UserPayload(user_id=7, user_name="bound", user_role=[2], tenant_id=5),
        cursor=None,
        page_size=50,
        keyword=None,
    )

    assert page.items[0].selectable is False
    assert page.items[0].has_children is True
    assert knowledge_repository.find_file_sync_spaces.await_args.kwargs["allowed_space_ids"] == {118}
    assert file_repository.find_file_sync_space_ids_with_folders.await_args.kwargs["visible_folder_ids"] == {10, 20, 30}


@pytest.mark.asyncio
async def test_folder_page_exposes_required_ancestor_as_navigation_only(monkeypatch) -> None:
    space = SimpleNamespace(id=118, name="Safety")
    deep_folder = SimpleNamespace(id=30, knowledge_id=118, file_level_path="/10/20")
    root_ancestor = SimpleNamespace(
        id=10,
        knowledge_id=118,
        file_name="Policies",
        file_level_path="",
    )
    knowledge_repository = SimpleNamespace(find_file_sync_spaces_by_ids=AsyncMock(return_value=[(space, "department")]))
    file_repository = SimpleNamespace(
        find_file_sync_folders_by_ids=AsyncMock(return_value=[deep_folder]),
        list_file_sync_direct_children=AsyncMock(return_value=[root_ancestor]),
        find_file_sync_parent_paths_with_children=AsyncMock(return_value={"/10"}),
    )

    @asynccontextmanager
    async def session_context():
        yield object()

    async def list_ids(_user_id, _permission, object_type, **_kwargs):
        return [] if object_type == "knowledge_space" else ["30"]

    monkeypatch.setattr(f"{KNOWLEDGE_SERVICE_MOD}.get_async_db_session", session_context)
    monkeypatch.setattr(
        f"{KNOWLEDGE_SERVICE_MOD}.KnowledgeRepositoryImpl",
        lambda _session: knowledge_repository,
    )
    monkeypatch.setattr(
        f"{KNOWLEDGE_SERVICE_MOD}.KnowledgeFileRepositoryImpl",
        lambda _session: file_repository,
    )
    monkeypatch.setattr(
        PermissionService,
        "list_accessible_ids",
        AsyncMock(side_effect=list_ids),
    )

    page = await KnowledgeSpaceService.list_file_sync_target_folders(
        login_user=UserPayload(user_id=7, user_name="bound", user_role=[2], tenant_id=5),
        knowledge_id=118,
        parent_id=None,
        cursor=None,
        page_size=50,
    )

    assert [(item.id, item.selectable, item.has_children) for item in page.items] == [(10, False, True)]
    assert file_repository.list_file_sync_direct_children.await_args.kwargs["visible_folder_ids"] == {10, 20, 30}


@pytest.mark.asyncio
async def test_target_display_paths_are_resolved_in_batched_repository_calls(monkeypatch) -> None:
    space = SimpleNamespace(id=118, name="Safety")
    target_folder = SimpleNamespace(
        id=30,
        knowledge_id=118,
        file_name="Current",
        file_level_path="/10/20",
    )
    ancestors = [
        SimpleNamespace(id=10, knowledge_id=118, file_name="Policies"),
        SimpleNamespace(id=20, knowledge_id=118, file_name="Management"),
    ]
    knowledge_repository = SimpleNamespace(find_file_sync_spaces_by_ids=AsyncMock(return_value=[(space, "department")]))
    file_repository = SimpleNamespace(find_file_sync_folders_by_ids=AsyncMock(side_effect=[[target_folder], ancestors]))

    @asynccontextmanager
    async def session_context():
        yield object()

    monkeypatch.setattr(f"{KNOWLEDGE_SERVICE_MOD}.get_async_db_session", session_context)
    monkeypatch.setattr(
        f"{KNOWLEDGE_SERVICE_MOD}.KnowledgeRepositoryImpl",
        lambda _session: knowledge_repository,
    )
    monkeypatch.setattr(
        f"{KNOWLEDGE_SERVICE_MOD}.KnowledgeFileRepositoryImpl",
        lambda _session: file_repository,
    )

    displays = await KnowledgeSpaceService.resolve_file_sync_target_displays({1: (118, 30), 2: (118, 30)})

    assert displays[1].folder_path == [
        (10, "Policies"),
        (20, "Management"),
        (30, "Current"),
    ]
    assert knowledge_repository.find_file_sync_spaces_by_ids.await_count == 1
    assert file_repository.find_file_sync_folders_by_ids.await_count == 2
