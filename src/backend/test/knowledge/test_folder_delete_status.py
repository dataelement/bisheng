from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.knowledge_space import SpaceFileChangeConflictError
from bisheng.knowledge.domain.models.folder_deletion import (
    RESERVED_KEY,
    FolderStatus,
    ensure_owner,
    make_marker,
    project_folder,
    public_metadata,
)

NOW = datetime(2026, 11, 5, tzinfo=UTC)
TOKEN = "cdf51303-4410-4dc3-a224-2ba12f17386e"


def folder(status=8):
    return SimpleNamespace(
        id=5, file_type=0, status=status, user_metadata={"color": "blue", RESERVED_KEY: make_marker(TOKEN, 7, NOW)}
    )


def test_stale_heartbeat_is_unknown_but_still_owns_the_fence():
    root = folder()
    assert project_folder(root, NOW).state == "running"
    assert project_folder(root, NOW + timedelta(seconds=60)).state == "unknown"
    ensure_owner(root, TOKEN)
    root.status = FolderStatus.NORMAL
    with pytest.raises(SpaceFileChangeConflictError):
        ensure_owner(root, TOKEN)


def test_corrupt_marker_stays_unknown_without_reconcile_identity():
    root = folder()
    root.user_metadata[RESERVED_KEY] = {"operation_id": TOKEN}
    state = project_folder(root, NOW)
    assert state.state == "unknown" and not state.can_reconcile
    assert state.operation_id == TOKEN
    with pytest.raises(SpaceFileChangeConflictError):
        ensure_owner(root, TOKEN)


def test_reserved_metadata_is_never_public():
    root = folder()
    assert public_metadata(root.user_metadata) == {"color": "blue"}
    assert RESERVED_KEY in root.user_metadata


async def test_empty_folder_projects_ancestor_scope():
    from unittest.mock import AsyncMock, MagicMock

    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService

    parent = folder()
    parent.file_level_path = ""
    service = KnowledgeFolderDeletionService(12, MagicMock())
    service.repository = MagicMock(
        return_value=SimpleNamespace(folders=AsyncMock(return_value={}), now=AsyncMock(return_value=NOW))
    )
    scope = await service.project_page([], [], parent)
    assert scope == {"root_folder_id": 5, "operation_id": TOKEN, "state": "running", "retry_after_ms": 3000}


def test_mutation_result_keeps_private_marker_out_of_rename_responses():
    from bisheng.knowledge.api.endpoints.knowledge_space import _resource_payload

    response = _resource_payload({"id": 5, "user_metadata": folder().user_metadata})
    assert response["user_metadata"] == {"color": "blue"}


async def test_uncertain_batch_result_retains_token_and_is_distinct_from_a_definite_failure():
    from unittest.mock import AsyncMock

    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import FolderCommitUncertain
    from bisheng.knowledge.domain.services.knowledge_space_file_change_service import (
        FileChangeRequestCommand,
        KnowledgeSpaceFileChangeService,
    )

    command = FileChangeRequestCommand(
        action="delete",
        resource_type="folder",
        resource_id=5,
        space_id=12,
        applicant_user_id=7,
        applicant_user_name="user",
        resource_name="folder",
    )
    service = object.__new__(KnowledgeSpaceFileChangeService)
    service.request_change = AsyncMock(side_effect=FolderCommitUncertain("commit unknown", TOKEN))
    (result,) = await service.request_changes([command])
    assert result.outcome_unknown and result.operation_id == TOKEN and result.decision == "invalid"


def test_status_request_rejects_ids_outside_database_integer_range():
    from pydantic import ValidationError

    from bisheng.knowledge.domain.schemas.folder_deletion import FolderDeletionQuery, FolderReconcileRequest

    with pytest.raises(ValidationError):
        FolderDeletionQuery(folder_ids=[10**200])
    with pytest.raises(ValidationError):
        FolderReconcileRequest(folder_id=10**200)


async def test_authorized_reconcile_pool_failure_stays_unknown():
    from unittest.mock import AsyncMock

    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from bisheng.knowledge.domain.models.folder_deletion import DeletionStatus
    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService

    svc = KnowledgeFolderDeletionService(12)
    item = DeletionStatus(folder_id=5, state="unknown", operation_id=TOKEN, can_reconcile=True)
    svc.query = AsyncMock(return_value=[item])
    svc._update = AsyncMock(side_effect=PoolTimeout("pool exhausted"))
    assert await svc.reconcile(None, 5, TOKEN) == item
    svc.query.assert_awaited_once()


async def test_unprivileged_guessed_closed_approval_id_and_unknown_id_are_indistinguishable():
    from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService

    root = SimpleNamespace(id=5, status=2, file_type=0, user_metadata={})
    old = SimpleNamespace(
        applicant_user_id=7, approval_instance_id=4, cutover_state=None, resource_id=5, execution_state="closed"
    )
    audience = {"user_id": 1, "space_visible": True, "manager": False}
    for token, row in [("approval-1", old), ("approval-3", None)]:
        item = KnowledgeFolderDeletionService._visible_item(root, NOW, token, row, {}, None, **audience)
        assert item.state == "unavailable" and item.operation_id is None and item.failure_reason is None
