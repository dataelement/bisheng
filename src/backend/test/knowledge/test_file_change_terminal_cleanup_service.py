from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
    KnowledgeSpaceUploadStageRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_terminal_cleanup_service import (
    KnowledgeSpaceFileChangeTerminalCleanupService,
)

TENANT_ID = 42
REQUEST_ID = 81
UPLOAD_ID = "01a02c03-0405-4607-8809-0a0b0c0d0e0f"


def _request(
    *,
    execution_state: str = KnowledgeSpaceFileChangeExecutionState.FAILED,
    cleanup_state: str = KnowledgeSpaceFileChangeCleanupState.NONE,
    upload_stage_id: int | None = None,
) -> KnowledgeSpaceFileChangeRequest:
    return KnowledgeSpaceFileChangeRequest(
        id=REQUEST_ID,
        tenant_id=TENANT_ID,
        space_id=8,
        action=KnowledgeSpaceFileChangeAction.UPLOAD,
        resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
        applicant_user_id=7,
        business_key="knowledge-space-change:81",
        request_fingerprint="fingerprint",
        execution_state=execution_state,
        cleanup_state=cleanup_state,
        upload_stage_id=upload_stage_id,
    )


async def test_cleanup_persists_pending_before_owner_cleanup_and_closes_after_success() -> None:
    request = _request()
    states: list[str] = []

    async def save_request(*, tenant_id: int, request_id: int, upload_id: str, cleanup_state: str):
        assert (tenant_id, request_id, upload_id) == (TENANT_ID, REQUEST_ID, UPLOAD_ID)
        request.cleanup_state = cleanup_state
        if cleanup_state == KnowledgeSpaceFileChangeCleanupState.SUCCESS:
            request.execution_state = KnowledgeSpaceFileChangeExecutionState.CLOSED
        states.append(cleanup_state)
        return request

    owner_cleanup = AsyncMock(return_value=SimpleNamespace(state="cleaned"))
    service = KnowledgeSpaceFileChangeTerminalCleanupService(
        request_loader=AsyncMock(return_value=request),
        cleanup_state_saver=save_request,
        upload_stage_cleanup=owner_cleanup,
    )

    await service.cleanup(
        tenant_id=TENANT_ID,
        request_id=REQUEST_ID,
        upload_id=UPLOAD_ID,
        terminal_action="rejected",
        reason="no",
    )

    assert states == [KnowledgeSpaceFileChangeCleanupState.PENDING, KnowledgeSpaceFileChangeCleanupState.SUCCESS]
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.CLOSED
    owner_cleanup.assert_awaited_once_with(UPLOAD_ID)


async def test_cleanup_failure_stays_pending_and_is_retryable() -> None:
    request = _request()
    states: list[str] = []

    async def save_request(**kwargs):
        request.cleanup_state = kwargs["cleanup_state"]
        states.append(kwargs["cleanup_state"])
        return request

    service = KnowledgeSpaceFileChangeTerminalCleanupService(
        request_loader=AsyncMock(return_value=request),
        cleanup_state_saver=save_request,
        upload_stage_cleanup=AsyncMock(side_effect=OSError("storage unavailable")),
    )

    with pytest.raises(OSError, match="storage unavailable"):
        await service.cleanup(
            tenant_id=TENANT_ID,
            request_id=REQUEST_ID,
            upload_id=UPLOAD_ID,
            terminal_action="withdrawn",
            reason=None,
        )

    assert states == [KnowledgeSpaceFileChangeCleanupState.PENDING]
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED


async def test_cleanup_rejects_unbound_upload_before_owner_cleanup() -> None:
    owner_cleanup = AsyncMock()
    service = KnowledgeSpaceFileChangeTerminalCleanupService(
        request_loader=AsyncMock(return_value=None),
        cleanup_state_saver=AsyncMock(),
        upload_stage_cleanup=owner_cleanup,
    )

    with pytest.raises(LookupError, match="bound stage"):
        await service.cleanup(
            tenant_id=TENANT_ID,
            request_id=REQUEST_ID,
            upload_id=UPLOAD_ID,
            terminal_action="rejected",
            reason=None,
        )

    owner_cleanup.assert_not_awaited()


async def test_default_loader_checks_request_to_stage_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    request_lookup = AsyncMock(return_value=_request(upload_stage_id=501))
    stage_lookup = AsyncMock(return_value=SimpleNamespace(id=999))
    monkeypatch.setattr(KnowledgeSpaceFileChangeRequestRepository, "get_by_id", request_lookup)
    monkeypatch.setattr(KnowledgeSpaceUploadStageRepository, "get_by_upload_id", stage_lookup)

    result = await KnowledgeSpaceFileChangeTerminalCleanupService._load_bound_request(
        tenant_id=TENANT_ID,
        request_id=REQUEST_ID,
        upload_id=UPLOAD_ID,
        for_update=True,
        session=object(),
    )

    assert result is None
    request_lookup.assert_awaited_once_with(tenant_id=TENANT_ID, request_id=REQUEST_ID, for_update=True)
    stage_lookup.assert_awaited_once_with(tenant_id=TENANT_ID, upload_id=UPLOAD_ID, for_update=True)


async def test_cleanup_success_is_idempotent() -> None:
    save = AsyncMock()
    owner_cleanup = AsyncMock()
    service = KnowledgeSpaceFileChangeTerminalCleanupService(
        request_loader=AsyncMock(
            return_value=_request(
                execution_state=KnowledgeSpaceFileChangeExecutionState.CLOSED,
                cleanup_state=KnowledgeSpaceFileChangeCleanupState.SUCCESS,
            )
        ),
        cleanup_state_saver=save,
        upload_stage_cleanup=owner_cleanup,
    )

    await service.cleanup(
        tenant_id=TENANT_ID,
        request_id=REQUEST_ID,
        upload_id=UPLOAD_ID,
        terminal_action="cancelled",
        reason=None,
    )

    save.assert_not_awaited()
    owner_cleanup.assert_not_awaited()


async def test_cleanup_success_backfills_closed_without_repeating_storage_cleanup() -> None:
    request = _request(cleanup_state=KnowledgeSpaceFileChangeCleanupState.SUCCESS)

    async def save(**kwargs):
        assert kwargs["cleanup_state"] == KnowledgeSpaceFileChangeCleanupState.SUCCESS
        request.execution_state = KnowledgeSpaceFileChangeExecutionState.CLOSED
        return request

    service = KnowledgeSpaceFileChangeTerminalCleanupService(
        request_loader=AsyncMock(return_value=request),
        cleanup_state_saver=AsyncMock(side_effect=save),
        upload_stage_cleanup=AsyncMock(),
    )

    persisted = await service.cleanup(
        tenant_id=TENANT_ID,
        request_id=REQUEST_ID,
        upload_id=UPLOAD_ID,
        terminal_action="cancelled",
        reason=None,
    )

    assert persisted.execution_state == KnowledgeSpaceFileChangeExecutionState.CLOSED
    service.cleanup_state_saver.assert_awaited_once()
    service.upload_stage_cleanup.assert_not_awaited()
