"""Large-space filters reuse business rows and bounded permission snapshots."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import InvalidCatalogActionError
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileDao
from bisheng.knowledge.domain.services import knowledge_file_visibility_service as visibility
from bisheng.knowledge.domain.services import knowledge_permission_service as permissions
from bisheng.permission.application import business_authorization as business
from bisheng.permission.application.control_state import PermissionResourceSnapshot
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_PERSONAL
from bisheng.permission.domain.services.permission_action_service import PermissionActor


@pytest.fixture
def batch_visibility(monkeypatch):
    rows = {
        index: SimpleNamespace(
            id=index,
            tenant_id=1,
            knowledge_id=10,
            file_type=FileType.FILE.value,
            file_level_path="",
            user_id=7,
            status=2,
            update_time=None,
        )
        for index in range(1, 1002)
    }
    state = SimpleNamespace(
        rows=rows,
        allowed={index for index in rows if index % 7},
        missing_snapshots=set(),
        modes={},
        active_io=0,
        peak_io=0,
    )

    async def io():
        state.active_io += 1
        state.peak_io = max(state.peak_io, state.active_io)
        try:
            await asyncio.sleep(0)
        finally:
            state.active_io -= 1

    async def load_files(ids):
        assert len(ids) <= 100
        await io()
        return [rows[index] for index in ids if index in rows]

    async def snapshots(keys):
        assert len(keys) <= 100
        await io()
        return {
            key: PermissionResourceSnapshot(
                tenant_id=key[0],
                resource_type=key[1],
                resource_id=key[2],
                version=4,
                context_version="permission-context-v4",
                mode=state.modes.get(int(key[2]), "INHERIT"),
                parent_type="knowledge_space",
                parent_id="10",
                projection_state="CURRENT",
            )
            for key in keys
            if int(key[2]) not in state.missing_snapshots
        }

    async def decide(actor, targets, action):
        assert len(targets) <= 100
        assert action == "visible"
        await io()
        return tuple(
            int(target.resource_id) in state.allowed and actor.data_scope != DATA_SCOPE_PERSONAL for target in targets
        )

    state.files = AsyncMock(side_effect=load_files)
    state.space = AsyncMock(return_value=SimpleNamespace(id=10, tenant_id=1, type=KnowledgeTypeEnum.SPACE.value))
    state.single_file = AsyncMock(side_effect=AssertionError("files must be loaded in batches"))
    state.versions = SimpleNamespace(
        get_permission_snapshots=AsyncMock(side_effect=snapshots),
        get_permission_version=AsyncMock(side_effect=AssertionError("single permission reads are forbidden")),
        mode_for_target=AsyncMock(side_effect=AssertionError("single mode reads are forbidden")),
    )
    state.runtime = SimpleNamespace(batch_check_actions=AsyncMock(side_effect=decide))
    adapter = permissions.F048KnowledgeFilePermissionAdapter(
        loader=permissions.KnowledgeFileDaoPermissionLoader(state.versions),
        permission=state.runtime,
    )
    state.adapter = AsyncMock(return_value=adapter)
    monkeypatch.setattr(KnowledgeFileDao, "aget_file_by_ids", state.files)
    monkeypatch.setattr(KnowledgeFileDao, "query_by_id", state.single_file)
    monkeypatch.setattr(KnowledgeDao, "aquery_by_id", state.space)
    monkeypatch.setattr(visibility, "get_f048_resource_adapter", state.adapter)
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=state.runtime))
    monkeypatch.setattr(permissions, "emit_metric", lambda *args, **kwargs: None)

    def service():
        result = visibility.KnowledgeFileVisibilityService(
            request=None, login_user=SimpleNamespace(user_id=7, tenant_id=1, is_global_super=False)
        )
        result._non_primary_ids = AsyncMock(return_value=set())
        result._list_primary_file_ids_in_space = AsyncMock(return_value=set(rows))
        result._config = lambda: SimpleNamespace(index_filter_threshold=10000)
        return result

    state.service = service
    return state


@pytest.mark.parametrize("prefilter", [True, False])
async def test_thousand_file_filters_use_bounded_bulk_loading(batch_visibility, prefilter):
    state = batch_visibility
    service = state.service()
    if prefilter:
        result = await service.build_index_prefilter(10, None)
        assert result.milvus_expr == f"document_id in {sorted(state.allowed)}"
        assert result.accessible_size == len(state.allowed)
    else:
        assert await service.post_filter_visible_files(10, state.rows) == state.allowed

    state.space.assert_awaited_once_with(10)
    assert state.files.await_count == 11
    assert state.versions.get_permission_snapshots.await_count == 11
    assert state.runtime.batch_check_actions.await_count == 11
    assert state.peak_io == 1
    state.single_file.assert_not_awaited()
    state.versions.get_permission_version.assert_not_awaited()
    state.versions.mode_for_target.assert_not_awaited()


async def test_concurrent_large_space_filters_do_not_multiply_connections_by_files(batch_visibility):
    state = batch_visibility

    async def request(prefilter):
        service = state.service()
        if prefilter:
            result = await service.build_index_prefilter(10, None)
            return result.accessible_size
        return len(await service.post_filter_visible_files(10, state.rows))

    results = await asyncio.wait_for(asyncio.gather(*(request(index % 2) for index in range(8))), timeout=10)

    assert results == [len(state.allowed)] * 8
    assert state.space.await_count == 8
    assert state.files.await_count == 88
    assert state.versions.get_permission_snapshots.await_count == 88
    assert state.peak_io <= 8
    state.single_file.assert_not_awaited()


async def test_folder_tag_scope_and_primary_versions_remain_intersected(batch_visibility):
    state = batch_visibility
    service = state.service()
    service._non_primary_ids = AsyncMock(return_value={9})
    service._list_primary_file_ids_in_space = AsyncMock(return_value={1, 2, 3, 4})

    result = await service.build_index_prefilter(10, [2, 4, 9, 99999])

    assert result.milvus_expr == "document_id in [2, 4]"
    state.files.assert_awaited_once_with([2, 4])


async def test_postfilter_rechecks_permission_changes_after_prefilter(batch_visibility):
    state = batch_visibility
    service = state.service()
    await service.build_index_prefilter(10, None)
    state.allowed.remove(1)

    assert await service.post_filter_retrievable_files(10, [1, 2]) == {2}
    assert state.versions.get_permission_snapshots.await_count == 12


async def test_invalid_missing_and_cross_space_targets_stay_invisible(batch_visibility):
    state = batch_visibility
    for index in list(state.rows):
        if index > 10:
            del state.rows[index]
    state.rows[2].knowledge_id = 99
    state.rows[3].tenant_id = 99
    state.rows[4].file_type = FileType.DIR.value
    state.rows[5].status = -1
    state.missing_snapshots.add(6)
    state.modes[8] = "INVALID"
    state.rows[9].file_level_path = "9"

    result = await state.service().post_filter_visible_files(10, range(1, 12))

    assert result == {1, 10}


@pytest.mark.parametrize("prefilter", [True, False])
async def test_empty_inputs_do_not_initialize_permissions(batch_visibility, prefilter):
    state = batch_visibility
    service = state.service()
    if prefilter:
        service._list_primary_file_ids_in_space.return_value = set()
        assert (await service.build_index_prefilter(10, None)).is_empty
    else:
        assert await service.post_filter_visible_files(10, []) == set()
    state.space.assert_not_awaited()
    state.files.assert_not_awaited()
    state.adapter.assert_not_awaited()


async def test_missing_space_has_no_visible_files(batch_visibility):
    state = batch_visibility
    state.space.return_value = None

    assert await state.service().post_filter_visible_files(10, [1]) == set()
    state.files.assert_not_awaited()
    state.adapter.assert_not_awaited()


async def test_disabled_visible_action_still_returns_no_access(batch_visibility):
    state = batch_visibility
    state.runtime.batch_check_actions.side_effect = InvalidCatalogActionError()

    assert await state.service().post_filter_visible_files(10, [1]) == set()


async def test_super_admin_preserves_shortcut_but_narrowed_token_reaches_runtime(batch_visibility):
    state = batch_visibility
    service = state.service()
    token = set_current_permission_actor(PermissionActor(user_id=7, current_tenant_id=1, super_admin=True))
    try:
        assert await service.post_filter_visible_files(10, [1, 7, 99999]) == {1, 7}
    finally:
        reset_current_permission_actor(token)
    state.space.assert_not_awaited()
    state.adapter.assert_not_awaited()
    state.versions.get_permission_snapshots.assert_not_awaited()
    state.runtime.batch_check_actions.assert_not_awaited()

    token = set_current_permission_actor(
        PermissionActor(user_id=7, current_tenant_id=1, super_admin=True, data_scope=DATA_SCOPE_PERSONAL)
    )
    try:
        assert await service.post_filter_visible_files(10, [1, 7]) == set()
    finally:
        reset_current_permission_actor(token)
    state.versions.get_permission_snapshots.assert_awaited_once()
    state.runtime.batch_check_actions.assert_awaited_once()


@pytest.mark.parametrize("failure", ["files", "snapshots", "decision"])
async def test_bulk_filter_errors_propagate_without_returning_unchecked_files(batch_visibility, failure):
    state = batch_visibility
    operation = {
        "files": state.files,
        "snapshots": state.versions.get_permission_snapshots,
        "decision": state.runtime.batch_check_actions,
    }[failure]
    operation.side_effect = RuntimeError("dependency unavailable")

    with pytest.raises(RuntimeError, match="dependency unavailable"):
        await state.service().post_filter_visible_files(10, [1])
