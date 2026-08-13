from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
)

RequestLoader = Callable[..., Awaitable[KnowledgeSpaceFileChangeRequest | None]]


class KnowledgeSpaceFileChangeTerminalCleanupService:
    """Recoverably clean an upload stage after an approval terminal state."""

    def __init__(
        self,
        *,
        request_loader: RequestLoader | None = None,
        cleanup_state_saver: Callable[..., Awaitable[KnowledgeSpaceFileChangeRequest]] | None = None,
        upload_stage_cleanup: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self.request_loader = request_loader or self._load_bound_request
        self.cleanup_state_saver = cleanup_state_saver or self._save_cleanup_state
        self.upload_stage_cleanup = upload_stage_cleanup or self._cleanup_upload_stage

    async def cleanup(
        self,
        *,
        tenant_id: int,
        request_id: int,
        upload_id: str,
        terminal_action: str,
        reason: str | None,
    ) -> KnowledgeSpaceFileChangeRequest:
        del terminal_action, reason
        request = await self.request_loader(
            tenant_id=int(tenant_id),
            request_id=int(request_id),
            upload_id=str(upload_id),
        )
        if request is None:
            raise LookupError(f"upload change request or bound stage not found: {request_id}")
        if request.action != KnowledgeSpaceFileChangeAction.UPLOAD:
            raise ValueError(f"terminal upload cleanup cannot clean action={request.action}")
        if request.cleanup_state == KnowledgeSpaceFileChangeCleanupState.SUCCESS:
            if request.execution_state == KnowledgeSpaceFileChangeExecutionState.CLOSED:
                return request
            return await self.cleanup_state_saver(
                tenant_id=int(tenant_id),
                request_id=int(request_id),
                upload_id=str(upload_id),
                cleanup_state=KnowledgeSpaceFileChangeCleanupState.SUCCESS,
            )

        request = await self.cleanup_state_saver(
            tenant_id=int(tenant_id),
            request_id=int(request_id),
            upload_id=str(upload_id),
            cleanup_state=KnowledgeSpaceFileChangeCleanupState.PENDING,
        )
        await self.upload_stage_cleanup(str(upload_id))
        return await self.cleanup_state_saver(
            tenant_id=int(tenant_id),
            request_id=int(request_id),
            upload_id=str(upload_id),
            cleanup_state=KnowledgeSpaceFileChangeCleanupState.SUCCESS,
        )

    @staticmethod
    async def _load_bound_request(
        *,
        tenant_id: int,
        request_id: int,
        upload_id: str,
        for_update: bool = False,
        session=None,
    ) -> KnowledgeSpaceFileChangeRequest | None:
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )
        from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
            KnowledgeSpaceUploadStageRepository,
        )

        async def load(bound_session):
            request = await KnowledgeSpaceFileChangeRequestRepository(bound_session).get_by_id(
                tenant_id=tenant_id,
                request_id=request_id,
                for_update=for_update,
            )
            if request is None or request.upload_stage_id is None:
                return None
            stage = await KnowledgeSpaceUploadStageRepository(bound_session).get_by_upload_id(
                tenant_id=tenant_id,
                upload_id=upload_id,
                for_update=for_update,
            )
            if stage is None or int(stage.id) != int(request.upload_stage_id):
                return None
            return request

        if session is not None:
            return await load(session)
        async with get_async_db_session() as owned_session:
            return await load(owned_session)

    @classmethod
    async def _save_cleanup_state(
        cls,
        *,
        tenant_id: int,
        request_id: int,
        upload_id: str,
        cleanup_state: str,
    ) -> KnowledgeSpaceFileChangeRequest:
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )

        async with get_async_db_session() as session, session.begin():
            request = await cls._load_bound_request(
                tenant_id=tenant_id,
                request_id=request_id,
                upload_id=upload_id,
                for_update=True,
                session=session,
            )
            if request is None:
                raise LookupError(f"upload change request or bound stage not found: {request_id}")
            if request.action != KnowledgeSpaceFileChangeAction.UPLOAD:
                raise ValueError(f"terminal upload cleanup cannot clean action={request.action}")
            if (
                request.cleanup_state == KnowledgeSpaceFileChangeCleanupState.SUCCESS
                and request.execution_state == KnowledgeSpaceFileChangeExecutionState.CLOSED
            ):
                return request
            request.cleanup_state = cleanup_state
            if cleanup_state == KnowledgeSpaceFileChangeCleanupState.SUCCESS:
                request.execution_state = KnowledgeSpaceFileChangeExecutionState.CLOSED
            return await KnowledgeSpaceFileChangeRequestRepository(session).save(request)

    @staticmethod
    async def _cleanup_upload_stage(upload_id: str):
        from bisheng.core.storage.minio.minio_manager import get_minio_storage
        from bisheng.knowledge.domain.services.knowledge_space_upload_stage_service import (
            KnowledgeSpaceUploadStageService,
        )

        async def capacity_loader_not_used(_tenant_id: int, _user_id: int):
            raise RuntimeError("capacity loading is not used by upload-stage cleanup")

        storage = await get_minio_storage()
        service = KnowledgeSpaceUploadStageService(
            storage=storage,
            capacity_loader=capacity_loader_not_used,
        )
        return await service.cleanup(upload_id)


__all__ = ["KnowledgeSpaceFileChangeTerminalCleanupService"]
