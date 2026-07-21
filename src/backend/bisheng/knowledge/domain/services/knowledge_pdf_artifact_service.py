"""统一 PDF Artifact 的 generation、投递与删除快照服务。"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from kombu.exceptions import KombuError, OperationalError
from loguru import logger

from bisheng.core.config.settings import KnowledgePdfArtifactConf
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifactOrigin,
    KnowledgeFilePdfArtifactStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_pdf_artifact_repository import (
    PdfArtifactGenerationRequest,
    PdfArtifactSourceSnapshot,
)
from bisheng.knowledge.pdf.converter import SUPPORTED_EXTENSIONS

_BROKER_PUBLISH_EXCEPTIONS = (
    KombuError,
    OperationalError,
    ConnectionError,
    TimeoutError,
    OSError,
)


@dataclass(frozen=True)
class PdfArtifactReference:
    """后续水印链路可依赖的当前 PDF 引用。

    不暴露引用来自原始文件、解析预览还是 Artifact 生成对象。
    """

    tenant_id: int
    knowledge_file_id: int
    generation: int
    object_name: str
    artifact_sha256: str
    page_count: int
    artifact_size: int
    completed_at: datetime


@dataclass(frozen=True)
class PdfArtifactDeletionSnapshot:
    """父文件删除前冻结的 Artifact 对象归属信息。"""

    tenant_id: int
    knowledge_file_id: int
    generation: int
    object_name: str | None
    artifact_origin: int | None

    @property
    def artifact_owned_object_name(self) -> str | None:
        if self.artifact_origin != KnowledgeFilePdfArtifactOrigin.GENERATED.value:
            return None
        return self.object_name

    def to_dict(self) -> dict[str, int | str | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PdfArtifactDeletionSnapshot:
        artifact_origin = value.get("artifact_origin")
        return cls(
            tenant_id=int(value["tenant_id"]),
            knowledge_file_id=int(value["knowledge_file_id"]),
            generation=int(value["generation"]),
            object_name=value.get("object_name"),
            artifact_origin=int(artifact_origin) if artifact_origin is not None else None,
        )


class KnowledgePdfArtifactService:
    """复用同步/异步 Repository 的无 ORM 业务编排。"""

    def __init__(
        self,
        *,
        repository,
        config: KnowledgePdfArtifactConf,
        task=None,
    ) -> None:
        self.repository = repository
        self.config = config
        self._task = task

    @staticmethod
    def _skip_reason(
        file: KnowledgeFile,
        source_object_name: str | None,
    ) -> str | None:
        if file.id is None or file.tenant_id is None:
            return "not_persisted"
        if file.file_type != FileType.FILE.value:
            return "not_physical_file"
        if file.file_source == "favorite_reference":
            return "favorite_reference"
        if not source_object_name:
            return "missing_source_object"
        extension = Path(file.file_name or "").suffix.lower().lstrip(".")
        if extension not in SUPPORTED_EXTENSIONS:
            return "unsupported_extension"
        return None

    def _source_snapshot(
        self,
        file: KnowledgeFile,
        *,
        source_object_name: str | None,
        source_md5: str | None,
    ) -> PdfArtifactSourceSnapshot | None:
        object_name = source_object_name or file.object_name
        reason = self._skip_reason(file, object_name)
        if reason:
            logger.info(
                "knowledge_pdf_artifact_request_skipped tenant_id={} file_id={} reason={}",
                file.tenant_id,
                file.id,
                reason,
            )
            return None
        return PdfArtifactSourceSnapshot(
            tenant_id=int(file.tenant_id),
            knowledge_file_id=int(file.id),
            source_object_name=str(object_name),
            source_md5=file.md5 if source_md5 is None else source_md5,
        )

    def request_generation_sync(
        self,
        file: KnowledgeFile,
        *,
        source_object_name: str | None = None,
        source_md5: str | None = None,
    ) -> PdfArtifactGenerationRequest | None:
        snapshot = self._source_snapshot(
            file,
            source_object_name=source_object_name,
            source_md5=source_md5,
        )
        if snapshot is None:
            return None
        return self.repository.request_generation(snapshot)

    async def request_generation(
        self,
        file: KnowledgeFile,
        *,
        source_object_name: str | None = None,
        source_md5: str | None = None,
    ) -> PdfArtifactGenerationRequest | None:
        snapshot = self._source_snapshot(
            file,
            source_object_name=source_object_name,
            source_md5=source_md5,
        )
        if snapshot is None:
            return None
        return await self.repository.request_generation(snapshot)

    @staticmethod
    def _build_available_reference(
        file: KnowledgeFile,
        artifact,
    ) -> PdfArtifactReference | None:
        if artifact is None:
            return None
        if (
            file.id is None
            or file.tenant_id is None
            or int(artifact.knowledge_file_id) != int(file.id)
            or int(artifact.tenant_id) != int(file.tenant_id)
            or artifact.source_object_name != file.object_name
            or artifact.source_md5 != file.md5
            or not artifact.object_name
            or not artifact.artifact_sha256
            or not artifact.page_count
            or artifact.page_count <= 0
            or not artifact.artifact_size
            or artifact.artifact_size <= 0
            or artifact.completed_at is None
        ):
            return None
        return PdfArtifactReference(
            tenant_id=int(artifact.tenant_id),
            knowledge_file_id=int(artifact.knowledge_file_id),
            generation=int(artifact.generation),
            object_name=str(artifact.object_name),
            artifact_sha256=str(artifact.artifact_sha256),
            page_count=int(artifact.page_count),
            artifact_size=int(artifact.artifact_size),
            completed_at=artifact.completed_at,
        )

    def get_available_reference_sync(
        self,
        file: KnowledgeFile,
    ) -> PdfArtifactReference | None:
        """仅返回与当前文件源快照仍一致的 SUCCESS 产物。"""

        if file.id is None or file.tenant_id is None:
            return None
        artifact = self.repository.find_available(int(file.tenant_id), int(file.id))
        return self._build_available_reference(file, artifact)

    async def get_available_reference(
        self,
        file: KnowledgeFile,
    ) -> PdfArtifactReference | None:
        """异步 accessor, 语义与同步版完全一致。"""

        if file.id is None or file.tenant_id is None:
            return None
        artifact = await self.repository.find_available(int(file.tenant_id), int(file.id))
        return self._build_available_reference(file, artifact)

    def _resolve_task(self):
        if self._task is None:
            from bisheng.worker.knowledge.pdf_artifact_worker import (
                generate_knowledge_file_pdf_celery,
            )

            self._task = generate_knowledge_file_pdf_celery
        return self._task

    def _publish(self, artifact) -> None:
        self._resolve_task().apply_async(
            args=(
                int(artifact.knowledge_file_id),
                int(artifact.generation),
                int(artifact.tenant_id),
            ),
            queue=self.config.queue_name,
            headers={"tenant_id": int(artifact.tenant_id)},
        )

    @staticmethod
    def _is_publishable(artifact) -> bool:
        return bool(
            artifact
            and artifact.status
            in {
                KnowledgeFilePdfArtifactStatus.WAITING.value,
                KnowledgeFilePdfArtifactStatus.PROCESSING.value,
            }
        )

    def enqueue_current_sync(self, *, tenant_id: int, knowledge_file_id: int) -> bool:
        if not self.config.enabled:
            return False
        artifact = self.repository.find_current(tenant_id, knowledge_file_id)
        if not self._is_publishable(artifact):
            return False
        try:
            self._publish(artifact)
        except _BROKER_PUBLISH_EXCEPTIONS as exc:
            summary = f"publish:{type(exc).__name__}"
            try:
                self.repository.fail_generation(
                    tenant_id,
                    knowledge_file_id,
                    int(artifact.generation),
                    summary,
                )
            except Exception as compensation_exc:
                logger.error(
                    "knowledge_pdf_artifact_publish_compensation_failed "
                    "tenant_id={} file_id={} generation={} publish_error_type={} "
                    "compensation_error_type={}",
                    tenant_id,
                    knowledge_file_id,
                    artifact.generation,
                    type(exc).__name__,
                    type(compensation_exc).__name__,
                )
            logger.error(
                "knowledge_pdf_artifact_publish_failed tenant_id={} file_id={} generation={} error_type={}",
                tenant_id,
                knowledge_file_id,
                artifact.generation,
                type(exc).__name__,
            )
            return False
        return True

    async def enqueue_current(self, *, tenant_id: int, knowledge_file_id: int) -> bool:
        if not self.config.enabled:
            return False
        artifact = await self.repository.find_current(tenant_id, knowledge_file_id)
        if not self._is_publishable(artifact):
            return False
        try:
            self._publish(artifact)
        except _BROKER_PUBLISH_EXCEPTIONS as exc:
            summary = f"publish:{type(exc).__name__}"
            try:
                await self.repository.fail_generation(
                    tenant_id,
                    knowledge_file_id,
                    int(artifact.generation),
                    summary,
                )
            except Exception as compensation_exc:
                logger.error(
                    "knowledge_pdf_artifact_publish_compensation_failed "
                    "tenant_id={} file_id={} generation={} publish_error_type={} "
                    "compensation_error_type={}",
                    tenant_id,
                    knowledge_file_id,
                    artifact.generation,
                    type(exc).__name__,
                    type(compensation_exc).__name__,
                )
            logger.error(
                "knowledge_pdf_artifact_publish_failed tenant_id={} file_id={} generation={} error_type={}",
                tenant_id,
                knowledge_file_id,
                artifact.generation,
                type(exc).__name__,
            )
            return False
        return True

    def request_and_enqueue_sync(
        self,
        file: KnowledgeFile,
        *,
        source_object_name: str | None = None,
        source_md5: str | None = None,
    ) -> PdfArtifactGenerationRequest | None:
        request = self.request_generation_sync(
            file,
            source_object_name=source_object_name,
            source_md5=source_md5,
        )
        if request is not None:
            self.enqueue_current_sync(
                tenant_id=int(request.artifact.tenant_id),
                knowledge_file_id=int(request.artifact.knowledge_file_id),
            )
        return request

    async def request_and_enqueue(
        self,
        file: KnowledgeFile,
        *,
        source_object_name: str | None = None,
        source_md5: str | None = None,
    ) -> PdfArtifactGenerationRequest | None:
        request = await self.request_generation(
            file,
            source_object_name=source_object_name,
            source_md5=source_md5,
        )
        if request is not None:
            await self.enqueue_current(
                tenant_id=int(request.artifact.tenant_id),
                knowledge_file_id=int(request.artifact.knowledge_file_id),
            )
        return request

    def build_deletion_snapshots_sync(
        self,
        tenant_id: int,
        knowledge_file_ids: list[int],
    ) -> list[PdfArtifactDeletionSnapshot]:
        rows = self.repository.find_by_file_ids(tenant_id, knowledge_file_ids)
        return self._build_deletion_snapshots(rows)

    async def build_deletion_snapshots(
        self,
        tenant_id: int,
        knowledge_file_ids: list[int],
    ) -> list[PdfArtifactDeletionSnapshot]:
        rows = await self.repository.find_by_file_ids(tenant_id, knowledge_file_ids)
        return self._build_deletion_snapshots(rows)

    @staticmethod
    def _build_deletion_snapshots(rows) -> list[PdfArtifactDeletionSnapshot]:
        return [
            PdfArtifactDeletionSnapshot(
                tenant_id=int(row.tenant_id),
                knowledge_file_id=int(row.knowledge_file_id),
                generation=int(row.generation),
                object_name=row.object_name,
                artifact_origin=row.artifact_origin,
            )
            for row in rows
        ]


@contextmanager
def get_knowledge_pdf_artifact_service_sync():
    """为同步业务入口提供受管 Session 的 Artifact Service。"""

    from bisheng.common.services.config_service import settings
    from bisheng.core.database import get_sync_db_session
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_pdf_artifact_repository_impl import (
        KnowledgeFilePdfArtifactSyncRepositoryImpl,
    )

    config = settings.get_knowledge().pdf_artifact
    with get_sync_db_session() as session:
        yield KnowledgePdfArtifactService(
            repository=KnowledgeFilePdfArtifactSyncRepositoryImpl(session),
            config=config,
        )


@asynccontextmanager
async def get_knowledge_pdf_artifact_service():
    """为异步业务入口提供受管 Session 的 Artifact Service。"""

    from bisheng.common.services.config_service import settings
    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_pdf_artifact_repository_impl import (
        KnowledgeFilePdfArtifactRepositoryImpl,
    )

    config = (await settings.async_get_knowledge()).pdf_artifact
    async with get_async_db_session() as session:
        yield KnowledgePdfArtifactService(
            repository=KnowledgeFilePdfArtifactRepositoryImpl(session),
            config=config,
        )


def request_pdf_artifact_generation_sync(
    file: KnowledgeFile,
    *,
    source_object_name: str | None = None,
    source_md5: str | None = None,
    enqueue: bool = False,
) -> PdfArtifactGenerationRequest | None:
    with get_knowledge_pdf_artifact_service_sync() as service:
        if enqueue:
            return service.request_and_enqueue_sync(
                file,
                source_object_name=source_object_name,
                source_md5=source_md5,
            )
        return service.request_generation_sync(
            file,
            source_object_name=source_object_name,
            source_md5=source_md5,
        )


async def request_pdf_artifact_generation(
    file: KnowledgeFile,
    *,
    source_object_name: str | None = None,
    source_md5: str | None = None,
    enqueue: bool = False,
) -> PdfArtifactGenerationRequest | None:
    async with get_knowledge_pdf_artifact_service() as service:
        if enqueue:
            return await service.request_and_enqueue(
                file,
                source_object_name=source_object_name,
                source_md5=source_md5,
            )
        return await service.request_generation(
            file,
            source_object_name=source_object_name,
            source_md5=source_md5,
        )


def get_available_pdf_artifact_reference_sync(
    file: KnowledgeFile,
) -> PdfArtifactReference | None:
    """统一 PDF 产物的同步 Domain accessor。"""

    with get_knowledge_pdf_artifact_service_sync() as service:
        return service.get_available_reference_sync(file)


async def get_available_pdf_artifact_reference(
    file: KnowledgeFile,
) -> PdfArtifactReference | None:
    """统一 PDF 产物的异步 Domain accessor。"""

    async with get_knowledge_pdf_artifact_service() as service:
        return await service.get_available_reference(file)


def enqueue_current_pdf_artifact_sync(*, tenant_id: int, knowledge_file_id: int) -> bool:
    """解析完成 hook 使用的 best-effort 同步投递边界。"""

    try:
        with get_knowledge_pdf_artifact_service_sync() as service:
            return service.enqueue_current_sync(
                tenant_id=tenant_id,
                knowledge_file_id=knowledge_file_id,
            )
    except Exception as exc:
        logger.error(
            "knowledge_pdf_artifact_completion_enqueue_failed tenant_id={} file_id={} error_type={}",
            tenant_id,
            knowledge_file_id,
            type(exc).__name__,
        )
        return False


async def enqueue_current_pdf_artifact(*, tenant_id: int, knowledge_file_id: int) -> bool:
    """解析完成 hook 使用的 best-effort 异步投递边界。"""

    try:
        async with get_knowledge_pdf_artifact_service() as service:
            return await service.enqueue_current(
                tenant_id=tenant_id,
                knowledge_file_id=knowledge_file_id,
            )
    except Exception as exc:
        logger.error(
            "knowledge_pdf_artifact_completion_enqueue_failed tenant_id={} file_id={} error_type={}",
            tenant_id,
            knowledge_file_id,
            type(exc).__name__,
        )
        return False


def get_pdf_artifact_deletion_snapshots_sync(
    tenant_id: int,
    knowledge_file_ids: list[int],
) -> list[PdfArtifactDeletionSnapshot]:
    with get_knowledge_pdf_artifact_service_sync() as service:
        return service.build_deletion_snapshots_sync(tenant_id, knowledge_file_ids)


async def get_pdf_artifact_deletion_snapshots(
    tenant_id: int,
    knowledge_file_ids: list[int],
) -> list[PdfArtifactDeletionSnapshot]:
    async with get_knowledge_pdf_artifact_service() as service:
        return await service.build_deletion_snapshots(tenant_id, knowledge_file_ids)
