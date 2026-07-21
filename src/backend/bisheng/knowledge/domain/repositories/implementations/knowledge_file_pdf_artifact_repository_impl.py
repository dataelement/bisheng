"""统一 PDF Artifact 的 generation 条件状态机。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
    KnowledgeFilePdfArtifactOrigin,
    KnowledgeFilePdfArtifactStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_pdf_artifact_repository import (
    PdfArtifactClaimResult,
    PdfArtifactClaimState,
    PdfArtifactCompleteResult,
    PdfArtifactGenerationRequest,
    PdfArtifactSourceSnapshot,
)

_CLAIMABLE_STATUSES = (
    KnowledgeFilePdfArtifactStatus.WAITING.value,
    KnowledgeFilePdfArtifactStatus.PROCESSING.value,
)
_COMPLETABLE_STATUSES = (
    KnowledgeFilePdfArtifactStatus.WAITING.value,
    KnowledgeFilePdfArtifactStatus.PROCESSING.value,
    KnowledgeFilePdfArtifactStatus.FAILED.value,
)
_VALID_ORIGINS = tuple(origin.value for origin in KnowledgeFilePdfArtifactOrigin)


class KnowledgeFilePdfArtifactRepositoryImpl:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _scope(tenant_id: int, knowledge_file_id: int):
        return (
            KnowledgeFilePdfArtifact.tenant_id == tenant_id,
            KnowledgeFilePdfArtifact.knowledge_file_id == knowledge_file_id,
        )

    async def request_generation(self, snapshot: PdfArtifactSourceSnapshot) -> PdfArtifactGenerationRequest:
        statement = (
            select(KnowledgeFilePdfArtifact)
            .where(*self._scope(snapshot.tenant_id, snapshot.knowledge_file_id))
            .with_for_update()
        )
        result = await self.session.execute(statement)
        artifact = result.scalars().first()
        previous_object_name = artifact.object_name if artifact else None
        previous_origin = artifact.artifact_origin if artifact else None

        if artifact is None:
            artifact = KnowledgeFilePdfArtifact(
                tenant_id=snapshot.tenant_id,
                knowledge_file_id=snapshot.knowledge_file_id,
                source_object_name=snapshot.source_object_name,
                source_md5=snapshot.source_md5,
                generation=1,
                status=KnowledgeFilePdfArtifactStatus.WAITING.value,
            )
            self.session.add(artifact)
        else:
            artifact.generation += 1
            artifact.source_object_name = snapshot.source_object_name
            artifact.source_md5 = snapshot.source_md5
            artifact.status = KnowledgeFilePdfArtifactStatus.WAITING.value
            artifact.artifact_sha256 = None
            artifact.attempt_count = 0
            artifact.last_error = None
            artifact.page_count = None
            artifact.artifact_size = None
            artifact.started_at = None
            artifact.completed_at = None

        await self.session.commit()
        await self.session.refresh(artifact)
        return PdfArtifactGenerationRequest(
            artifact=artifact,
            previous_object_name=previous_object_name,
            previous_origin=previous_origin,
        )

    async def find_current(self, tenant_id: int, knowledge_file_id: int) -> KnowledgeFilePdfArtifact | None:
        result = await self.session.execute(
            select(KnowledgeFilePdfArtifact).where(*self._scope(tenant_id, knowledge_file_id))
        )
        return result.scalars().first()

    async def find_available(self, tenant_id: int, knowledge_file_id: int) -> KnowledgeFilePdfArtifact | None:
        result = await self.session.execute(
            select(KnowledgeFilePdfArtifact).where(
                *self._scope(tenant_id, knowledge_file_id),
                KnowledgeFilePdfArtifact.status == KnowledgeFilePdfArtifactStatus.SUCCESS.value,
                KnowledgeFilePdfArtifact.object_name.is_not(None),
                KnowledgeFilePdfArtifact.artifact_sha256.is_not(None),
                col(KnowledgeFilePdfArtifact.artifact_origin).in_(_VALID_ORIGINS),
            )
        )
        return result.scalars().first()

    async def claim_generation(
        self,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        started_at: datetime,
    ) -> PdfArtifactClaimResult:
        current = await self.find_current(tenant_id, knowledge_file_id)
        if current is None or current.generation != generation:
            return PdfArtifactClaimResult(PdfArtifactClaimState.STALE, current)
        if current.status == KnowledgeFilePdfArtifactStatus.SUCCESS.value:
            return PdfArtifactClaimResult(PdfArtifactClaimState.ALREADY_COMPLETED, current)
        if current.status == KnowledgeFilePdfArtifactStatus.FAILED.value:
            return PdfArtifactClaimResult(PdfArtifactClaimState.FAILED, current)

        result = await self.session.execute(
            update(KnowledgeFilePdfArtifact)
            .where(
                *self._scope(tenant_id, knowledge_file_id),
                KnowledgeFilePdfArtifact.generation == generation,
                col(KnowledgeFilePdfArtifact.status).in_(_CLAIMABLE_STATUSES),
            )
            .values(
                status=KnowledgeFilePdfArtifactStatus.PROCESSING.value,
                attempt_count=KnowledgeFilePdfArtifact.attempt_count + 1,
                started_at=started_at,
            )
        )
        await self.session.commit()
        refreshed = await self.find_current(tenant_id, knowledge_file_id)
        if int(result.rowcount or 0) == 1:
            return PdfArtifactClaimResult(PdfArtifactClaimState.CLAIMED, refreshed)
        if refreshed and refreshed.status == KnowledgeFilePdfArtifactStatus.SUCCESS.value:
            return PdfArtifactClaimResult(PdfArtifactClaimState.ALREADY_COMPLETED, refreshed)
        return PdfArtifactClaimResult(PdfArtifactClaimState.STALE, refreshed)

    async def mark_retry(
        self,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        last_error: str,
    ) -> bool:
        result = await self.session.execute(
            update(KnowledgeFilePdfArtifact)
            .where(
                *self._scope(tenant_id, knowledge_file_id),
                KnowledgeFilePdfArtifact.generation == generation,
                KnowledgeFilePdfArtifact.status != KnowledgeFilePdfArtifactStatus.SUCCESS.value,
            )
            .values(
                status=KnowledgeFilePdfArtifactStatus.WAITING.value,
                last_error=last_error[:2000],
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0) == 1

    async def fail_generation(
        self,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        last_error: str,
    ) -> bool:
        result = await self.session.execute(
            update(KnowledgeFilePdfArtifact)
            .where(
                *self._scope(tenant_id, knowledge_file_id),
                KnowledgeFilePdfArtifact.generation == generation,
                KnowledgeFilePdfArtifact.status != KnowledgeFilePdfArtifactStatus.SUCCESS.value,
            )
            .values(
                status=KnowledgeFilePdfArtifactStatus.FAILED.value,
                last_error=last_error[:2000],
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0) == 1

    async def complete_generation(
        self,
        *,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        origin: KnowledgeFilePdfArtifactOrigin,
        object_name: str,
        artifact_sha256: str,
        page_count: int,
        artifact_size: int,
        completed_at: datetime,
    ) -> PdfArtifactCompleteResult:
        if not object_name or not artifact_sha256 or page_count <= 0 or artifact_size <= 0:
            raise ValueError("A completed PDF artifact requires valid object metadata")

        current = await self.find_current(tenant_id, knowledge_file_id)
        if (
            current is None
            or current.generation != generation
            or current.status == KnowledgeFilePdfArtifactStatus.SUCCESS.value
        ):
            return PdfArtifactCompleteResult(False, current)

        previous_object_name = current.object_name
        previous_origin = current.artifact_origin
        result = await self.session.execute(
            update(KnowledgeFilePdfArtifact)
            .where(
                *self._scope(tenant_id, knowledge_file_id),
                KnowledgeFilePdfArtifact.generation == generation,
                col(KnowledgeFilePdfArtifact.status).in_(_COMPLETABLE_STATUSES),
            )
            .values(
                status=KnowledgeFilePdfArtifactStatus.SUCCESS.value,
                artifact_origin=origin.value,
                object_name=object_name,
                artifact_sha256=artifact_sha256,
                page_count=page_count,
                artifact_size=artifact_size,
                completed_at=completed_at,
                last_error=None,
            )
        )
        await self.session.commit()
        refreshed = await self.find_current(tenant_id, knowledge_file_id)
        completed = int(result.rowcount or 0) == 1
        return PdfArtifactCompleteResult(
            completed=completed,
            artifact=refreshed,
            previous_object_name=previous_object_name if completed else None,
            previous_origin=previous_origin if completed else None,
        )

    async def find_by_file_ids(self, tenant_id: int, knowledge_file_ids: list[int]) -> list[KnowledgeFilePdfArtifact]:
        if not knowledge_file_ids:
            return []
        result = await self.session.execute(
            select(KnowledgeFilePdfArtifact).where(
                KnowledgeFilePdfArtifact.tenant_id == tenant_id,
                col(KnowledgeFilePdfArtifact.knowledge_file_id).in_(knowledge_file_ids),
            )
        )
        return list(result.scalars().all())

    async def delete_by_file_ids(self, tenant_id: int, knowledge_file_ids: list[int]) -> int:
        if not knowledge_file_ids:
            return 0
        result = await self.session.execute(
            delete(KnowledgeFilePdfArtifact).where(
                KnowledgeFilePdfArtifact.tenant_id == tenant_id,
                col(KnowledgeFilePdfArtifact.knowledge_file_id).in_(knowledge_file_ids),
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0)


class KnowledgeFilePdfArtifactSyncRepositoryImpl:
    """同步业务入口使用的同语义 Repository。"""

    def __init__(self, session):
        self.session = session

    @staticmethod
    def _scope(tenant_id: int, knowledge_file_id: int):
        return KnowledgeFilePdfArtifactRepositoryImpl._scope(tenant_id, knowledge_file_id)

    def request_generation(self, snapshot: PdfArtifactSourceSnapshot) -> PdfArtifactGenerationRequest:
        artifact = (
            self.session.execute(
                select(KnowledgeFilePdfArtifact)
                .where(*self._scope(snapshot.tenant_id, snapshot.knowledge_file_id))
                .with_for_update()
            )
            .scalars()
            .first()
        )
        previous_object_name = artifact.object_name if artifact else None
        previous_origin = artifact.artifact_origin if artifact else None
        if artifact is None:
            artifact = KnowledgeFilePdfArtifact(
                tenant_id=snapshot.tenant_id,
                knowledge_file_id=snapshot.knowledge_file_id,
                source_object_name=snapshot.source_object_name,
                source_md5=snapshot.source_md5,
                generation=1,
                status=KnowledgeFilePdfArtifactStatus.WAITING.value,
            )
            self.session.add(artifact)
        else:
            artifact.generation += 1
            artifact.source_object_name = snapshot.source_object_name
            artifact.source_md5 = snapshot.source_md5
            artifact.status = KnowledgeFilePdfArtifactStatus.WAITING.value
            artifact.artifact_sha256 = None
            artifact.attempt_count = 0
            artifact.last_error = None
            artifact.page_count = None
            artifact.artifact_size = None
            artifact.started_at = None
            artifact.completed_at = None
        self.session.commit()
        self.session.refresh(artifact)
        return PdfArtifactGenerationRequest(artifact, previous_object_name, previous_origin)

    def find_current(self, tenant_id: int, knowledge_file_id: int) -> KnowledgeFilePdfArtifact | None:
        return (
            self.session.execute(select(KnowledgeFilePdfArtifact).where(*self._scope(tenant_id, knowledge_file_id)))
            .scalars()
            .first()
        )

    def find_available(self, tenant_id: int, knowledge_file_id: int) -> KnowledgeFilePdfArtifact | None:
        return (
            self.session.execute(
                select(KnowledgeFilePdfArtifact).where(
                    *self._scope(tenant_id, knowledge_file_id),
                    KnowledgeFilePdfArtifact.status == KnowledgeFilePdfArtifactStatus.SUCCESS.value,
                    KnowledgeFilePdfArtifact.object_name.is_not(None),
                    KnowledgeFilePdfArtifact.artifact_sha256.is_not(None),
                    col(KnowledgeFilePdfArtifact.artifact_origin).in_(_VALID_ORIGINS),
                )
            )
            .scalars()
            .first()
        )

    def claim_generation(
        self,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        started_at: datetime,
    ) -> PdfArtifactClaimResult:
        current = self.find_current(tenant_id, knowledge_file_id)
        if current is None or current.generation != generation:
            return PdfArtifactClaimResult(PdfArtifactClaimState.STALE, current)
        if current.status == KnowledgeFilePdfArtifactStatus.SUCCESS.value:
            return PdfArtifactClaimResult(PdfArtifactClaimState.ALREADY_COMPLETED, current)
        if current.status == KnowledgeFilePdfArtifactStatus.FAILED.value:
            return PdfArtifactClaimResult(PdfArtifactClaimState.FAILED, current)
        result = self.session.execute(
            update(KnowledgeFilePdfArtifact)
            .where(
                *self._scope(tenant_id, knowledge_file_id),
                KnowledgeFilePdfArtifact.generation == generation,
                col(KnowledgeFilePdfArtifact.status).in_(_CLAIMABLE_STATUSES),
            )
            .values(
                status=KnowledgeFilePdfArtifactStatus.PROCESSING.value,
                attempt_count=KnowledgeFilePdfArtifact.attempt_count + 1,
                started_at=started_at,
            )
        )
        self.session.commit()
        refreshed = self.find_current(tenant_id, knowledge_file_id)
        if int(result.rowcount or 0) == 1:
            return PdfArtifactClaimResult(PdfArtifactClaimState.CLAIMED, refreshed)
        if refreshed and refreshed.status == KnowledgeFilePdfArtifactStatus.SUCCESS.value:
            return PdfArtifactClaimResult(PdfArtifactClaimState.ALREADY_COMPLETED, refreshed)
        return PdfArtifactClaimResult(PdfArtifactClaimState.STALE, refreshed)

    def mark_retry(
        self,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        last_error: str,
    ) -> bool:
        result = self.session.execute(
            update(KnowledgeFilePdfArtifact)
            .where(
                *self._scope(tenant_id, knowledge_file_id),
                KnowledgeFilePdfArtifact.generation == generation,
                KnowledgeFilePdfArtifact.status != KnowledgeFilePdfArtifactStatus.SUCCESS.value,
            )
            .values(
                status=KnowledgeFilePdfArtifactStatus.WAITING.value,
                last_error=last_error[:2000],
            )
        )
        self.session.commit()
        return int(result.rowcount or 0) == 1

    def complete_generation(
        self,
        *,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        origin: KnowledgeFilePdfArtifactOrigin,
        object_name: str,
        artifact_sha256: str,
        page_count: int,
        artifact_size: int,
        completed_at: datetime,
    ) -> PdfArtifactCompleteResult:
        if not object_name or not artifact_sha256 or page_count <= 0 or artifact_size <= 0:
            raise ValueError("A completed PDF artifact requires valid object metadata")
        current = self.find_current(tenant_id, knowledge_file_id)
        if (
            current is None
            or current.generation != generation
            or current.status == KnowledgeFilePdfArtifactStatus.SUCCESS.value
        ):
            return PdfArtifactCompleteResult(False, current)
        previous_object_name = current.object_name
        previous_origin = current.artifact_origin
        result = self.session.execute(
            update(KnowledgeFilePdfArtifact)
            .where(
                *self._scope(tenant_id, knowledge_file_id),
                KnowledgeFilePdfArtifact.generation == generation,
                col(KnowledgeFilePdfArtifact.status).in_(_COMPLETABLE_STATUSES),
            )
            .values(
                status=KnowledgeFilePdfArtifactStatus.SUCCESS.value,
                artifact_origin=origin.value,
                object_name=object_name,
                artifact_sha256=artifact_sha256,
                page_count=page_count,
                artifact_size=artifact_size,
                completed_at=completed_at,
                last_error=None,
            )
        )
        self.session.commit()
        refreshed = self.find_current(tenant_id, knowledge_file_id)
        completed = int(result.rowcount or 0) == 1
        return PdfArtifactCompleteResult(
            completed=completed,
            artifact=refreshed,
            previous_object_name=previous_object_name if completed else None,
            previous_origin=previous_origin if completed else None,
        )

    def find_by_file_ids(self, tenant_id: int, knowledge_file_ids: list[int]) -> list[KnowledgeFilePdfArtifact]:
        if not knowledge_file_ids:
            return []
        result = self.session.execute(
            select(KnowledgeFilePdfArtifact).where(
                KnowledgeFilePdfArtifact.tenant_id == tenant_id,
                col(KnowledgeFilePdfArtifact.knowledge_file_id).in_(knowledge_file_ids),
            )
        )
        return list(result.scalars().all())

    def fail_generation(
        self,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        last_error: str,
    ) -> bool:
        result = self.session.execute(
            update(KnowledgeFilePdfArtifact)
            .where(
                *self._scope(tenant_id, knowledge_file_id),
                KnowledgeFilePdfArtifact.generation == generation,
                KnowledgeFilePdfArtifact.status != KnowledgeFilePdfArtifactStatus.SUCCESS.value,
            )
            .values(
                status=KnowledgeFilePdfArtifactStatus.FAILED.value,
                last_error=last_error[:2000],
            )
        )
        self.session.commit()
        return int(result.rowcount or 0) == 1

    def delete_by_file_ids(self, tenant_id: int, knowledge_file_ids: list[int]) -> int:
        if not knowledge_file_ids:
            return 0
        result = self.session.execute(
            delete(KnowledgeFilePdfArtifact).where(
                KnowledgeFilePdfArtifact.tenant_id == tenant_id,
                col(KnowledgeFilePdfArtifact.knowledge_file_id).in_(knowledge_file_ids),
            )
        )
        self.session.commit()
        return int(result.rowcount or 0)
