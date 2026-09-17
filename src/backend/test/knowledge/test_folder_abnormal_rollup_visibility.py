"""Folder anomaly rollups avoid descendant permission fanout."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, call

from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    FolderDescendantStatusFlags,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _service(states: dict[int, FolderDescendantStatusFlags], *, login_user_id: int = 42):
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=login_user_id, tenant_id=1)
    repository = SimpleNamespace(find_folder_descendant_status_flags=AsyncMock(return_value=states))
    service.knowledge_file_repo = repository
    # 909 only: the rollup is followed by the F046 file-change approval pass, which
    # needs a live request/OpenFGA. These tests are about the rollup itself, so the
    # approval pass is stubbed out rather than dragged in.
    service._enrich_file_change_approval_views = AsyncMock(side_effect=lambda _res, result: result)
    return service, repository


def _folder(folder_id: int = 10, space_id: int = 7):
    return KnowledgeFile(
        id=folder_id,
        knowledge_id=space_id,
        file_type=FileType.DIR,
        file_level_path="",
        file_name="folder",
    )


def test_abnormal_statuses_are_centralized_on_the_enum():
    assert KnowledgeFileStatus.abnormal_values() == {
        KnowledgeFileStatus.FAILED.value,
        KnowledgeFileStatus.TIMEOUT.value,
        KnowledgeFileStatus.VIOLATION.value,
    }
    assert KnowledgeFileStatus.is_abnormal(KnowledgeFileStatus.TIMEOUT.value) is True
    assert KnowledgeFileStatus.is_abnormal(KnowledgeFileStatus.SUCCESS.value) is False


async def test_creator_gets_both_flags_from_one_batch_lookup():
    service, repository = _service(
        {
            10: FolderDescendantStatusFlags(
                has_abnormal_files=True,
                has_processing_files=False,
            ),
            11: FolderDescendantStatusFlags(
                has_abnormal_files=False,
                has_processing_files=True,
            ),
        }
    )

    first, second = await service._handle_file_folder_extra_info(
        [_folder(10), _folder(11)],
        space_creator_user_id=42,
    )

    assert first["has_failed_files"] is True
    assert first["has_abnormal_files"] is True
    assert first["has_processing_files"] is False
    assert second["has_failed_files"] is False
    assert second["has_abnormal_files"] is False
    assert second["has_processing_files"] is True
    repository.find_folder_descendant_status_flags.assert_awaited_once_with(
        7,
        {10: "/10", 11: "/11"},
        excluded_file_ids=None,
    )


async def test_non_creator_does_not_receive_the_abnormal_display_signal():
    service, repository = _service(
        {
            10: FolderDescendantStatusFlags(
                has_abnormal_files=True,
                has_processing_files=False,
            )
        }
    )

    (result,) = await service._handle_file_folder_extra_info(
        [_folder()],
        space_creator_user_id=99,
    )

    assert result["has_failed_files"] is True
    assert result["has_abnormal_files"] is False
    repository.find_folder_descendant_status_flags.assert_awaited_once_with(7, {10: "/10"}, excluded_file_ids=None)


async def test_legacy_counts_are_removed_when_folder_has_no_tracked_descendants():
    service, repository = _service({})

    (result,) = await service._handle_file_folder_extra_info(
        [_folder()],
        space_creator_user_id=42,
    )

    assert result["has_failed_files"] is False
    assert result["has_abnormal_files"] is False
    assert result["has_processing_files"] is False
    assert "success_file_num" not in result
    assert "processing_file_num" not in result
    repository.find_folder_descendant_status_flags.assert_awaited_once_with(7, {10: "/10"}, excluded_file_ids=None)


async def test_search_parent_and_child_folders_use_separate_prefix_groups():
    service, repository = _service({})
    repository.find_folder_descendant_status_flags.side_effect = [
        {10: FolderDescendantStatusFlags(has_abnormal_files=True, has_processing_files=False)},
        {11: FolderDescendantStatusFlags(has_abnormal_files=False, has_processing_files=True)},
    ]
    child = _folder(11)
    child.file_level_path = "/10"

    parent_result, child_result = await service._handle_file_folder_extra_info(
        [_folder(10), child],
        space_creator_user_id=42,
    )

    assert parent_result["has_abnormal_files"] is True
    assert child_result["has_processing_files"] is True
    assert repository.find_folder_descendant_status_flags.await_args_list == [
        call(7, {10: "/10"}, excluded_file_ids=None),
        call(7, {11: "/10/11"}, excluded_file_ids=None),
    ]


async def test_file_change_hidden_files_are_kept_out_of_the_rollup():
    """909 only: a file hidden by file-change approval must not light up its folder."""
    service, repository = _service(
        {10: FolderDescendantStatusFlags(has_abnormal_files=False, has_processing_files=False)}
    )

    (result,) = await service._handle_file_folder_extra_info(
        [_folder()],
        space_creator_user_id=42,
        file_change_excluded_ids={501, 502},
    )

    assert result["has_abnormal_files"] is False
    repository.find_folder_descendant_status_flags.assert_awaited_once_with(
        7,
        {10: "/10"},
        excluded_file_ids={501, 502},
    )
