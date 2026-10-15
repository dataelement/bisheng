"""Commit direct deletions with the same durable purge ledger as F046."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from loguru import logger

from bisheng.common.errcode.knowledge_space import SpaceFileChangeConflictError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeLockScope,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_execution_step_repository import (
    KnowledgeSpaceFileChangeExecutionStepRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
    FootprintEntry,
    KnowledgeSpaceFileChangeFootprintRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository import KnowledgeSpaceMutationRepository
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgeFilePermissionRecord
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import DeleteExecutionStepCode


async def _dispatch_purge(*, tenant_id: int, request_id: int, execution_token: str) -> None:
    from bisheng.worker.knowledge.file_change_tasks import purge_file_change_delete

    purge_file_change_delete.apply_async(
        kwargs={"request_id": request_id, "execution_token": execution_token},
        headers={"tenant_id": tenant_id},
    )


class KnowledgeSpaceDirectDeleteService:
    """Keep DB failure reversible; retain external cleanup intent after commit."""

    def __init__(
        self,
        *,
        authorize: Callable[[str, int, str], Awaitable[None]],
        load_permission_records: Callable[[list[tuple[str, int]]], Awaitable[list[KnowledgeFilePermissionRecord]]],
        session_factory=get_async_db_session,
        repository_factory=KnowledgeSpaceMutationRepository,
        dispatch_purge: Callable = _dispatch_purge,
    ) -> None:
        self.authorize = authorize
        self.load_permission_records = load_permission_records
        self.session_factory = session_factory
        self.repository_factory = repository_factory
        self.dispatch_purge = dispatch_purge

    async def delete(self, *, resource: KnowledgeFile, applicant_user_id: int) -> dict:
        tenant_id = get_current_tenant_id()
        if tenant_id is None or int(resource.tenant_id) != int(tenant_id):
            raise RuntimeError("direct deletion requires the resource tenant context")
        tenant_id = int(tenant_id)
        resource_type = "folder" if int(resource.file_type) == 0 else "knowledge_file"
        token = str(uuid4())
        async with self.session_factory() as session, session.begin():
            repository = self.repository_factory(session)
            manifest = await repository.build_delete_manifest(
                tenant_id=tenant_id,
                space_id=int(resource.knowledge_id),
                resource_id=int(resource.id),
                resource_type=resource_type,
                source_name=str(resource.file_name),
                source_path=str(resource.file_level_path or ""),
                source_level=int(resource.level or 0),
            )
            resources = [(str(item["resource_type"]), int(item["resource_id"])) for item in manifest["fga_resources"]]
            # Check expanded version siblings too, while the manifest is locked.
            for kind, resource_id in resources:
                await self.authorize(kind, resource_id, "delete")
            records = await self.load_permission_records(resources)
            manifest["fga_permission_records"] = [asdict(record) for record in records]
            footprints = [
                FootprintEntry(
                    space_id=int(resource.knowledge_id),
                    resource_type=kind,
                    resource_id=resource_id,
                    path_root=(
                        f"{resource.file_level_path or ''}/{resource.id}"
                        if kind == "folder" and resource_id == int(resource.id)
                        else None
                    ),
                    lock_scope=(
                        KnowledgeSpaceFileChangeLockScope.SUBTREE
                        if kind == "folder" and resource_id == int(resource.id)
                        else KnowledgeSpaceFileChangeLockScope.EXACT
                    ),
                )
                for kind, resource_id in resources
            ]
            footprint_repository = KnowledgeSpaceFileChangeFootprintRepository(session)
            if await footprint_repository.find_blocking_request_ids(tenant_id=tenant_id, footprints=footprints):
                raise SpaceFileChangeConflictError()
            request = await KnowledgeSpaceFileChangeRequestRepository(session).add(
                tenant_id=tenant_id,
                request=KnowledgeSpaceFileChangeRequest(
                    space_id=int(resource.knowledge_id),
                    action=KnowledgeSpaceFileChangeAction.DELETE,
                    resource_type=resource_type,
                    resource_id=int(resource.id),
                    applicant_user_id=int(applicant_user_id),
                    business_key=f"direct-delete:{token}",
                    request_fingerprint=token,
                    file_name=str(resource.file_name),
                    execution_token=token,
                    execution_state=KnowledgeSpaceFileChangeExecutionState.APPLYING,
                    execution_checkpoint={
                        "direct_delete": True,
                        "delete_manifest": manifest,
                        "delete_phase": "purging",
                        "deletion_cutover_active": True,
                        "cutover_completed_at": datetime.now(UTC).isoformat(),
                        "deadline": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
                    },
                ),
            )
            request_id = int(request.id)
            await footprint_repository.add_many(tenant_id=tenant_id, request_id=request_id, footprints=footprints)
            steps = KnowledgeSpaceFileChangeExecutionStepRepository(session)
            await steps.ensure_steps(
                tenant_id=tenant_id,
                request_id=request_id,
                attempt_token=token,
                step_codes=DeleteExecutionStepCode.ALL,
            )
            await repository.apply_delete_cutover(tenant_id=tenant_id, manifest=manifest)
            for code in (DeleteExecutionStepCode.PREPARE, DeleteExecutionStepCode.DB_CUTOVER):
                if not await steps.mark_succeeded(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    step_code=code,
                    attempt_token=token,
                    result_digest=f"direct-delete:{request_id}:{code}",
                ):
                    raise RuntimeError("direct delete step identity changed during cutover")
        # The ledger is the outbox: the existing residue scan recovers a lost
        # broker publish or an API process crash after this DB commit.
        try:
            await self.dispatch_purge(tenant_id=tenant_id, request_id=request_id, execution_token=token)
        except Exception:
            logger.exception("Direct delete purge dispatch failed: request_id={} tenant_id={}", request_id, tenant_id)
        return manifest
