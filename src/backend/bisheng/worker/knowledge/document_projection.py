"""Tenant-aware Celery reconciliation for F059 document projections."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from sqlalchemy import delete, or_
from sqlmodel import col, select

from bisheng.approval.domain.models.approval_instance import (
    ApprovalOutboxStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import (
    ApprovalInstanceRepository,
)
from bisheng.core.config.celery_queues import KNOWLEDGE_PARSE_QUEUE
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeState
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
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    KnowledgeFulltextFileRef,
    request_file_delete_intents,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.knowledge._projection_scan_state import ProjectionScanState, run_reserved
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)
DEFAULT_QUEUE = "celery"

# 测试可注入 writer; 生产始终要求已初始化的共享目标。
shared_storage_writer_factory = None


def _default_shared_storage_writer_factory(tenant_id: int):
    from bisheng.knowledge.rag.shared_space_storage import (
        build_shared_space_components_for_tenant,
    )

    components = build_shared_space_components_for_tenant(int(tenant_id))
    return components[0] if components is not None else None


async def _build_document_projection_service(
    session,
    *,
    file_repository,
    document_repository,
    version_repository,
    deleting_entry_finalizer=None,
    tenant_id: int | None = None,
):
    from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError, SharedStorageErrorCode
    from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
        KnowledgeDocumentProjectionService,
    )
    from bisheng.knowledge.rag.shared_space_storage import get_shared_storage_conf

    if tenant_id is None:
        raise SharedStorageContractError(
            SharedStorageErrorCode.ROUTING_NOT_CONFIGURED, "projection requires a tenant shared target",
        )
    factory = shared_storage_writer_factory or _default_shared_storage_writer_factory
    writer = factory(tenant_id=int(tenant_id))
    if writer is None:
        raise SharedStorageContractError(
            SharedStorageErrorCode.ROUTING_NOT_CONFIGURED, "shared projection writer is unavailable", tenant_id=int(tenant_id),
        )
    kwargs = {
        "shared_storage_writer": writer,
        "shared_embedding_model_id": writer.schema_spec.embedding_model_id,
        "max_retry_attempts": int(get_shared_storage_conf().projection_max_retries),
    }
    from bisheng.knowledge.domain.services.shared_space_content_loader import load_shared_content_from_original
    kwargs["shared_content_chunk_loader"] = load_shared_content_from_original
    if deleting_entry_finalizer is not None:
        kwargs["deleting_entry_finalizer"] = deleting_entry_finalizer
    return KnowledgeDocumentProjectionService(
        session=session,
        file_repository=file_repository,
        document_repository=document_repository,
        version_repository=version_repository,
        **kwargs,
    )


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


async def _delete_resource_permissions(object_type: str, object_id: int) -> None:
    from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
    from bisheng.permission.domain.services.permission_service import PermissionService

    fga = await PermissionService._aget_fga()
    if fga is None:
        raise RuntimeError("OpenFGA unavailable during knowledge space retirement")
    tuples = await fga.read_tuples(object=f"{object_type}:{object_id}")
    operations = [
        TupleOperation(
            action="delete",
            user=str(item["user"]),
            relation=str(item["relation"]),
            object=f"{object_type}:{object_id}",
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
        item.entry_status
        not in {
            KnowledgeFileEntryStatus.DELETING.value,
            KnowledgeFileEntryStatus.INVALID.value,
        }
        or item.projection_status != KnowledgeFileProjectionStatus.READY.value
        or item.applied_content_generation != item.desired_content_generation
        or item.applied_entry_generation != item.desired_entry_generation
        for item in entries
    ):
        from bisheng.knowledge.domain.services.knowledge_document_projection_service import ProjectionDependencyPending

        raise ProjectionDependencyPending(
            "F059 final delete requires all entries to finish cleanup"
        )


def _require_cleanup_claim(current: KnowledgeFile, expected: KnowledgeFile) -> None:
    if (
        current.entry_status != KnowledgeFileEntryStatus.DELETING.value
        or current.projection_status != KnowledgeFileProjectionStatus.READY.value
        or current.projection_lease_owner != expected.projection_lease_owner
        or not expected.projection_lease_owner
        or current.tenant_id != expected.tenant_id
        or current.reference_document_id != expected.reference_document_id
        or current.entry_type != expected.entry_type
        or current.desired_content_generation != expected.desired_content_generation
        or current.desired_entry_generation != expected.desired_entry_generation
        or current.applied_content_generation != current.desired_content_generation
        or current.applied_entry_generation != current.desired_entry_generation
    ):
        raise RuntimeError("F059 logical entry cleanup state changed")


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
        current = next((item for item in entries if item.id == entry.id), None)
        if current is None:
            return
        _require_cleanup_claim(current, entry)
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
        current = next((item for item in current_entries if item.id == entry.id), None)
        if current is None:
            return
        _require_cleanup_claim(current, entry)
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
        invalid_entries = [
            item
            for item in current_entries
            if item.entry_status == KnowledgeFileEntryStatus.INVALID.value
        ]
        delete_file_ids = sorted(
            {
                *physical_file_ids,
                *(
                    int(item.id)
                    for item in current_entries
                    if item.entry_status
                    != KnowledgeFileEntryStatus.INVALID.value
                ),
            }
        )
        knowledge_by_file_id = {
            int(item.id): int(item.knowledge_id)
            for item in [*physical_files, *current_entries]
        }
        await file_repository.prepare_delete_by_ids(delete_file_ids)
        await request_file_delete_intents(
            session,
            [
                KnowledgeFulltextFileRef(
                    file_id=file_id,
                    knowledge_id=knowledge_by_file_id.get(file_id),
                    tenant_id=tenant_id,
                )
                for file_id in delete_file_ids
            ],
            trigger_type="document_entry_finalized",
        )
        if invalid_entries:
            document.primary_version_id = None
            document.predecessor_logic_file_id = None
            document.lifecycle_status = KnowledgeDocumentLifecycleStatus.INVALID.value
            session.add(document)
        else:
            await session.execute(
                delete(KnowledgeDocument).where(
                    KnowledgeDocument.id == document_id
                )
            )
        await session.commit()


async def _finalize_deleting_entry(entry: KnowledgeFile) -> None:
    if entry.entry_status == KnowledgeFileEntryStatus.INVALID.value:
        await _delete_entry_permissions(int(entry.id))
        return
    if entry.entry_type == KnowledgeFileEntryType.MANAGER.value:
        await _finalize_document_delete(entry)
        return
    async with get_async_db_session() as session:
        repository = KnowledgeFileRepositoryImpl(session)
        current = await repository.find_by_id_for_update(int(entry.id))
        if current is None:
            return
        _require_cleanup_claim(current, entry)
        # 行锁保护最终清理, 权限写入失败会回滚并由原租约记录重试。
        await _delete_entry_permissions(int(entry.id))
        await repository.prepare_delete_by_ids([int(entry.id)])
        await request_file_delete_intents(
            session,
            [
                KnowledgeFulltextFileRef(
                    file_id=int(current.id),
                    knowledge_id=int(current.knowledge_id),
                    tenant_id=int(current.tenant_id or 1),
                )
            ],
            trigger_type="document_entry_finalized",
        )
        document_id = int(current.reference_document_id or 0)
        remaining = await repository.find_distribution_entries_by_document_id(
            document_id,
            for_update=True,
        )
        if len(remaining) == 1:
            document_repository = KnowledgeDocumentRepositoryImpl(session)
            document = await document_repository.find_by_id_for_update(document_id)
            if (
                document is not None
                and document.lifecycle_status
                == KnowledgeDocumentLifecycleStatus.INVALID.value
            ):
                await session.execute(
                    delete(KnowledgeDocument).where(
                        KnowledgeDocument.id == document_id
                    )
                )
        await session.commit()


async def _process_projection_async(
    *,
    tenant_id: int,
    entry_id: int,
    lease_owner: str,
) -> str:
    async with get_async_db_session() as session:
        repository = KnowledgeFileRepositoryImpl(session)
        service = await _build_document_projection_service(
            session,
            file_repository=repository,
            document_repository=KnowledgeDocumentRepositoryImpl(session),
            version_repository=KnowledgeDocumentVersionRepositoryImpl(
                session
            ),
            deleting_entry_finalizer=_finalize_deleting_entry,
            tenant_id=int(tenant_id),
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
    name=(
        "bisheng.worker.knowledge.document_projection."
        "process_document_projection"
    ),
)
def process_document_projection(
    task,
    tenant_id: int,
    entry_id: int | None = None,
    *,
    entry_ids: list[int] | None = None,
    scan_tickets: list[dict] | None = None,
) -> dict:
    if entry_id is not None and entry_ids is not None:
        raise ValueError("use entry_ids or entry_id, not both")
    ids = entry_ids if entry_ids is not None else ([entry_id] if entry_id is not None else [])
    if not isinstance(ids, list) or any(type(value) is not int or value <= 0 for value in ids):
        raise ValueError("projection entry_ids must be positive integers")
    if int(get_current_tenant_id() or DEFAULT_TENANT_ID) != int(tenant_id):
        raise ValueError("projection tenant header mismatch")
    # 每次交付使用唯一所有者, 旧执行者不能在消息重投后写回结果。
    lease_owner = f"batch:{uuid.uuid4().hex}"
    if scan_tickets is not None:
        if any(ticket["kind"] != "projection" or ticket["object_id"] not in ids for ticket in scan_tickets):
            raise ValueError("projection scan ticket target mismatch")

        async def reserved_batch() -> dict:
            state = await ProjectionScanState.create(tenant_id)
            return await run_reserved(state, scan_tickets, lambda active, progress: _process_projection_batch_async(
                int(tenant_id), [int(ticket["object_id"]) for ticket in active], lease_owner,
            ))

        return run_async_task(reserved_batch)
    return run_async_task(
        lambda: _process_projection_batch_async(int(tenant_id), list(dict.fromkeys(ids)), lease_owner)
    )


@bisheng_celery.task(
    bind=True, acks_late=True, queue=KNOWLEDGE_PARSE_QUEUE,
    name="bisheng.worker.knowledge.document_projection.rebuild_document_content",
)
def rebuild_document_content(
    task, tenant_id: int, entry_ids: list[int], rebuild_owner: str, content_manifests: list[dict] | None = None,
) -> dict:
    """内容重建由文件解析 Worker 执行, 接管交接租约后再次核验实际内容。"""
    if not isinstance(entry_ids, list) or any(type(value) is not int or value <= 0 for value in entry_ids):
        raise ValueError("projection entry_ids must be positive integers")
    if int(get_current_tenant_id() or DEFAULT_TENANT_ID) != int(tenant_id):
        raise ValueError("projection tenant header mismatch")
    if not isinstance(rebuild_owner, str) or not rebuild_owner.startswith("rebuild:"):
        raise ValueError("invalid content rebuild reservation")
    return run_async_task(lambda: _process_projection_batch_async(
        int(tenant_id), list(dict.fromkeys(entry_ids)), f"content:{uuid.uuid4().hex}",
        allow_content_rebuild=True, handoff_owner=rebuild_owner,
        content_manifests=content_manifests,
    ))


async def _dispatch_content_rebuild(
    tenant_id: int, entry_ids: list[int], reservation: str, *, content_manifests: list[dict] | None = None,
) -> None:
    payload = {"tenant_id": tenant_id, "entry_ids": entry_ids, "rebuild_owner": reservation}
    if content_manifests:
        payload["content_manifests"] = content_manifests
    await asyncio.to_thread(
        rebuild_document_content.apply_async,
        kwargs=payload,
        headers={"tenant_id": tenant_id}, queue=KNOWLEDGE_PARSE_QUEUE, task_id=reservation, retry=False,
    )


async def _process_projection_batch_async(
    tenant_id: int, entry_ids: list[int], owner: str, *,
    allow_content_rebuild: bool = False, handoff_owner: str | None = None,
    content_manifests: list[dict] | None = None,
) -> dict:
    from bisheng.knowledge.domain.repositories.implementations.document_projection_batch_repository import (
        DocumentProjectionBatchRepository,
    )
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService
    from bisheng.knowledge.rag.shared_space_storage import get_shared_storage_conf

    if not entry_ids:
        return {"total": 0, "results": {}}

    @asynccontextmanager
    async def repository_factory():
        async with get_async_db_session() as session:
            yield DocumentProjectionBatchRepository(session)

    conf = get_shared_storage_conf()
    writer = (shared_storage_writer_factory or _default_shared_storage_writer_factory)(tenant_id=tenant_id)
    if writer is None:
        raise RuntimeError("shared projection writer is unavailable")
    loaders = {}
    if allow_content_rebuild:
        from bisheng.knowledge.domain.services.shared_space_content_loader import (
            embed_shared_content_chunks,
            load_shared_content_from_original,
        )
        async def reserve_rebuild(file):
            from bisheng.knowledge.domain.repositories.implementations.shared_storage_reconcile_repository_impl import SharedStorageReconcileRepositoryImpl
            async with get_async_db_session() as session:
                accepted = await SharedStorageReconcileRepositoryImpl(session).claim_content_rebuild(int(file.id))
                await session.commit()
            if not accepted:
                raise RuntimeError("document_content_rebuild_budget_exhausted")

        async def load_with_budget(file):
            await reserve_rebuild(file)
            return await load_shared_content_from_original(file)

        async def embed_with_budget(file, chunks):
            await reserve_rebuild(file)
            return await embed_shared_content_chunks(file, chunks)

        loaders = {"chunk_loader": load_with_budget, "chunk_embedder": embed_with_budget}
    service = DocumentProjectionBatchService(
        repository_factory=repository_factory, writer=writer,
        finalizer=_finalize_deleting_entry, rebuild_dispatch=_dispatch_content_rebuild,
        allow_content_rebuild=allow_content_rebuild, handoff_owner=handoff_owner,
        content_manifests=content_manifests,
        batch_size=int(conf.projection_batch_size), max_attempts=int(conf.projection_max_retries),
        **loaders,
    )
    results = await service.run(tenant_id, entry_ids, owner)
    logger.info("projection batch completed tenant_id=%s total=%s failed=%s", tenant_id, len(results),
                sum(status in {"failed", "exhausted"} for status in results.values()))
    return {
        "total": len(results), "results": results,
        "status": (
            "completed_with_failures" if any(status in {"failed", "exhausted"} for status in results.values())
            else "completed_with_pending" if "rebuild_queued" in results.values() else "completed"
        ),
    }


async def _reconcile_permission_candidates(
    *,
    tenant_id: int,
    candidates: list[KnowledgeFile],
    state: ProjectionScanState,
    max_attempts: int,
    guard: Callable[[], Awaitable[None]],
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
            dispatched += await _dispatch_scan_recovery(
                state, guard, "approval", int(outbox.id), str(outbox.id),
                {"outbox_id": int(outbox.id)}, max_attempts=max_attempts,
            )
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
    state: ProjectionScanState,
    max_attempts: int,
    guard: Callable[[], Awaitable[None]],
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
        dispatched += await _dispatch_scan_recovery(
            state, guard, "rollback", int(entry.id),
            f"{entry.id}:{entry.desired_content_generation}:{entry.desired_entry_generation}",
            {
                "entry_id": int(entry.id),
                "document_id": document_id,
                "manager_file_id": int(entry.projection_previous_file_id),
            },
            max_attempts=max_attempts,
        )
    return dispatched


async def _publish_scan_task(task, *, state: ProjectionScanState,
                             guard: Callable[[], Awaitable[None]], kwargs: dict) -> None:
    await guard()
    # 超时可能意味着已经发出消息, 保留预占直到过期, 不能立即解锁造成重复。
    await asyncio.wait_for(asyncio.to_thread(
        task.apply_async, kwargs=kwargs, headers={"tenant_id": state.tenant_id}, queue=DEFAULT_QUEUE, retry=False,
    ), timeout=5)


async def _dispatch_scan_recovery(
    state: ProjectionScanState, guard: Callable[[], Awaitable[None]], kind: str,
    object_id: int, fingerprint: str, payload: dict, *, max_attempts: int,
) -> int:
    await guard()
    ticket = await state.reserve(kind, object_id, fingerprint, max_attempts=max_attempts)
    if ticket is None:
        return 0
    await _publish_scan_task(recover_document_projection_scan_item, state=state, guard=guard, kwargs={
        "tenant_id": state.tenant_id, "ticket": ticket, "payload": payload,
    })
    return 1


@bisheng_celery.task(acks_late=True, name="bisheng.worker.knowledge.document_projection.recover_scan_item")
def recover_document_projection_scan_item(tenant_id: int, ticket: dict, payload: dict) -> dict:
    if int(get_current_tenant_id() or DEFAULT_TENANT_ID) != int(tenant_id):
        raise ValueError("projection recovery tenant header mismatch")

    async def run() -> dict:
        state = await ProjectionScanState.create(tenant_id)

        async def work(active: list[dict], progress: dict) -> dict:
            kind, object_id = ticket["kind"], int(ticket["object_id"])
            if kind == "approval" and int(payload["outbox_id"]) == object_id:
                from bisheng.worker.approval.tasks import _execute_approval_outbox_async, _retry_approval_outbox_async

                outbox = await ApprovalInstanceRepository.get_outbox(object_id)
                if outbox is None:
                    return {"status": "completed"}
                async with get_async_db_session() as session:
                    still_pending = await KnowledgeFileRepositoryImpl(session).has_preparing_approval_entries(outbox.instance_id)
                if not still_pending:
                    return {"status": "completed"}
                action = (_execute_approval_outbox_async if outbox.status == ApprovalOutboxStatus.PENDING
                          else _retry_approval_outbox_async)
                if not await action(object_id):
                    raise RuntimeError(f"approval recovery failed: {object_id}")
                result = "completed"
            elif kind == "rollback" and int(payload["entry_id"]) == object_id:
                async with get_async_db_session() as session:
                    entry = await KnowledgeFileRepositoryImpl(session).find_by_id(object_id)
                if (entry is None or entry.entry_status != KnowledgeFileEntryStatus.PREPARING.value
                        or entry.entry_type != KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value
                        or entry.reference_document_id != payload["document_id"]
                        or entry.projection_previous_file_id != payload["manager_file_id"]):
                    return {"status": "completed"}
                result = await _resume_rollback_async(
                    tenant_id=tenant_id, document_id=int(payload["document_id"]),
                    manager_file_id=int(payload["manager_file_id"]),
                )
            elif kind == "retirement" and int(payload["space_id"]) == object_id:
                result = await _process_knowledge_space_retirement_async(
                    tenant_id=tenant_id, space_id=object_id, scan_progress=progress,
                )
            else:
                raise ValueError("projection recovery ticket target mismatch")
            return {"status": result}

        return await run_reserved(state, [ticket], work)

    return run_async_task(run)


@bisheng_celery.task(
    name="bisheng.worker.knowledge.document_projection.scan_document_projections",
)
def scan_document_projections(tenant_id: int | None = None) -> dict:
    current = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    if tenant_id is not None and (type(tenant_id) is not int or tenant_id <= 0):
        raise ValueError("projection scan tenant_id must be a positive integer")
    if current != (tenant_id if tenant_id is not None else DEFAULT_TENANT_ID):
        raise ValueError("projection scan tenant header mismatch")
    from bisheng.worker.knowledge._projection_scan import scan_documents

    return run_async_task(lambda: scan_documents(tenant_id))


def enqueue_document_projection_entries(
    *,
    tenant_id: int,
    entry_ids: list[int] | None,
) -> None:
    if entry_ids is None:
        scan_document_projections.apply_async(
            kwargs={"tenant_id": int(tenant_id)},
            headers={"tenant_id": int(tenant_id)},
            queue=DEFAULT_QUEUE,
        )
        return
    normalized_ids = sorted({int(item) for item in entry_ids})
    if normalized_ids:
        process_document_projection.apply_async(
            kwargs={
                "tenant_id": int(tenant_id),
                "entry_ids": normalized_ids,
            },
            headers={"tenant_id": int(tenant_id)},
            queue=DEFAULT_QUEUE,
        )


_CONTAINER_CLEANUP_BATCH_SIZE = 50
_CONTAINER_CLEANUP_MAX_BATCHES = 10


async def _build_distribution_cleanup_service(session):
    from bisheng.knowledge.domain.services.knowledge_distribution_cleanup_service import (
        KnowledgeDistributionCleanupService,
    )
    from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
        KnowledgeDocumentDistributionService,
    )
    from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
        KnowledgeDocumentPermissionActivationService,
    )

    file_repository = KnowledgeFileRepositoryImpl(session)
    return KnowledgeDistributionCleanupService(
        distribution_service=KnowledgeDocumentDistributionService(
            session=session,
            document_repository=KnowledgeDocumentRepositoryImpl(session),
            version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
            file_repository=file_repository,
            permission_activation_service=KnowledgeDocumentPermissionActivationService(
                file_repository=file_repository,
            ),
        )
    )


async def _load_container_distribution_entries(
    session,
    *,
    tenant_id: int,
    space_id: int,
    folder_prefix: str | None,
    limit: int,
) -> list[KnowledgeFile]:
    """Entries inside the container that still need a cleanup decision.

    ``deleting`` is deliberately excluded: those already belong to the
    projection worker, and re-processing them would undo nothing but waste a
    round trip.
    """
    statement = (
        select(KnowledgeFile)
        .where(
            KnowledgeFile.tenant_id == tenant_id,
            KnowledgeFile.knowledge_id == space_id,
            col(KnowledgeFile.reference_document_id).is_not(None),
            col(KnowledgeFile.entry_status).in_(
                [
                    KnowledgeFileEntryStatus.PREPARING.value,
                    KnowledgeFileEntryStatus.ACTIVE.value,
                    KnowledgeFileEntryStatus.INVALID.value,
                ]
            ),
        )
        .order_by(KnowledgeFile.id.asc())
        .limit(limit)
    )
    if folder_prefix:
        statement = statement.where(
            or_(
                col(KnowledgeFile.file_level_path) == folder_prefix,
                col(KnowledgeFile.file_level_path).like(f"{folder_prefix}/%"),
            )
        )
    return list((await session.exec(statement)).all())


async def _sweep_container_distribution_entries(
    *,
    tenant_id: int,
    space_id: int,
    folder_prefix: str | None = None,
) -> tuple[str, int]:
    """Clean one container's distribution entries; returns (status, processed).

    Status is ``completed`` when nothing is left, ``pending`` when more remain
    after this invocation's batch budget, and ``stalled`` when a whole batch
    failed to move — the latter must not be re-queued in a loop, since the
    periodic reconcile scan will come back to it.
    """
    processed = 0
    for _ in range(_CONTAINER_CLEANUP_MAX_BATCHES):
        async with get_async_db_session() as session:
            entries = await _load_container_distribution_entries(
                session,
                tenant_id=tenant_id,
                space_id=space_id,
                folder_prefix=folder_prefix,
                limit=_CONTAINER_CLEANUP_BATCH_SIZE,
            )
            if not entries:
                return "completed", processed
            service = await _build_distribution_cleanup_service(session)
            outcomes = await service.cleanup_entries(entries)

        processed += len(outcomes)
        moved = [item for item in outcomes if item.action.value not in {"failed", "skipped"}]
        degraded = [item for item in outcomes if item.degraded]
        failed = [item for item in outcomes if item.action.value == "failed"]
        logger.info(
            "F098 container cleanup tenant_id=%s space_id=%s folder_prefix=%s "
            "batch=%s moved=%s degraded=%s failed=%s",
            tenant_id,
            space_id,
            folder_prefix,
            len(outcomes),
            len(moved),
            len(degraded),
            len(failed),
        )
        if not moved:
            logger.error(
                "F098 container cleanup made no progress tenant_id=%s space_id=%s "
                "folder_prefix=%s stuck_entry_ids=%s",
                tenant_id,
                space_id,
                folder_prefix,
                [item.entry_id for item in failed],
            )
            return "stalled", processed
        enqueue_document_projection_entries(
            tenant_id=tenant_id,
            entry_ids=[item.entry_id for item in moved],
        )
    return "pending", processed


async def _process_container_distribution_cleanup_async(
    *,
    tenant_id: int,
    space_id: int,
    folder_prefix: str | None,
) -> str:
    if folder_prefix:
        from bisheng.knowledge.domain.services.knowledge_background_service import KnowledgeBackgroundService
        service = KnowledgeBackgroundService()
        folder_id = int(folder_prefix.rstrip("/").split("/")[-1])
        folders = await service.repository_call("files", [folder_id])
        if not folders or folders[0].deleted_at is None:
            return "skipped"
        job_id = await service.repository_call("request_container", folders[0], folders[0].deleted_at)
        return await service.process(job_id, tenant_id)
    status, processed = await _sweep_container_distribution_entries(
        tenant_id=tenant_id,
        space_id=space_id,
        folder_prefix=folder_prefix,
    )
    if status == "pending":
        enqueue_container_distribution_cleanup(
            tenant_id=tenant_id,
            space_id=space_id,
            folder_prefix=folder_prefix,
        )
    logger.info(
        "F098 container cleanup pass finished tenant_id=%s space_id=%s "
        "folder_prefix=%s status=%s processed=%s",
        tenant_id,
        space_id,
        folder_prefix,
        status,
        processed,
    )
    return status


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    name=(
        "bisheng.worker.knowledge.document_projection."
        "process_container_distribution_cleanup"
    ),
)
def process_container_distribution_cleanup(
    task,
    tenant_id: int,
    space_id: int,
    folder_prefix: str | None = None,
) -> str:
    return run_async_task(
        lambda: _process_container_distribution_cleanup_async(
            tenant_id=int(tenant_id),
            space_id=int(space_id),
            folder_prefix=folder_prefix,
        )
    )


def enqueue_container_distribution_cleanup(
    *,
    tenant_id: int,
    space_id: int,
    folder_prefix: str | None = None,
) -> None:
    process_container_distribution_cleanup.apply_async(
        kwargs={
            "tenant_id": int(tenant_id),
            "space_id": int(space_id),
            "folder_prefix": folder_prefix,
        },
        headers={"tenant_id": int(tenant_id)},
        queue=DEFAULT_QUEUE,
    )


async def _process_knowledge_space_retirement_async(
    *,
    tenant_id: int,
    space_id: int,
    scan_progress: dict | None = None,
) -> str:
    from bisheng.common.models.space_channel_member import SpaceChannelMemberDao
    from bisheng.knowledge.domain.models.knowledge_file import FileType
    from bisheng.knowledge.domain.models.knowledge_space_tag_library import (
        KnowledgeSpaceTagLibraryDao,
    )
    from bisheng.knowledge.domain.services.knowledge_space_pin_service import (
        KnowledgeSpacePinService,
    )
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
        KnowledgeSpaceContentStat,
    )

    async with get_async_db_session() as session:
        space = (
            await session.exec(
                select(Knowledge).where(
                    Knowledge.id == space_id,
                    Knowledge.tenant_id == tenant_id,
                    Knowledge.state == KnowledgeState.DELETING.value,
                )
            )
        ).first()
        if space is None:
            return "completed"

    # Sweep before checking: the reconcile scan re-queues retiring spaces, so
    # doing the work here is what actually moves a space toward disappearing.
    await _sweep_container_distribution_entries(
        tenant_id=tenant_id,
        space_id=space_id,
    )

    async with get_async_db_session() as session:
        local_files = list(
            (
                await session.exec(
                    select(KnowledgeFile).where(
                        KnowledgeFile.knowledge_id == space_id,
                        col(KnowledgeFile.deleted_at).is_(None),
                    )
                )
            ).all()
        )
    if scan_progress is not None:
        # 只比较清理进度, 不把失败次数或刷新时间当成业务进展。
        snapshot = sorted((int(item.id), item.entry_status, item.applied_content_generation,
                           item.applied_entry_generation) for item in local_files)
        scan_progress["fingerprint"] = hashlib.sha256(repr(snapshot).encode()).hexdigest()
    if any(
        item.reference_document_id is not None
        and item.entry_status
        in {
            KnowledgeFileEntryStatus.PREPARING.value,
            KnowledgeFileEntryStatus.ACTIVE.value,
            KnowledgeFileEntryStatus.DELETING.value,
            KnowledgeFileEntryStatus.INVALID.value,
        }
        for item in local_files
    ):
        return "waiting"

    from bisheng.channel.domain.models.channel_knowledge_sync import (
        ChannelKnowledgeSyncDao,
    )
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

    await asyncio.to_thread(KnowledgeService.delete_knowledge_file_in_vector, space)
    await asyncio.to_thread(
        KnowledgeService.delete_knowledge_file_in_minio,
        space_id,
        tenant_id,
    )
    for item in local_files:
        await _delete_resource_permissions(
            "folder" if item.file_type == FileType.DIR.value else "knowledge_file",
            int(item.id),
        )
    await _delete_resource_permissions("knowledge_space", space_id)
    await KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge(space_id)
    await KnowledgeSpacePinService.delete_space_pins(space_id)
    await KnowledgeSpaceContentStat.enqueue_space_delete_stat_async(space_id)
    await SpaceChannelMemberDao.clean_space_member(space_id)
    await ChannelKnowledgeSyncDao.adelete_by_space_id(str(space_id))
    await KnowledgeDao.async_delete_knowledge(knowledge_id=space_id)
    return "completed"


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    name="bisheng.worker.knowledge.document_projection.process_knowledge_space_retirement",
)
def process_knowledge_space_retirement(
    task,
    tenant_id: int,
    space_id: int,
) -> str:
    return run_async_task(
        lambda: _process_knowledge_space_retirement_async(
            tenant_id=int(tenant_id),
            space_id=int(space_id),
        )
    )


def enqueue_knowledge_space_retirement(*, tenant_id: int, space_id: int) -> None:
    process_knowledge_space_retirement.apply_async(
        kwargs={"tenant_id": int(tenant_id), "space_id": int(space_id)},
        headers={"tenant_id": int(tenant_id)},
        queue=DEFAULT_QUEUE,
    )
