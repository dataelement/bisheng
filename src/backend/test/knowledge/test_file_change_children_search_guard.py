from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import mysql, sqlite

from bisheng.core.context.tenant import (
    current_tenant_id,
    set_admin_scope_tenant_id,
    set_current_tenant_id,
)
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_space_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import KnowledgeFileVisibilityService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_SERVICE_MODULE = "bisheng.knowledge.domain.services.knowledge_space_service"


class _User:
    user_id = 7
    tenant_id = 11
    is_global_super = False

    def is_admin(self) -> bool:
        return False


def _item(
    item_id: int,
    *,
    file_type: int = FileType.FILE.value,
    status: int = KnowledgeFileStatus.WAITING.value,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=item_id,
        file_name=f"item-{item_id}.txt",
        file_type=file_type,
        status=status,
        update_time=datetime(2026, 8, 10, item_id, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_children_guard_filters_after_rebac_and_refills_with_one_guard_load():
    service = KnowledgeSpaceService(request=None, login_user=_User())
    candidates = [_item(1), _item(2), _item(3), _item(4), _item(5)]
    excluded_loader = AsyncMock(return_value={1, 2})
    service._get_file_change_excluded_ids = excluded_loader
    dao_calls = 0

    async def list_children(*args, cursor=None, **kwargs):
        nonlocal dao_calls
        dao_calls += 1
        if cursor is None:
            return candidates[:3]
        assert cursor[-1] == 3
        return candidates[3:]

    async def rebac_filter(items, **kwargs):
        return list(items)

    with (
        patch(f"{_SERVICE_MODULE}.SpaceFileDao.async_list_children", new=list_children),
        patch.object(service, "_build_child_permission_context", new=AsyncMock(return_value={})),
        patch.object(service, "_filter_visible_child_items", new=rebac_filter),
        patch(f"{_SERVICE_MODULE}._CHILD_PERMISSION_SCAN_BATCH_SIZE", 3),
    ):
        items, has_more = await service._scan_visible_child_items(
            space_id=1,
            parent_id=None,
            file_ids=None,
            order_field="file_type",
            order_sort="asc",
            file_status=None,
            file_type=None,
            page_size=2,
        )

    assert [item.id for item in items] == [3, 4]
    assert has_more is True
    assert dao_calls == 2
    excluded_loader.assert_awaited_once_with(space_id=1)


@pytest.mark.asyncio
async def test_search_guard_filters_after_rebac_and_refills_with_one_guard_load():
    service = KnowledgeSpaceService(request=None, login_user=_User())
    candidates = [_item(1), _item(2), _item(3), _item(4), _item(5)]
    excluded_loader = AsyncMock(return_value={1, 2})
    service._get_file_change_excluded_ids = excluded_loader
    dao_calls = 0

    async def search_batch(*args, page, page_size, **kwargs):
        nonlocal dao_calls
        dao_calls += 1
        start = (page - 1) * page_size
        return candidates[start : start + page_size]

    async def rebac_filter(items, **kwargs):
        return list(items)

    with (
        patch(f"{_SERVICE_MODULE}.KnowledgeFileDao.aget_file_by_filters", new=search_batch),
        patch.object(service, "_build_child_permission_context", new=AsyncMock(return_value={})),
        patch.object(service, "_filter_visible_child_items", new=rebac_filter),
        patch(f"{_SERVICE_MODULE}._SEARCH_SCAN_BATCH_SIZE", 3),
    ):
        items, has_more = await service._scan_visible_search_items(
            space_id=1,
            file_name="item",
            filter_files=None,
            extra_file_ids=None,
            file_status=None,
            file_level_path=None,
            order_field="file_type",
            order_sort="asc",
            exclude_file_ids=None,
            page=1,
            page_size=2,
        )

    assert [item.id for item in items] == [3, 4]
    assert has_more is True
    assert dao_calls == 2
    excluded_loader.assert_awaited_once_with(space_id=1)


@pytest.mark.asyncio
async def test_shared_published_folder_remains_but_unpublished_sibling_is_hidden():
    service = KnowledgeSpaceService(request=None, login_user=_User())
    shared_folder = _item(10, file_type=FileType.DIR.value)
    unpublished_sibling = _item(11)
    published_child = _item(12, status=KnowledgeFileStatus.SUCCESS.value)
    service._get_file_change_excluded_ids = AsyncMock(return_value={11})

    with (
        patch(
            f"{_SERVICE_MODULE}.SpaceFileDao.async_list_children",
            new=AsyncMock(return_value=[shared_folder, unpublished_sibling, published_child]),
        ),
        patch.object(service, "_build_child_permission_context", new=AsyncMock(return_value={})),
        patch.object(
            service,
            "_filter_visible_child_items",
            new=AsyncMock(return_value=[shared_folder, unpublished_sibling, published_child]),
        ),
    ):
        items, has_more = await service._scan_visible_child_items(
            space_id=1,
            parent_id=None,
            file_ids=None,
            order_field="file_type",
            order_sort="asc",
            file_status=None,
            file_type=None,
            page_size=20,
        )

    assert [item.id for item in items] == [10, 12]
    assert has_more is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        KnowledgeFileStatus.WAITING.value,
        KnowledgeFileStatus.PROCESSING.value,
        KnowledgeFileStatus.FAILED.value,
    ],
)
async def test_status_alone_does_not_hide_pre_cutover_rename_move_delete_resource(status):
    service = KnowledgeSpaceService(request=None, login_user=_User())
    old_resource = _item(20, status=status)
    service._get_file_change_excluded_ids = AsyncMock(return_value=set())

    with (
        patch(
            f"{_SERVICE_MODULE}.SpaceFileDao.async_list_children",
            new=AsyncMock(return_value=[old_resource]),
        ),
        patch.object(service, "_build_child_permission_context", new=AsyncMock(return_value={})),
        patch.object(service, "_filter_visible_child_items", new=AsyncMock(return_value=[old_resource])),
    ):
        items, _ = await service._scan_visible_child_items(
            space_id=1,
            parent_id=None,
            file_ids=None,
            order_field="file_type",
            order_sort="asc",
            file_status=None,
            file_type=None,
            page_size=20,
        )

    assert [item.id for item in items] == [20]


@pytest.mark.asyncio
async def test_folder_counts_exclude_file_change_hidden_descendants():
    service = KnowledgeSpaceService(request=None, login_user=_User())
    folder = KnowledgeFile(
        id=30,
        tenant_id=11,
        user_id=7,
        knowledge_id=1,
        file_name="shared-folder",
        file_type=FileType.DIR.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        file_level_path="",
    )
    statements = []

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        async def exec(self, statement):
            statements.append(statement)
            if len(statements) == 1:
                return _Rows(
                    [
                        (30, KnowledgeFileStatus.WAITING.value, 1),
                        (30, KnowledgeFileStatus.SUCCESS.value, 1),
                    ]
                )
            if len(statements) == 2:
                return _Rows([(31, 1, KnowledgeFileStatus.WAITING.value, "/30")])
            return _Rows([])

    @asynccontextmanager
    async def session_factory():
        yield _Session()

    tenant_token = set_current_tenant_id(11)
    try:
        with (
            patch("bisheng.core.database.get_async_db_session", new=session_factory),
            patch.object(service, "_load_file_change_approval_matches", AsyncMock(return_value=[])),
        ):
            result = await service._handle_file_folder_extra_info(
                [folder],
                file_change_excluded_ids=set(range(31, 532)),
            )
    finally:
        current_tenant_id.reset(tenant_token)

    for dialect in (sqlite.dialect(), mysql.dialect()):
        compiled = [
            statement.compile(
                dialect=dialect,
                compile_kwargs={"render_postcompile": True},
            )
            for statement in statements
        ]
        assert all("knowledgefile.tenant_id" in str(statement) for statement in compiled)
        assert all("knowledgefile.id NOT IN" not in str(statement) for statement in compiled)
    assert len(statements) == 3
    assert result[0]["success_file_num"] == 1
    assert result[0]["processing_file_num"] == 0
    assert result[0]["has_failed_files"] is False


@pytest.mark.asyncio
async def test_formal_list_enriches_root_and_inherited_children_with_one_batch_load():
    service = KnowledgeSpaceService(request=None, login_user=_User())
    root = KnowledgeFile(
        id=60,
        tenant_id=11,
        user_id=7,
        knowledge_id=1,
        file_name="root",
        file_type=FileType.DIR.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        file_level_path="",
    )
    child = KnowledgeFile(
        id=61,
        tenant_id=11,
        user_id=7,
        knowledge_id=1,
        file_name="child.txt",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        file_level_path="/60",
    )
    sibling = KnowledgeFile(
        id=62,
        tenant_id=11,
        user_id=7,
        knowledge_id=1,
        file_name="sibling.txt",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        file_level_path="",
    )
    match = SimpleNamespace(
        request=SimpleNamespace(
            id=71,
            resource_id=60,
            applicant_user_id=8,
            action="delete",
        ),
        instance=SimpleNamespace(id=81, status="pending"),
        path_root="/60/",
        lock_scope="subtree",
    )
    loader = AsyncMock(return_value=[match])
    service._load_file_change_approval_matches = loader

    tenant_token = set_current_tenant_id(11)
    try:
        with patch(
            "bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver."
            "KnowledgeSpaceFileChangeApproverResolver.is_current_approver",
            new=AsyncMock(return_value=True),
        ) as approver_check:
            enriched = await service._enrich_file_change_approval_views(
                [root, child, sibling],
                [root.model_dump(), child.model_dump(), sibling.model_dump()],
            )
    finally:
        current_tenant_id.reset(tenant_token)

    loader.assert_awaited_once()
    approver_check.assert_awaited_once_with(tenant_id=11, space_id=1, user_id=7)
    assert enriched[0]["file_change_approval"]["inherited"] is False
    assert enriched[1]["file_change_approval"]["inherited"] is True
    assert enriched[1]["file_change_approval"]["root_resource_id"] == 60
    assert "file_change_approval" not in enriched[2]


def test_guard_uses_verified_global_super_admin_scope_tenant():
    user = _User()
    user.tenant_id = 1
    user.is_global_super = True
    service = KnowledgeFileVisibilityService(request=None, login_user=user)
    tenant_token = set_current_tenant_id(1)
    scope_token = set_admin_scope_tenant_id(22)
    try:
        assert service.require_explicit_tenant() == 22
    finally:
        from bisheng.core.context.tenant import _admin_scope_tenant_id

        _admin_scope_tenant_id.reset(scope_token)
        current_tenant_id.reset(tenant_token)


def test_guard_rejects_ordinary_cross_tenant_identity():
    user = _User()
    service = KnowledgeFileVisibilityService(request=None, login_user=user)
    tenant_token = set_current_tenant_id(12)
    try:
        with pytest.raises(RuntimeError, match="matching tenant context"):
            service.require_explicit_tenant()
    finally:
        current_tenant_id.reset(tenant_token)
