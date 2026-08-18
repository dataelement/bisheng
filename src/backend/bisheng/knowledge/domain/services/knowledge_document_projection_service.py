"""Lease/CAS reconciliation for F059 ES and Milvus entry projections."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    KnowledgeFulltextFileRef,
    commit_tracked_fulltext_changes,
    request_file_sync_intents,
    track_fulltext_file_changes,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectionSource:
    space_id: int
    file_id: int


@dataclass(frozen=True)
class ProjectionTarget:
    tenant_id: int
    entry_id: int
    document_id: int
    version_id: int
    entry_type: str
    content_generation: int
    entry_generation: int


@dataclass(frozen=True)
class ProjectionProcessResult:
    entry_id: int
    status: str
    content_generation: int
    entry_generation: int


ProjectionWriter = Callable[
    [ProjectionSource, KnowledgeFile, ProjectionTarget],
    Awaitable[None],
]
ProjectionCleaner = Callable[[int, list[int]], Awaitable[None]]
DeletingEntryFinalizer = Callable[[KnowledgeFile], Awaitable[None]]


class KnowledgeDocumentProjectionError(RuntimeError):
    """Raised when one entry projection cannot safely converge."""


async def _default_projection_writer(
    source: ProjectionSource,
    entry: KnowledgeFile,
    target: ProjectionTarget,
) -> None:
    def _write() -> None:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
        from bisheng.worker.knowledge.file_worker import copy_vector
        from bisheng.worker.knowledge.rebuild_knowledge_worker import (
            _rebuild_knowledge_file_chunk,
        )

        metadata_overrides = {
            "canonical_document_id": int(target.document_id),
            "canonical_version_id": int(target.version_id),
            "entry_type": target.entry_type,
            "content_generation": int(target.content_generation),
            "entry_generation": int(target.entry_generation),
            "document_name": entry.file_name,
            "abstract": entry.abstract,
            "updater": entry.updater_name,
            "update_time": (
                int(entry.update_time.timestamp())
                if entry.update_time is not None
                else 0
            ),
        }
        if (
            source.space_id == int(entry.knowledge_id)
            and source.file_id == int(entry.id)
        ):
            _rebuild_knowledge_file_chunk(
                entry,
                metadata_overrides=metadata_overrides,
            )
            return
        source_space = KnowledgeDao.query_by_id(source.space_id)
        target_space = KnowledgeDao.query_by_id(int(entry.knowledge_id))
        if source_space is None or target_space is None:
            raise KnowledgeDocumentProjectionError(
                "projection source or target space does not exist"
            )
        copy_vector(
            source_space,
            target_space,
            source.file_id,
            int(entry.id),
            metadata_overrides=metadata_overrides,
        )

    await asyncio.to_thread(_write)


async def _default_projection_cleaner(
    space_id: int,
    file_ids: list[int],
) -> None:
    def _clean() -> None:
        from bisheng.api.services.knowledge_imp import delete_vector_files
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        knowledge = KnowledgeDao.query_by_id(space_id)
        if knowledge is None:
            return
        delete_vector_files(sorted(set(file_ids)), knowledge)

    await asyncio.to_thread(_clean)


async def _noop_deleting_entry_finalizer(entry: KnowledgeFile) -> None:
    return None


class KnowledgeDocumentProjectionService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        file_repository: KnowledgeFileRepository,
        document_repository: KnowledgeDocumentRepository | None = None,
        version_repository: KnowledgeDocumentVersionRepository | None = None,
        projection_writer: ProjectionWriter = _default_projection_writer,
        projection_cleaner: ProjectionCleaner = _default_projection_cleaner,
        deleting_entry_finalizer: DeletingEntryFinalizer = (
            _noop_deleting_entry_finalizer
        ),
        lease_seconds: int = 120,
        max_retry_seconds: int = 300,
    ):
        self.session = session
        self.file_repository = file_repository
        self.document_repository = document_repository
        self.version_repository = version_repository
        self.projection_writer = projection_writer
        self.projection_cleaner = projection_cleaner
        self.deleting_entry_finalizer = deleting_entry_finalizer
        self.lease_seconds = max(int(lease_seconds), 1)
        self.max_retry_seconds = max(int(max_retry_seconds), 1)
        track_fulltext_file_changes(self.session)

    async def _commit(self) -> None:
        await commit_tracked_fulltext_changes(
            self.session,
            trigger_type="document_projection_updated",
        )

    async def _resolve_source(
        self,
        entry: KnowledgeFile,
    ) -> ProjectionSource:
        entries = (
            await self.file_repository.find_distribution_entries_by_document_id(
                int(entry.reference_document_id),
            )
        )
        if entry.entry_type == KnowledgeFileEntryType.MANAGER.value:
            previous = (
                await self.file_repository.find_by_id(
                    int(entry.projection_previous_file_id)
                )
                if entry.projection_previous_file_id is not None
                else None
            )
            if (
                previous is not None
                and previous.entry_type
                == KnowledgeFileEntryType.PUBLISH.value
                and previous.entry_status
                in {
                    KnowledgeFileEntryStatus.ACTIVE.value,
                    KnowledgeFileEntryStatus.DELETING.value,
                }
            ):
                if (
                    previous.applied_content_generation
                    >= entry.desired_content_generation
                ):
                    return ProjectionSource(
                        space_id=int(previous.knowledge_id),
                        file_id=int(previous.id),
                    )
                rollback_tombstone = next(
                    (
                        candidate
                        for candidate in entries
                        if candidate.entry_type
                        == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value
                        and candidate.entry_status
                        in {
                            KnowledgeFileEntryStatus.PREPARING.value,
                            KnowledgeFileEntryStatus.DELETING.value,
                        }
                        and int(
                            candidate.projection_previous_file_id or 0
                        )
                        == int(entry.id)
                    ),
                    None,
                )
                if rollback_tombstone is not None:
                    return ProjectionSource(
                        space_id=int(rollback_tombstone.knowledge_id),
                        file_id=int(entry.id),
                    )
                if previous.projection_previous_file_id is not None:
                    return ProjectionSource(
                        space_id=int(previous.knowledge_id),
                        file_id=int(
                            previous.projection_previous_file_id
                        ),
                    )
                return ProjectionSource(
                    space_id=int(previous.knowledge_id),
                    file_id=int(previous.id),
                )
            return ProjectionSource(
                space_id=int(entry.knowledge_id),
                file_id=int(entry.id),
            )
        if entry.entry_type == KnowledgeFileEntryType.PUBLISH.value:
            if entry.projection_previous_file_id is not None:
                return ProjectionSource(
                    space_id=int(entry.knowledge_id),
                    file_id=int(entry.projection_previous_file_id),
                )

        if entry.projection_previous_file_id is not None:
            previous = await self.file_repository.find_by_id(
                int(entry.projection_previous_file_id)
            )
            if (
                previous is not None
                and previous.entry_type
                == KnowledgeFileEntryType.PUBLISH.value
            ):
                return ProjectionSource(
                    space_id=int(entry.knowledge_id),
                    file_id=int(previous.id),
                )

        ready_entries = [
            candidate
            for candidate in entries
            if int(candidate.id) != int(entry.id)
            and candidate.entry_status
            == KnowledgeFileEntryStatus.ACTIVE.value
            and candidate.projection_status
            == KnowledgeFileProjectionStatus.READY.value
            and candidate.applied_content_generation
            >= entry.desired_content_generation
        ]
        if ready_entries:
            ready_entries.sort(
                key=lambda candidate: (
                    0
                    if candidate.entry_type
                    == KnowledgeFileEntryType.MANAGER.value
                    else 1,
                    int(candidate.id),
                )
            )
            source = ready_entries[0]
            return ProjectionSource(
                space_id=int(source.knowledge_id),
                file_id=int(source.id),
            )

        previous_sources = [
            candidate
            for candidate in entries
            if candidate.projection_previous_file_id is not None
            and candidate.entry_status
            in {
                KnowledgeFileEntryStatus.ACTIVE.value,
                KnowledgeFileEntryStatus.DELETING.value,
            }
        ]
        if previous_sources:
            previous_sources.sort(key=lambda candidate: int(candidate.id))
            source = previous_sources[0]
            return ProjectionSource(
                space_id=int(source.knowledge_id),
                file_id=int(source.projection_previous_file_id),
            )

        if entry.applied_content_generation > 0:
            return ProjectionSource(
                space_id=int(entry.knowledge_id),
                file_id=int(entry.id),
            )
        raise KnowledgeDocumentProjectionError(
            "no ready canonical projection source is available"
        )

    @staticmethod
    def _cleanup_file_ids(entry: KnowledgeFile) -> list[int]:
        ids = [int(entry.id)]
        if entry.projection_previous_file_id is not None:
            ids.append(int(entry.projection_previous_file_id))
        return sorted(set(ids))

    async def _require_destination_manager_ready_for_cleanup(
        self,
        entry: KnowledgeFile,
    ) -> None:
        if (
            entry.entry_status
            != KnowledgeFileEntryStatus.DELETING.value
            or entry.entry_type
            not in {
                KnowledgeFileEntryType.PUBLISH.value,
                KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
            }
        ):
            return
        if self.document_repository is not None:
            document = await self.document_repository.find_by_id(
                int(entry.reference_document_id)
            )
            if (
                document is not None
                and document.lifecycle_status
                != KnowledgeDocumentLifecycleStatus.ACTIVE.value
            ):
                return
        entries = (
            await self.file_repository.find_distribution_entries_by_document_id(
                int(entry.reference_document_id),
            )
        )
        destination_ready = any(
            candidate.entry_type
            == KnowledgeFileEntryType.MANAGER.value
            and candidate.entry_status
            == KnowledgeFileEntryStatus.ACTIVE.value
            and candidate.projection_status
            == KnowledgeFileProjectionStatus.READY.value
            and candidate.applied_content_generation
            >= entry.desired_content_generation
            and candidate.applied_entry_generation
            >= candidate.desired_entry_generation
            for candidate in entries
        )
        if not destination_ready:
            raise KnowledgeDocumentProjectionError(
                "destination manager projection is not ready for cleanup"
            )

    async def process_entry(
        self,
        *,
        tenant_id: int,
        entry_id: int,
        lease_owner: str,
        now: datetime | None = None,
    ) -> ProjectionProcessResult:
        started_at = time.monotonic()
        now = now or datetime.now()
        claimed = await self.file_repository.claim_projection_lease(
            entry_id=entry_id,
            lease_owner=lease_owner,
            lease_until=now + timedelta(seconds=self.lease_seconds),
            now=now,
        )
        if claimed is None:
            await self.session.rollback()
            return ProjectionProcessResult(
                entry_id=entry_id,
                status="not_claimed",
                content_generation=0,
                entry_generation=0,
            )
        if int(claimed.tenant_id or 0) != int(tenant_id):
            await self.session.rollback()
            raise KnowledgeDocumentProjectionError(
                "projection tenant mismatch"
            )
        version_id = 0
        is_cleanup = (
            claimed.entry_status
            in {
                KnowledgeFileEntryStatus.DELETING.value,
                KnowledgeFileEntryStatus.INVALID.value,
            }
            or claimed.entry_type
            == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value
        )
        if (
            not is_cleanup
            and self.document_repository is not None
            and self.version_repository is not None
            and claimed.reference_document_id is not None
        ):
            document = await self.document_repository.find_by_id(
                int(claimed.reference_document_id)
            )
            if (
                document is None
                or int(document.tenant_id or 0) != int(tenant_id)
                or document.primary_version_id is None
            ):
                await self.session.rollback()
                raise KnowledgeDocumentProjectionError(
                    "projection canonical document is unavailable"
                )
            version = await self.version_repository.find_by_id(
                int(document.primary_version_id)
            )
            if (
                version is None
                or int(version.document_id) != int(document.id)
            ):
                await self.session.rollback()
                raise KnowledgeDocumentProjectionError(
                    "projection canonical version is unavailable"
                )
            version_id = int(version.id)

        target = ProjectionTarget(
            tenant_id=tenant_id,
            entry_id=int(claimed.id),
            document_id=int(claimed.reference_document_id or 0),
            version_id=version_id,
            entry_type=str(claimed.entry_type or ""),
            content_generation=int(claimed.desired_content_generation),
            entry_generation=int(claimed.desired_entry_generation),
        )
        retry_count = int(claimed.projection_retry_count or 0)
        await self._commit()

        try:
            if is_cleanup:
                await self._require_destination_manager_ready_for_cleanup(
                    claimed
                )
                await self.projection_cleaner(
                    int(claimed.knowledge_id),
                    self._cleanup_file_ids(claimed),
                )
                if claimed.entry_status == KnowledgeFileEntryStatus.INVALID.value:
                    # 权限清理必须在 CAS 完成前成功，否则保留失败态供扫描重试。
                    await self.deleting_entry_finalizer(claimed)
            else:
                source = await self._resolve_source(claimed)
                await self.projection_writer(source, claimed, target)
                if claimed.projection_previous_file_id is not None:
                    await self.projection_cleaner(
                        int(claimed.knowledge_id),
                        [int(claimed.projection_previous_file_id)],
                    )

            applied = await self.file_repository.apply_projection_result(
                entry_id=entry_id,
                lease_owner=lease_owner,
                target_content_generation=target.content_generation,
                target_entry_generation=target.entry_generation,
            )
            if applied:
                await request_file_sync_intents(
                    self.session,
                    [
                        KnowledgeFulltextFileRef(
                            file_id=entry_id,
                            knowledge_id=int(claimed.knowledge_id),
                            tenant_id=tenant_id,
                        )
                    ],
                    trigger_type="document_projection_applied",
                )
            await self._commit()
            if not applied:
                logger.info(
                    "F059 projection result tenant_id=%s entry_id=%s "
                    "status=stale content_generation=%s "
                    "entry_generation=%s duration_ms=%.2f",
                    tenant_id,
                    entry_id,
                    target.content_generation,
                    target.entry_generation,
                    (time.monotonic() - started_at) * 1000,
                )
                return ProjectionProcessResult(
                    entry_id=entry_id,
                    status="stale",
                    content_generation=target.content_generation,
                    entry_generation=target.entry_generation,
                )
            if (
                is_cleanup
                and claimed.entry_status
                != KnowledgeFileEntryStatus.INVALID.value
            ):
                await self.deleting_entry_finalizer(claimed)
            result_status = "ready" if not is_cleanup else "cleaned"
            logger.info(
                "F059 projection result tenant_id=%s entry_id=%s "
                "status=%s content_generation=%s entry_generation=%s "
                "content_lag_before=%s entry_lag_before=%s "
                "duration_ms=%.2f",
                tenant_id,
                entry_id,
                result_status,
                target.content_generation,
                target.entry_generation,
                max(
                    target.content_generation
                    - int(claimed.applied_content_generation),
                    0,
                ),
                max(
                    target.entry_generation
                    - int(claimed.applied_entry_generation),
                    0,
                ),
                (time.monotonic() - started_at) * 1000,
            )
            return ProjectionProcessResult(
                entry_id=entry_id,
                status=result_status,
                content_generation=target.content_generation,
                entry_generation=target.entry_generation,
            )
        except Exception as exc:
            await self.session.rollback()
            retry_delay = min(
                2 ** min(retry_count + 1, 8),
                self.max_retry_seconds,
            )
            failed = await self.file_repository.fail_projection_lease(
                entry_id=entry_id,
                lease_owner=lease_owner,
                next_retry_at=now + timedelta(seconds=retry_delay),
                error_summary=f"{type(exc).__name__}:projection_failed",
            )
            if not failed:
                logger.info(
                    "F059 projection failure result ignored after lease "
                    "ownership changed: tenant_id=%s entry_id=%s",
                    tenant_id,
                    entry_id,
                )
            await self._commit()
            logger.warning(
                "F059 projection failed tenant_id=%s entry_id=%s "
                "retry_count=%s error_type=%s duration_ms=%.2f",
                tenant_id,
                entry_id,
                retry_count + 1,
                type(exc).__name__,
                (time.monotonic() - started_at) * 1000,
            )
            raise

    async def list_due_entry_ids(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[int]:
        candidates = await self.file_repository.find_projection_candidates(
            now=now or datetime.now(),
            limit=min(max(int(limit), 1), 500),
        )
        return [int(candidate.id) for candidate in candidates]
