"""Tenant-aware Celery reconciliation for F059 document projections."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlmodel import col

from bisheng.approval.domain.models.approval_instance import (
    ApprovalOutboxStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import (
    ApprovalInstanceRepository,
)
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import TenantDao
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
    KnowledgeDocumentProjectionService,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.approval.tasks import (
    execute_approval_outbox,
    retry_approval_outbox,
)
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)
KNOWLEDGE_QUEUE = "knowledge_celery"
SCAN_PAGE_SIZE = 100


async def _delete_entry_permissions(entry_id: int) -> None:
    from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
    from bisheng.permission.domain.services.permission_service import (
        PermissionService,
    )

    fga = await PermissionService._aget_fga()
    if fga is None:
        raise RuntimeError("OpenFGA unavailable during F059 cleanup")
    tuples = await fga.read_tuples(
        object=f"knowledge_file:{entry_id}"
    )
    operations = [
        TupleOperation(
            action="delete",
            user=str(item["user"]),
            relation=str(item["relation"]),
            object=f"knowledge_file:{entry_id}",
        )
        for item in tuples
        if item.get("user") and item.get("relation")
    ]
    if operations:
        await PermissionService.batch_write_tuples(
            operations,
            crash_safe=True,
            raise_on_failure=True,
            stop_on_failure=True,
        )


async def _strict_delete_minio_objects(
    files: list[KnowledgeFile],
    artifact_snapshots: list,
) -> None:
    from bisheng.api.services.knowledge_imp import (
        _artifact_owned_object_name,
        _knowledge_file_owned_object_names,
    )
    from bisheng.core.storage.minio.minio_manager import (
        get_minio_storage_sync,
    )

    object_names = {
        object_name
        for file in files
        for object_name in _knowledge_file_owned_object_names(file)
    }
    object_names.update(
        object_name
        for snapshot in artifact_snapshots
        if (object_name := _artifact_owned_object_name(snapshot))
    )

    def _delete() -> None:
        storage = get_minio_storage_sync()
        for object_name in sorted(object_names):
            storage.remove_object_sync(
                bucket_name=storage.bucket,
                object_name=object_name,
            )

    await asyncio.to_thread(_delete)


def _require_entries_ready_for_document_delete(
    entries: list[KnowledgeFile],
) -> None:
    """最终删除前, 所有入口必须已完成各自的投影清理。"""
    if any(
        item.entry_status != KnowledgeFileEntryStatus.DELETING.value
        or item.projection_status
        != KnowledgeFileProjectionStatus.READY.value
        for item in entries
    ):
        raise RuntimeError(
            "F059 final delete requires all entries to finish cleanup"
        )


async def _finalize_document_delete(entry: KnowledgeFile) -> None:
    from bisheng.api.services.knowledge_imp import delete_vector_files
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.knowledge.domain.services.knowledge_pdf_artifact_service import (
        get_pdf_artifact_deletion_snapshots,
    )

    document_id = int(entry.reference_document_id)
    tenant_id = int(entry.tenant_id)
    async with get_async_db_session() as session:
        document_repository = KnowledgeDocumentRepositoryImpl(session)
        version_repository = KnowledgeDocumentVersionRepositoryImpl(session)
        file_repository = KnowledgeFileRepositoryImpl(session)
        document = await document_repository.find_by_id_for_update(document_id)
        if (
            document is None
            or document.lifecycle_status
            != KnowledgeDocumentLifecycleStatus.DELETING.value
        ):
            return
        versions = await version_repository.find_by_document_id(document_id)
        physical_file_ids = [
            int(version.knowledge_file_id) for version in versions
        ]
        physical_files = list(
            await file_repository.find_by_ids(physical_file_ids)
        )
        entries = (
            await file_repository.find_distribution_entries_by_document_id(
                document_id,
                for_update=True,
            )
        )
        _require_entries_ready_for_document_delete(entries)
        await session.commit()

    artifact_snapshots = await get_pdf_artifact_deletion_snapshots(
        tenant_id,
        physical_file_ids,
    )
    knowledge = await KnowledgeDao.aquery_by_id(int(entry.knowledge_id))
    if knowledge is not None:
        await asyncio.to_thread(
            delete_vector_files,
            physical_file_ids,
            knowledge,
        )
    await _strict_delete_minio_objects(
        physical_files,
        artifact_snapshots,
    )
    for distribution_entry in entries:
        await _delete_entry_permissions(int(distribution_entry.id))

    async with get_async_db_session() as session:
        document_repository = KnowledgeDocumentRepositoryImpl(session)
        file_repository = KnowledgeFileRepositoryImpl(session)
        document = await document_repository.find_by_id_for_update(document_id)
        if (
            document is None
            or document.lifecycle_status
            != KnowledgeDocumentLifecycleStatus.DELETING.value
        ):
            return
        current_entries = (
            await file_repository.find_distribution_entries_by_document_id(
                document_id,
                for_update=True,
            )
        )
        _require_entries_ready_for_document_delete(current_entries)
        await session.execute(
            delete(KnowledgeFilePdfArtifact).where(
                col(KnowledgeFilePdfArtifact.knowledge_file_id).in_(
                    physical_file_ids
                )
            )
        )
        await session.execute(
            delete(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == document_id
            )
        )
        delete_file_ids = sorted(
            {
                *physical_file_ids,
                *(int(item.id) for item in current_entries),
            }
        )
        await file_repository.prepare_delete_by_ids(delete_file_ids)
        await session.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id
            )
        )
        await session.commit()


async def _finalize_deleting_entry(entry: KnowledgeFile) -> None:
    if entry.entry_type == KnowledgeFileEntryType.MANAGER.value:
        await _finalize_document_delete(entry)
        return
    await _delete_entry_permissions(int(entry.id))
    async with get_async_db_session() as session:
        repository = KnowledgeFileRepositoryImpl(session)
        current = await repository.find_by_id_for_update(int(entry.id))
        if current is None:
            return
        if (
            current.entry_status
            != KnowledgeFileEntryStatus.DELETING.value
            or current.projection_status
            != KnowledgeFileProjectionStatus.READY.value
        ):
            raise RuntimeError(
                "F059 logical entry cleanup state changed"
            )
        await repository.prepare_delete_by_ids([int(entry.id)])
        await session.commit()


async def _process_projection_async(
    *,
    tenant_id: int,
    entry_id: int,
    lease_owner: str,
) -> str:
    async with get_async_db_session() as session:
        repository = KnowledgeFileRepositoryImpl(session)
        service = KnowledgeDocumentProjectionService(
            session=session,
            file_repository=repository,
            document_repository=KnowledgeDocumentRepositoryImpl(session),
            version_repository=KnowledgeDocumentVersionRepositoryImpl(
                session
            ),
            deleting_entry_finalizer=_finalize_deleting_entry,
        )
        result = await service.process_entry(
            tenant_id=tenant_id,
            entry_id=entry_id,
            lease_owner=lease_owner,
        )
        return result.status


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    name=(
        "bisheng.worker.knowledge.document_projection."
        "process_document_projection"
    ),
)
def process_document_projection(
    task,
    tenant_id: int,
    entry_id: int,
) -> str:
    lease_owner = f"{task.request.id or uuid.uuid4()}:{entry_id}"
    return run_async_task(
        lambda: _process_projection_async(
            tenant_id=int(tenant_id),
            entry_id=int(entry_id),
            lease_owner=lease_owner,
        )
    )


async def _reconcile_permission_candidates(
    *,
    tenant_id: int,
    candidates: list[KnowledgeFile],
) -> int:
    dispatched = 0
    dispatched_approval_ids: set[int] = set()
    for entry in candidates:
        if (
            entry.entry_status
            != KnowledgeFileEntryStatus.PREPARING.value
        ):
            continue
        if (
            entry.entry_type
            == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value
            or (
                entry.entry_type
                == KnowledgeFileEntryType.MANAGER.value
                and entry.approval_instance_id is None
            )
        ):
            continue
        if entry.approval_instance_id is None:
            logger.error(
                "F059 aged preparing entry has no approval recovery key: "
                "tenant_id=%s entry_id=%s entry_type=%s",
                tenant_id,
                entry.id,
                entry.entry_type,
            )
            continue
        approval_instance_id = int(entry.approval_instance_id)
        if approval_instance_id in dispatched_approval_ids:
            continue
        dispatched_approval_ids.add(approval_instance_id)
        try:
            outboxes = await ApprovalInstanceRepository.list_outbox(
                approval_instance_id
            )
            if not outboxes:
                logger.error(
                    "F059 aged preparing entry has no approval outbox: "
                    "tenant_id=%s entry_id=%s approval_instance_id=%s",
                    tenant_id,
                    entry.id,
                    entry.approval_instance_id,
                )
                continue
            outbox = outboxes[-1]
            task = (
                execute_approval_outbox
                if outbox.status == ApprovalOutboxStatus.PENDING
                else retry_approval_outbox
            )
            task.apply_async(
                kwargs={"outbox_id": int(outbox.id)},
                headers={"tenant_id": int(tenant_id)},
            )
            dispatched += 1
        except Exception:
            logger.exception(
                "F059 permission reconcile dispatch failed: "
                "tenant_id=%s entry_id=%s approval_instance_id=%s",
                tenant_id,
                entry.id,
                entry.approval_instance_id,
            )
    return dispatched


async def _resume_rollback_async(
    *,
    tenant_id: int,
    document_id: int,
    manager_file_id: int,
) -> str:
    from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
        KnowledgeDocumentDistributionService,
    )
    from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
        KnowledgeDocumentPermissionActivationService,
    )

    async with get_async_db_session() as session:
        file_repository = KnowledgeFileRepositoryImpl(session)
        service = KnowledgeDocumentDistributionService(
            session=session,
            document_repository=KnowledgeDocumentRepositoryImpl(session),
            version_repository=KnowledgeDocumentVersionRepositoryImpl(
                session
            ),
            file_repository=file_repository,
            permission_activation_service=(
                KnowledgeDocumentPermissionActivationService(
                    file_repository=file_repository,
                )
            ),
        )
        result = await service.delete_manager(
            tenant_id=tenant_id,
            document_id=document_id,
            manager_file_id=manager_file_id,
        )
        if result.action != "rollback":
            raise RuntimeError(
                "F059 rollback reconcile reached an unexpected lifecycle"
            )
        return result.action


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    name=(
        "bisheng.worker.knowledge.document_projection."
        "reconcile_document_rollback"
    ),
)
def reconcile_document_rollback(
    task,
    tenant_id: int,
    document_id: int,
    manager_file_id: int,
) -> str:
    return run_async_task(
        lambda: _resume_rollback_async(
            tenant_id=int(tenant_id),
            document_id=int(document_id),
            manager_file_id=int(manager_file_id),
        )
    )


async def _reconcile_rollback_candidates(
    *,
    tenant_id: int,
    candidates: list[KnowledgeFile],
) -> int:
    dispatched = 0
    seen_documents: set[int] = set()
    for entry in candidates:
        if (
            entry.entry_type
            != KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value
            or entry.entry_status
            != KnowledgeFileEntryStatus.PREPARING.value
            or entry.reference_document_id is None
            or entry.projection_previous_file_id is None
        ):
            continue
        document_id = int(entry.reference_document_id)
        if document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        reconcile_document_rollback.apply_async(
            kwargs={
                "tenant_id": int(tenant_id),
                "document_id": document_id,
                "manager_file_id": int(
                    entry.projection_previous_file_id
                ),
            },
            headers={"tenant_id": int(tenant_id)},
            queue=KNOWLEDGE_QUEUE,
        )
        dispatched += 1
    return dispatched


async def _scan_tenant_projection_async(tenant_id: int) -> int:
    async with get_async_db_session() as session:
        repository = KnowledgeFileRepositoryImpl(session)
        service = KnowledgeDocumentProjectionService(
            session=session,
            file_repository=repository,
        )
        entry_ids = await service.list_due_entry_ids(
            limit=SCAN_PAGE_SIZE,
        )
        permission_candidates = (
            await repository.find_permission_reconcile_candidates(
                older_than=datetime.now() - timedelta(minutes=5),
                limit=SCAN_PAGE_SIZE,
            )
        )
    preparing_count = sum(
        1
        for item in permission_candidates
        if item.entry_status
        == KnowledgeFileEntryStatus.PREPARING.value
    )
    deleting_count = sum(
        1
        for item in permission_candidates
        if item.entry_status
        == KnowledgeFileEntryStatus.DELETING.value
    )
    logger.info(
        "F059 reconcile scan tenant_id=%s projection_due=%s "
        "aged_preparing=%s aged_deleting=%s page_size=%s",
        tenant_id,
        len(entry_ids),
        preparing_count,
        deleting_count,
        SCAN_PAGE_SIZE,
    )
    for entry_id in entry_ids:
        process_document_projection.apply_async(
            kwargs={
                "tenant_id": int(tenant_id),
                "entry_id": int(entry_id),
            },
            headers={"tenant_id": int(tenant_id)},
            queue=KNOWLEDGE_QUEUE,
        )
    await _reconcile_permission_candidates(
        tenant_id=tenant_id,
        candidates=permission_candidates,
    )
    await _reconcile_rollback_candidates(
        tenant_id=tenant_id,
        candidates=permission_candidates,
    )
    return len(entry_ids)


@bisheng_celery.task(
    name=(
        "bisheng.worker.knowledge.document_projection."
        "scan_tenant_document_projections"
    )
)
def scan_tenant_document_projections(tenant_id: int) -> int:
    current = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    if current != int(tenant_id):
        raise RuntimeError("F059 projection tenant header mismatch")
    return run_async_task(
        lambda: _scan_tenant_projection_async(int(tenant_id))
    )


async def _fanout_projection_scan_async() -> int:
    tenant_ids = [
        DEFAULT_TENANT_ID,
        *(
            await TenantDao.aget_children_ids_active(
                DEFAULT_TENANT_ID
            )
        ),
    ]
    for tenant_id in sorted({int(item) for item in tenant_ids}):
        scan_tenant_document_projections.apply_async(
            kwargs={"tenant_id": tenant_id},
            headers={"tenant_id": tenant_id},
            queue=KNOWLEDGE_QUEUE,
        )
    return len(set(tenant_ids))


@bisheng_celery.task(
    name=(
        "bisheng.worker.knowledge.document_projection."
        "fanout_document_projection_scan"
    )
)
def fanout_document_projection_scan() -> int:
    return run_async_task(_fanout_projection_scan_async)


def enqueue_document_projection_entries(
    *,
    tenant_id: int,
    entry_ids: list[int] | None,
) -> None:
    if entry_ids is None:
        scan_tenant_document_projections.apply_async(
            kwargs={"tenant_id": int(tenant_id)},
            headers={"tenant_id": int(tenant_id)},
            queue=KNOWLEDGE_QUEUE,
        )
        return
    for entry_id in sorted({int(item) for item in entry_ids}):
        process_document_projection.apply_async(
            kwargs={
                "tenant_id": int(tenant_id),
                "entry_id": entry_id,
            },
            headers={"tenant_id": int(tenant_id)},
            queue=KNOWLEDGE_QUEUE,
        )
