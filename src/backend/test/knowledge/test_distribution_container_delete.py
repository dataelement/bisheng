"""F098: folder deletion no longer refuses containers holding distributed files.

Two things must hold. Ordinary files keep going to the recycle bin, and
distribution entries must not join them there — the bin only sets a flag the
distribution state machine cannot see, so a shortcut resting in it would still
count as a live link.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

SPACE_ID = 20
FOLDER_ID = 900
TENANT_ID = 7
MODULE = "bisheng.knowledge.domain.services.knowledge_space_service"


def _service() -> KnowledgeSpaceService:
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=UserPayload(user_id=11, user_name="tester", tenant_id=TENANT_ID),
    )
    service._require_permission_id = AsyncMock()
    service._enqueue_container_distribution_cleanup = AsyncMock()
    service._notify_folder_deleted = AsyncMock()
    service.update_folder_update_time = AsyncMock()
    service._enqueue_recommendation_deleted_files = MagicMock()
    return service


def _folder() -> KnowledgeFile:
    return KnowledgeFile(
        id=FOLDER_ID,
        tenant_id=TENANT_ID,
        knowledge_id=SPACE_ID,
        file_name="待删目录",
        file_type=FileType.DIR.value,
        file_level_path="/8",
        level=1,
    )


def _plain_file(file_id: int) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=TENANT_ID,
        knowledge_id=SPACE_ID,
        file_name=f"plain-{file_id}.pdf",
        file_type=FileType.FILE.value,
        file_level_path=f"/8/{FOLDER_ID}",
        level=2,
    )


def _distribution_entry(file_id: int, entry_type: str) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=TENANT_ID,
        knowledge_id=SPACE_ID,
        file_name=f"entry-{file_id}.pdf",
        file_type=FileType.FILE.value,
        file_level_path=f"/8/{FOLDER_ID}",
        level=2,
        reference_document_id=500 + file_id,
        entry_type=entry_type,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
    )


async def _run_delete_folder(service: KnowledgeSpaceService, children: list[KnowledgeFile]):
    recycle = SimpleNamespace(soft_delete_file_ids=AsyncMock())
    space = Knowledge(
        id=SPACE_ID,
        tenant_id=TENANT_ID,
        name="库",
        type=KnowledgeTypeEnum.SPACE.value,
        state=KnowledgeState.PUBLISHED.value,
    )
    service._get_folder_for_action = AsyncMock(return_value=_folder())
    # Mirror the real planner: whatever ids the caller hands in are the ids that
    # reach the recycle bin, so the filtering under test stays visible here.
    service._plan_cascade_version_links_on_delete = AsyncMock(
        side_effect=lambda file_ids: SimpleNamespace(expanded_file_ids=list(file_ids))
    )
    service._apply_cascade_version_delete_plan = AsyncMock()
    service._cleanup_review_tags_for_deleted_files = AsyncMock()
    service._prepare_favorite_delete_events = AsyncMock(return_value=[])
    service._ensure_space_async_task_tenant_consistency = MagicMock()

    with (
        patch(f"{MODULE}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=space)),
        patch(f"{MODULE}._require_not_write_frozen", new=AsyncMock()),
        patch(
            f"{MODULE}.SpaceFileDao.get_children_by_prefix",
            new=AsyncMock(return_value=children),
        ),
        patch(f"{MODULE}.KnowledgeDao.async_update_knowledge_update_time_by_id", new=AsyncMock()),
        patch(f"{MODULE}.enqueue_favorite_change_events", new=MagicMock()),
        patch(
            "bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeRecycleService",
            return_value=recycle,
        ),
    ):
        await service.delete_folder(SPACE_ID, FOLDER_ID)
    return recycle


@pytest.mark.asyncio
async def test_folder_delete_allows_distribution_entries():
    """The old hard refusal is gone: the folder deletes and the sweep is queued."""
    service = _service()
    children = [
        _plain_file(101),
        _distribution_entry(102, KnowledgeFileEntryType.PUBLISH.value),
    ]

    await _run_delete_folder(service, children)

    service._enqueue_container_distribution_cleanup.assert_awaited_once()
    kwargs = service._enqueue_container_distribution_cleanup.await_args.kwargs
    assert kwargs["space_id"] == SPACE_ID
    assert kwargs["folder_prefix"] == f"/8/{FOLDER_ID}"


@pytest.mark.asyncio
async def test_distribution_entries_skip_recycle_bin():
    """Plain files are restorable; distribution entries must never be."""
    service = _service()
    children = [
        _plain_file(101),
        _distribution_entry(102, KnowledgeFileEntryType.PUBLISH.value),
        _distribution_entry(103, KnowledgeFileEntryType.MANAGER.value),
    ]

    recycle = await _run_delete_folder(service, children)

    planned_ids = service._plan_cascade_version_links_on_delete.await_args.args[0]
    assert planned_ids == [101]
    recycle_kwargs = recycle.soft_delete_file_ids.await_args.kwargs
    assert 102 not in recycle_kwargs["file_ids"]
    assert 103 not in recycle_kwargs["file_ids"]


@pytest.mark.asyncio
async def test_folder_without_distribution_entries_skips_the_sweep():
    service = _service()

    await _run_delete_folder(service, [_plain_file(101)])

    service._enqueue_container_distribution_cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_preflight_reports_rollback_and_permanent_counts():
    service = _service()
    manager_rollback = _distribution_entry(201, KnowledgeFileEntryType.MANAGER.value)
    manager_permanent = _distribution_entry(202, KnowledgeFileEntryType.MANAGER.value)
    children = [
        _plain_file(101),
        manager_rollback,
        manager_permanent,
        _distribution_entry(203, KnowledgeFileEntryType.PUBLISH.value),
        _distribution_entry(204, KnowledgeFileEntryType.SHARE.value),
    ]
    service._get_folder_for_action = AsyncMock(return_value=_folder())
    service.document_distribution_service = SimpleNamespace(
        preflight_delete_entry=AsyncMock(side_effect=["rollback", "final_delete"])
    )

    with patch(
        f"{MODULE}.SpaceFileDao.get_children_by_prefix",
        new=AsyncMock(return_value=children),
    ):
        summary = await service.preflight_container_delete(
            space_id=SPACE_ID,
            folder_id=FOLDER_ID,
        )

    assert summary["rollback_count"] == 1
    assert summary["permanent_delete_count"] == 1
    assert summary["soft_link_count"] == 1
    assert summary["share_count"] == 1
    assert summary["recyclable_count"] == 1
    assert summary["irreversible"] is True
    assert summary["rollback_samples"] == [
        {"file_id": 201, "file_name": "entry-201.pdf"}
    ]


@pytest.mark.asyncio
async def test_preflight_marks_plain_container_reversible():
    service = _service()
    service._get_folder_for_action = AsyncMock(return_value=_folder())

    with patch(
        f"{MODULE}.SpaceFileDao.get_children_by_prefix",
        new=AsyncMock(return_value=[_plain_file(101)]),
    ):
        summary = await service.preflight_container_delete(
            space_id=SPACE_ID,
            folder_id=FOLDER_ID,
        )

    assert summary["irreversible"] is False
    assert summary["recyclable_count"] == 1
