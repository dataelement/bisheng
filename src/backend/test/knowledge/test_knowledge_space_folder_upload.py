"""F034 Wave 5 — KnowledgeSpaceService.upload_folder_items unit tests (§5.5 folder upload).

Strategy: mock DAO / PermissionService / QuotaService / add_file (same approach as
test_knowledge_space_move.py). upload_folder_items is pure orchestration — batch
pre-checks (count / depth / top-level dup / capacity) + directory-tree build +
per-directory delegation to the already-tested add_file. See
features/v2.6.0/034-knowledge-space-file-move/design.md §9.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceFileSizeLimitError,
    SpaceFolderDepthError,
    SpaceFolderDuplicateError,
    SpaceFolderUploadCountExceededError,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FolderUploadItem
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_SVC = "bisheng.knowledge.domain.services.knowledge_space_service"


def _items(*paths, size=10):
    return [FolderUploadItem(file_path=f"minio://tmp/{i}.bin", relative_path=p, size=size) for i, p in enumerate(paths)]


def _svc():
    svc = KnowledgeSpaceService(request=MagicMock(), login_user=MagicMock(user_id=1, user_name="u1", tenant_id=1))
    svc._require_permission_id = AsyncMock(return_value=None)
    svc._initialize_child_resource_permissions = AsyncMock(return_value=None)
    svc._cleanup_resource_tuples = AsyncMock(return_value=None)
    svc._ensure_space_async_task_tenant_consistency = MagicMock(return_value=None)
    svc.add_file = AsyncMock(return_value=[])
    return svc


class _FakeFileDao:
    """Records created folder rows and hands out incremental ids."""

    def __init__(self):
        self.rows = []
        self.deleted = []
        self._next_id = 100

    async def aadd_file(self, row):
        row.id = self._next_id
        self._next_id += 1
        self.rows.append(row)
        return row

    async def adelete_batch(self, ids):
        self.deleted.extend(ids)


@pytest.fixture()
def fake_dao():
    return _FakeFileDao()


@pytest.fixture(autouse=True)
def _patch_module(fake_dao):
    space = MagicMock(id=5, tenant_id=1)
    with (
        patch(f"{_SVC}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=space)),
        patch(f"{_SVC}.KnowledgeDao.async_update_knowledge_update_time_by_id", new=AsyncMock()),
        patch(f"{_SVC}.SpaceFileDao.count_folder_by_name", new=AsyncMock(return_value=0)),
        patch(f"{_SVC}.SpaceFileDao.get_user_total_file_size", new=AsyncMock(return_value=0)),
        patch(f"{_SVC}.QuotaService.get_knowledge_space_upload_limit_bytes", new=AsyncMock(return_value=None)),
        patch(f"{_SVC}.QuotaService.get_tenant_storage_remaining_bytes", new=AsyncMock(return_value=None)),
        patch(f"{_SVC}.KnowledgeFileDao.aadd_file", new=fake_dao.aadd_file),
        patch(f"{_SVC}.KnowledgeFileDao.adelete_batch", new=fake_dao.adelete_batch),
    ):
        yield


# ── tree build + grouping (AC-25) ──────────────────────────────────────────


async def test_builds_nested_tree_and_groups_files(fake_dao):
    svc = _svc()
    items = _items("Root/a.pdf", "Root/Sub/b.pdf", "Root/Sub/Deep/c.pdf")

    await svc.upload_folder_items(5, items, parent_id=None)

    by_name = {r.file_name: r for r in fake_dao.rows}
    assert set(by_name) == {"Root", "Sub", "Deep"}
    root, sub, deep = by_name["Root"], by_name["Sub"], by_name["Deep"]
    assert all(r.file_type == 0 for r in fake_dao.rows)
    assert (root.level, root.file_level_path) == (0, "")
    assert (sub.level, sub.file_level_path) == (1, f"/{root.id}")
    assert (deep.level, deep.file_level_path) == (2, f"/{root.id}/{sub.id}")

    # files registered per directory via add_file(knowledge_id, paths, parent_id=...)
    calls = {c.kwargs.get("parent_id") or c.args[2]: c.args[1] for c in svc.add_file.await_args_list}
    assert calls[root.id] == ["minio://tmp/0.bin"]
    assert calls[sub.id] == ["minio://tmp/1.bin"]
    assert calls[deep.id] == ["minio://tmp/2.bin"]

    # U7: every created folder got its permission tuple initialised, chained to its parent
    perm_calls = {c.args[1]: (c.args[2], c.args[3]) for c in svc._initialize_child_resource_permissions.await_args_list}
    assert perm_calls[root.id] == ("knowledge_space", 5)
    assert perm_calls[sub.id] == ("folder", root.id)
    assert perm_calls[deep.id] == ("folder", sub.id)


async def test_upload_under_existing_parent_folder(fake_dao):
    svc = _svc()
    parent = MagicMock(id=9, level=2, file_level_path="/7/8")
    svc._get_folder_for_action = AsyncMock(return_value=parent)

    await svc.upload_folder_items(5, _items("Top/x.pdf"), parent_id=9)

    top = fake_dao.rows[0]
    assert (top.level, top.file_level_path) == (3, "/7/8/9")
    assert svc._initialize_child_resource_permissions.await_args_list[0].args[2:4] == ("folder", 9)


# ── batch pre-checks: all-or-nothing (AC-26 / AC-28 / AC-29 / AC-30) ───────


async def test_count_over_1000_rejected(fake_dao):
    svc = _svc()
    items = _items(*[f"Root/f{i}.pdf" for i in range(1001)])
    with pytest.raises(SpaceFolderUploadCountExceededError):
        await svc.upload_folder_items(5, items)
    assert fake_dao.rows == []
    svc.add_file.assert_not_awaited()


async def test_depth_over_limit_rejected_whole_batch(fake_dao):
    svc = _svc()
    # parent at level 8 = 第9层; folders A (level 9 = 第10层, OK) + B (level 10 = 第11层) → reject
    parent = MagicMock(id=9, level=8, file_level_path="/1/2/3/4/5/6/7/8")
    svc._get_folder_for_action = AsyncMock(return_value=parent)
    with pytest.raises(SpaceFolderDepthError):
        await svc.upload_folder_items(5, _items("A/B/d.pdf"), parent_id=9)
    assert fake_dao.rows == []
    svc.add_file.assert_not_awaited()


async def test_depth_into_deepest_folder_rejected(fake_dao):
    svc = _svc()
    # parent at level 9 = 第10层 (deepest allowed): even a single-layer folder → level 10 → reject
    parent = MagicMock(id=9, level=9, file_level_path="/1/2/3/4/5/6/7/8/9")
    svc._get_folder_for_action = AsyncMock(return_value=parent)
    with pytest.raises(SpaceFolderDepthError):
        await svc.upload_folder_items(5, _items("A/d.pdf"), parent_id=9)
    assert fake_dao.rows == []


async def test_depth_deepest_folder_at_level_9_allowed(fake_dao):
    svc = _svc()
    # parent at level 7 = 第8层; folders A (level 8) + B (level 9 = 第10层) → allowed;
    # the FILE inside B lands at level 10 but files don't count as a layer
    parent = MagicMock(id=9, level=7, file_level_path="/1/2/3/4/5/6/7")
    svc._get_folder_for_action = AsyncMock(return_value=parent)
    await svc.upload_folder_items(5, _items("A/B/d.pdf"), parent_id=9)
    assert {r.level for r in fake_dao.rows} == {8, 9}


async def test_top_level_name_conflict_rejected(fake_dao):
    svc = _svc()
    with patch(f"{_SVC}.SpaceFileDao.count_folder_by_name", new=AsyncMock(return_value=1)):
        with pytest.raises(SpaceFolderDuplicateError):
            await svc.upload_folder_items(5, _items("Root/a.pdf"))
    assert fake_dao.rows == []


async def test_capacity_precheck_user_limit_rejects_batch(fake_dao):
    svc = _svc()
    with (
        patch(f"{_SVC}.QuotaService.get_knowledge_space_upload_limit_bytes", new=AsyncMock(return_value=100)),
        patch(f"{_SVC}.SpaceFileDao.get_user_total_file_size", new=AsyncMock(return_value=50)),
    ):
        with pytest.raises(SpaceFileSizeLimitError):
            await svc.upload_folder_items(
                5, _items("R/a.pdf", "R/b.pdf", "R/c.pdf", "R/d.pdf", "R/e.pdf", "R/f.pdf", size=10)
            )
    assert fake_dao.rows == []
    svc.add_file.assert_not_awaited()


async def test_capacity_precheck_tenant_limit_rejects_batch(fake_dao):
    svc = _svc()
    with (
        patch(f"{_SVC}.QuotaService.get_tenant_storage_remaining_bytes", new=AsyncMock(return_value=10)),
        patch(f"{_SVC}.QuotaService.get_tenant_storage_used_bytes", new=AsyncMock(return_value=0)),
    ):
        with pytest.raises(Exception) as exc_info:
            await svc.upload_folder_items(5, _items("R/a.pdf", "R/b.pdf", size=10))
    assert "quota" in type(exc_info.value).__name__.lower() or "Quota" in type(exc_info.value).__name__
    assert fake_dao.rows == []


# ── rollback on folder-create failure ──────────────────────────────────────


async def test_folder_create_failure_rolls_back_created_folders(fake_dao):
    svc = _svc()
    svc._initialize_child_resource_permissions = AsyncMock(side_effect=[None, RuntimeError("fga down")])
    with pytest.raises(RuntimeError):
        await svc.upload_folder_items(5, _items("Root/Sub/a.pdf"))
    created_ids = [r.id for r in fake_dao.rows]
    assert sorted(fake_dao.deleted) == sorted(created_ids)
    cleanup_arg = svc._cleanup_resource_tuples.await_args.args[0]
    assert sorted(cleanup_arg) == sorted([("folder", i) for i in created_ids])
    svc.add_file.assert_not_awaited()


# ── file-level duplicates do NOT reject the batch (AC-31) ──────────────────


async def test_file_dup_failed_entries_aggregate_without_raise(fake_dao):
    svc = _svc()
    failed_entry = MagicMock(status=3)
    ok_entry = MagicMock(status=2)
    svc.add_file = AsyncMock(side_effect=[[failed_entry], [ok_entry]])
    res = await svc.upload_folder_items(5, _items("Root/a.pdf", "Root/Sub/b.pdf"))
    assert failed_entry in res and ok_entry in res
