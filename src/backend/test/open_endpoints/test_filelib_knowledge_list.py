from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.cursor import decode_cursor
from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError
from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeRead, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.api.dependencies import get_filelib_request_user
from bisheng.open_endpoints.api.endpoints import filelib as filelib_endpoint
from bisheng.open_endpoints.domain.services.filelib_knowledge_list_service import (
    FilelibKnowledgeListService,
)


def _empty_page():
    return PageInfiniteCursorData(data=[], page_size=10, has_more=False, next_cursor=None)


@pytest.mark.parametrize("query", ["type=3", "knowledge_type=3"])
def test_space_type_parameters_select_space_listing(monkeypatch, query) -> None:
    """标准和兼容参数都必须进入知识空间列表, 不能回退到默认 type=0。"""
    login_user = type("RequestUser", (), {"user_id": 7})()
    list_spaces = AsyncMock(return_value=_empty_page())
    monkeypatch.setattr(
        filelib_endpoint.FilelibKnowledgeListService,
        "list_spaces",
        list_spaces,
    )

    app = FastAPI()
    app.include_router(filelib_endpoint.router, prefix="/api/v2")
    app.dependency_overrides[get_filelib_request_user] = lambda: login_user

    with TestClient(app) as client:
        response = client.get(f"/api/v2/filelib/?{query}")

    assert response.status_code == 200
    list_spaces.assert_awaited_once_with(name=None, cursor=None, page_size=10)


def test_conflicting_type_parameters_return_422(monkeypatch) -> None:
    list_spaces = AsyncMock(return_value=_empty_page())
    monkeypatch.setattr(
        filelib_endpoint.FilelibKnowledgeListService,
        "list_spaces",
        list_spaces,
    )
    app = FastAPI()
    app.include_router(filelib_endpoint.router, prefix="/api/v2")
    app.dependency_overrides[get_filelib_request_user] = lambda: SimpleNamespace(user_id=7)

    with TestClient(app) as client:
        response = client.get("/api/v2/filelib/?type=0&knowledge_type=3")

    assert response.status_code == 422
    list_spaces.assert_not_awaited()


@pytest.mark.parametrize(
    ("query", "expected_type"),
    [
        ("", KnowledgeTypeEnum.NORMAL),
        ("type=0", KnowledgeTypeEnum.NORMAL),
        ("type=1", KnowledgeTypeEnum.QA),
        ("type=2", KnowledgeTypeEnum.PRIVATE),
    ],
)
def test_non_space_types_keep_legacy_knowledge_list(monkeypatch, query, expected_type) -> None:
    login_user = SimpleNamespace(user_id=7)
    get_knowledge = AsyncMock(return_value=_empty_page())
    monkeypatch.setattr(filelib_endpoint.KnowledgeService, "get_knowledge", get_knowledge)
    app = FastAPI()
    app.include_router(filelib_endpoint.router, prefix="/api/v2")
    app.dependency_overrides[get_filelib_request_user] = lambda: login_user

    with TestClient(app) as client:
        response = client.get(f"/api/v2/filelib/?{query}")

    assert response.status_code == 200
    assert get_knowledge.await_args.args[2] is expected_type


async def test_visible_space_levels_match_portal_groups_without_creating_personal_spaces() -> None:
    login_user = SimpleNamespace(user_id=7, user_name="tester", is_admin=lambda: False)
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)
    favorite = SimpleNamespace(id=6, user_id=7)

    async def _space_ids_by_level(level):
        return {
            KnowledgeSpaceLevelEnum.PUBLIC: [1],
            KnowledgeSpaceLevelEnum.DEPARTMENT: [2, 3, 7],
            KnowledgeSpaceLevelEnum.TEAM: [4],
            KnowledgeSpaceLevelEnum.TEAM_KS: [5],
        }[level]

    async def _accessible_ids(*, relation, **_kwargs):
        return [2, 4] if relation == "can_read" else [5]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_space_ids_by_level",
            new=AsyncMock(side_effect=_space_ids_by_level),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_space_members",
            new=AsyncMock(return_value=[SimpleNamespace(business_id="3")]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids",
            new=AsyncMock(side_effect=_accessible_ids),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_knowledge_ids_created_by",
            new=AsyncMock(return_value=[7]),
        ),
        patch.object(service, "_find_favorite_space", new=AsyncMock(return_value=favorite)),
        patch.object(service, "_find_personal_default_space", new=AsyncMock(return_value=None)),
        patch.object(service, "_get_relation_models_map", new=AsyncMock(return_value={})),
        patch.object(service, "_get_relation_bindings", new=AsyncMock(return_value=[])),
        patch.object(service, "_ensure_personal_spaces", new=AsyncMock()) as ensure_personal,
    ):
        result = await service.get_existing_portal_visible_space_levels()

    assert result == {
        1: KnowledgeSpaceLevelEnum.PUBLIC,
        2: KnowledgeSpaceLevelEnum.DEPARTMENT,
        3: KnowledgeSpaceLevelEnum.DEPARTMENT,
        4: KnowledgeSpaceLevelEnum.TEAM,
        5: KnowledgeSpaceLevelEnum.TEAM_KS,
        6: KnowledgeSpaceLevelEnum.PERSONAL,
        7: KnowledgeSpaceLevelEnum.DEPARTMENT,
    }
    ensure_personal.assert_not_awaited()


async def test_custom_relation_without_view_space_is_excluded() -> None:
    login_user = SimpleNamespace(user_id=7, user_name="tester", is_admin=lambda: False)
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)

    async def _space_ids_by_level(level):
        return [2] if level == KnowledgeSpaceLevelEnum.DEPARTMENT else []

    async def _accessible_ids(*, relation, **_kwargs):
        return [2] if relation == "can_read" else []

    custom_binding = {
        "resource_type": "knowledge_space",
        "resource_id": "2",
        "model_id": "custom-viewer",
    }
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_space_ids_by_level",
            new=AsyncMock(side_effect=_space_ids_by_level),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_space_members",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids",
            new=AsyncMock(side_effect=_accessible_ids),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_knowledge_ids_created_by",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(service, "_find_favorite_space", new=AsyncMock(return_value=None)),
        patch.object(service, "_find_personal_default_space", new=AsyncMock(return_value=None)),
        patch.object(
            service,
            "_get_relation_models_map",
            new=AsyncMock(return_value={"custom-viewer": {"is_system": False}}),
        ),
        patch.object(
            service,
            "_get_relation_bindings",
            new=AsyncMock(return_value=[custom_binding]),
        ),
        patch.object(service, "_get_effective_permission_ids", new=AsyncMock(return_value=set())),
    ):
        result = await service.get_existing_portal_visible_space_levels()

    assert result == {}


async def test_space_list_uses_bounded_cursor_query_and_adds_space_level(monkeypatch) -> None:
    login_user = SimpleNamespace(user_id=7)
    service = FilelibKnowledgeListService(request=SimpleNamespace(), login_user=login_user)
    service.space_service.get_existing_portal_visible_space_levels = AsyncMock(
        return_value={
            1: KnowledgeSpaceLevelEnum.PUBLIC,
            2: KnowledgeSpaceLevelEnum.DEPARTMENT,
            3: KnowledgeSpaceLevelEnum.TEAM_KS,
        }
    )
    rows = [
        SimpleNamespace(id=1),
        SimpleNamespace(id=2),
        SimpleNamespace(id=3),
    ]
    query = AsyncMock(return_value=rows)
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_knowledge_list_service.KnowledgeDao.aget_knowledge_by_ids_cursor",
        query,
    )
    converted = [
        KnowledgeRead(
            id=1,
            user_id=7,
            name="公共库",
            type=KnowledgeTypeEnum.SPACE.value,
            update_time=datetime(2026, 9, 4, 12, 0, 0),
        ),
        KnowledgeRead(
            id=2,
            user_id=8,
            name="部门库",
            type=KnowledgeTypeEnum.SPACE.value,
            update_time=datetime(2026, 9, 4, 11, 0, 0),
        ),
    ]
    convert = AsyncMock(return_value=converted)
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_knowledge_list_service.KnowledgeService.aconvert_knowledge_read",
        convert,
    )

    result = await service.list_spaces(name="库", cursor=None, page_size=2)

    query.assert_awaited_once_with(
        [1, 2, 3],
        knowledge_type=KnowledgeTypeEnum.SPACE,
        name="库",
        sort_by="update_time",
        limit=3,
        cursor=None,
    )
    assert [item.space_level for item in result.data] == [
        KnowledgeSpaceLevelEnum.PUBLIC,
        KnowledgeSpaceLevelEnum.DEPARTMENT,
    ]
    assert result.has_more is True
    assert decode_cursor(
        result.next_cursor,
        expected_key_len=2,
        expected_context="filelib-space|sort_by=update_time",
    ) == ["2026-09-04T11:00:00", 2]


async def test_first_space_page_applies_database_limit(monkeypatch) -> None:
    from bisheng.knowledge.domain.models import knowledge as knowledge_model

    captured = {}

    class _Result:
        @staticmethod
        def all():
            return []

    class _Session:
        async def exec(self, statement):
            captured["statement"] = statement
            return _Result()

    @asynccontextmanager
    async def _session_context():
        yield _Session()

    monkeypatch.setattr(knowledge_model, "get_async_db_session", _session_context)

    result = await knowledge_model.KnowledgeDao.aget_knowledge_by_ids_cursor(
        [1, 2, 3],
        knowledge_type=KnowledgeTypeEnum.SPACE,
        limit=11,
        cursor=None,
    )

    assert result == []
    assert captured["statement"]._limit_clause.value == 11


async def test_space_name_filter_uses_async_file_lookup(monkeypatch) -> None:
    from bisheng.knowledge.domain.models import knowledge as knowledge_model

    class _Result:
        @staticmethod
        def all():
            return []

    class _Session:
        async def exec(self, _statement):
            return _Result()

    @asynccontextmanager
    async def _session_context():
        yield _Session()

    async_lookup = AsyncMock(return_value=[3])
    monkeypatch.setattr(knowledge_model, "get_async_db_session", _session_context)
    monkeypatch.setattr(
        knowledge_model.KnowledgeFileDao,
        "aget_knowledge_ids_by_name",
        async_lookup,
    )
    monkeypatch.setattr(
        knowledge_model.KnowledgeFileDao,
        "get_knowledge_ids_by_name",
        lambda _name: (_ for _ in ()).throw(AssertionError("不能调用同步文件名查询")),
    )

    await knowledge_model.KnowledgeDao.aget_knowledge_by_ids_cursor(
        [1, 2, 3],
        knowledge_type=KnowledgeTypeEnum.SPACE,
        name="制度",
        limit=11,
    )

    async_lookup.assert_awaited_once_with("制度")


async def test_space_item_conversion_uses_async_user_lookup(monkeypatch) -> None:
    from bisheng.knowledge.domain.services import knowledge_service as knowledge_service_module

    async_lookup = AsyncMock(return_value=[SimpleNamespace(user_id=8, user_name="owner")])
    monkeypatch.setattr(knowledge_service_module.UserDao, "aget_user_by_ids", async_lookup)
    monkeypatch.setattr(
        knowledge_service_module.UserDao,
        "get_user_by_ids",
        lambda _ids: (_ for _ in ()).throw(AssertionError("不能调用同步用户查询")),
    )
    knowledge = Knowledge(
        id=3,
        user_id=8,
        name="部门库",
        type=KnowledgeTypeEnum.SPACE.value,
    )

    result = await KnowledgeService.aconvert_knowledge_read(
        SimpleNamespace(user_id=7),
        [knowledge],
        permission_map={},
    )

    assert result[0].user_name == "owner"
    async_lookup.assert_awaited_once_with([8])


async def test_space_list_rejects_cursor_from_other_list_context() -> None:
    service = FilelibKnowledgeListService(
        request=SimpleNamespace(),
        login_user=SimpleNamespace(user_id=7),
    )

    with pytest.raises(KnowledgeInvalidCursorError):
        await service.list_spaces(
            name=None,
            cursor="not-a-valid-cursor",
            page_size=10,
        )
