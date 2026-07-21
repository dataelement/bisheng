"""统一 PDF Artifact 的独立 Celery 处理任务。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from loguru import logger
from sqlmodel import select

from bisheng.common.services.config_service import settings
from bisheng.core.config.settings import KnowledgePdfArtifactConf
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_sync_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifactOrigin,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_pdf_artifact_repository_impl import (
    KnowledgeFilePdfArtifactSyncRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_pdf_artifact_repository import (
    PdfArtifactClaimState,
)
from bisheng.knowledge.pdf.converter import (
    SUPPORTED_EXTENSIONS,
    ConversionContext,
    PdfConversionError,
    PdfConverterRegistry,
)
from bisheng.knowledge.pdf.validator import PdfValidationError, validate_pdf
from bisheng.worker.main import bisheng_celery

_ATTEMPT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class PdfArtifactProcessOutcome(str, Enum):
    COMPLETED = "completed"
    STALE = "stale"
    ALREADY_COMPLETED = "already_completed"
    FAILED = "failed"


class PdfArtifactSourceChangedError(RuntimeError):
    """Artifact 快照与当前物理文件已不一致。"""


class PdfArtifactTenantMismatchError(RuntimeError):
    """Celery header 恢复出的租户与显式参数不一致。"""


class PdfArtifactStorageError(RuntimeError):
    """对象存储没有返回可转换的源字节。"""


class PdfArtifactTaskFailureAction(str, Enum):
    RETRY = "retry"
    FAILED = "failed"
    NOOP = "noop"


@dataclass(frozen=True)
class PdfArtifactTaskFailureDecision:
    action: PdfArtifactTaskFailureAction
    countdown: int | None = None


def _bounded_error_summary(error: Exception) -> str:
    return f"process:{type(error).__name__}"[:2000]


def record_pdf_artifact_task_failure(
    *,
    repository,
    tenant_id: int,
    knowledge_file_id: int,
    generation: int,
    completed_retries: int,
    config: KnowledgePdfArtifactConf,
    error: Exception,
) -> PdfArtifactTaskFailureDecision:
    """按 generation 条件记录重试或最终失败; 避免晚到失败覆盖成功。"""

    summary = _bounded_error_summary(error)
    if completed_retries < config.max_retries:
        updated = repository.mark_retry(
            tenant_id,
            knowledge_file_id,
            generation,
            summary,
        )
        if not updated:
            return PdfArtifactTaskFailureDecision(PdfArtifactTaskFailureAction.NOOP)
        countdown = min(
            config.retry_base_seconds * (2**completed_retries),
            config.retry_max_seconds,
        )
        return PdfArtifactTaskFailureDecision(
            PdfArtifactTaskFailureAction.RETRY,
            countdown=countdown,
        )

    updated = repository.fail_generation(
        tenant_id,
        knowledge_file_id,
        generation,
        summary,
    )
    return PdfArtifactTaskFailureDecision(
        PdfArtifactTaskFailureAction.FAILED if updated else PdfArtifactTaskFailureAction.NOOP
    )


class PdfArtifactProcessor:
    """可注入依赖的单次 attempt 处理器; Celery 只负责重试边界。"""

    def __init__(
        self,
        *,
        repository,
        storage,
        file_loader,
        converter_registry: PdfConverterRegistry | None = None,
        conversion_context: ConversionContext | None = None,
        attempt_token_factory=None,
        now_factory=None,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.file_loader = file_loader
        self.converter_registry = converter_registry or PdfConverterRegistry()
        self.conversion_context = conversion_context or ConversionContext()
        self.attempt_token_factory = attempt_token_factory or (lambda: uuid4().hex)
        self.now_factory = now_factory or datetime.now

    @staticmethod
    def _validate_source_snapshot(artifact, file: KnowledgeFile, tenant_id: int) -> None:
        if (
            file.id != artifact.knowledge_file_id
            or file.tenant_id != tenant_id
            or artifact.tenant_id != tenant_id
            or file.object_name != artifact.source_object_name
            or file.md5 != artifact.source_md5
        ):
            raise PdfArtifactSourceChangedError("Current file does not match the artifact snapshot")

    def _download_to(self, object_name: str, local_path: Path) -> None:
        try:
            content = self.storage.get_object_sync(object_name=object_name)
        except Exception as exc:
            raise PdfArtifactStorageError("Source object is unavailable") from exc
        if not content:
            raise PdfArtifactStorageError("Source object is empty or unavailable")
        local_path.write_bytes(content)

    def _best_effort_remove(
        self,
        object_name: str,
        *,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
    ) -> None:
        try:
            self.storage.remove_object_sync(object_name=object_name)
        except Exception as exc:
            logger.warning(
                "knowledge_pdf_artifact_object_cleanup_failed "
                "tenant_id={} file_id={} generation={} object_name={} error_type={}",
                tenant_id,
                knowledge_file_id,
                generation,
                object_name,
                type(exc).__name__,
            )

    def _cleanup_replaced_generated(
        self,
        complete_result,
        *,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        current_object_name: str,
    ) -> None:
        if (
            complete_result.previous_origin != KnowledgeFilePdfArtifactOrigin.GENERATED.value
            or not complete_result.previous_object_name
            or complete_result.previous_object_name == current_object_name
        ):
            return
        self._best_effort_remove(
            complete_result.previous_object_name,
            tenant_id=tenant_id,
            knowledge_file_id=knowledge_file_id,
            generation=generation,
        )

    def _complete(
        self,
        *,
        artifact,
        origin: KnowledgeFilePdfArtifactOrigin,
        object_name: str,
        validation,
    ):
        return self.repository.complete_generation(
            tenant_id=int(artifact.tenant_id),
            knowledge_file_id=int(artifact.knowledge_file_id),
            generation=int(artifact.generation),
            origin=origin,
            object_name=object_name,
            artifact_sha256=validation.artifact_sha256,
            page_count=validation.page_count,
            artifact_size=validation.artifact_size,
            completed_at=self.now_factory(),
        )

    @staticmethod
    def _preview_candidate(file: KnowledgeFile, artifact) -> str | None:
        metadata = file.user_metadata or {}
        object_name = metadata.get("pdf_preview_object_name")
        source_md5 = metadata.get("pdf_preview_source_md5")
        if (
            not object_name
            or Path(str(object_name)).suffix.lower() != ".pdf"
            or not source_md5
            or source_md5 != artifact.source_md5
            or source_md5 != file.md5
        ):
            return None
        return str(object_name)

    def _finish_shared_candidate(
        self,
        *,
        artifact,
        origin: KnowledgeFilePdfArtifactOrigin,
        object_name: str,
        local_path: Path,
    ) -> PdfArtifactProcessOutcome:
        validation = validate_pdf(local_path)
        complete_result = self._complete(
            artifact=artifact,
            origin=origin,
            object_name=object_name,
            validation=validation,
        )
        if not complete_result.completed:
            return PdfArtifactProcessOutcome.STALE
        self._cleanup_replaced_generated(
            complete_result,
            tenant_id=int(artifact.tenant_id),
            knowledge_file_id=int(artifact.knowledge_file_id),
            generation=int(artifact.generation),
            current_object_name=object_name,
        )
        return PdfArtifactProcessOutcome.COMPLETED

    def process(
        self,
        *,
        knowledge_file_id: int,
        generation: int,
        tenant_id: int,
    ) -> PdfArtifactProcessOutcome:
        claim = self.repository.claim_generation(
            tenant_id,
            knowledge_file_id,
            generation,
            self.now_factory(),
        )
        if claim.state == PdfArtifactClaimState.ALREADY_COMPLETED:
            return PdfArtifactProcessOutcome.ALREADY_COMPLETED
        if claim.state == PdfArtifactClaimState.FAILED:
            return PdfArtifactProcessOutcome.FAILED
        if claim.state != PdfArtifactClaimState.CLAIMED or claim.artifact is None:
            return PdfArtifactProcessOutcome.STALE

        artifact = claim.artifact
        file = self.file_loader(tenant_id, knowledge_file_id)
        if file is None:
            return PdfArtifactProcessOutcome.STALE
        self._validate_source_snapshot(artifact, file, tenant_id)

        extension = Path(file.file_name or "").suffix.lower().lstrip(".")
        if extension not in SUPPORTED_EXTENSIONS:
            raise PdfArtifactSourceChangedError("Current file extension is unsupported")
        logger.info(
            "knowledge_pdf_artifact_attempt_started tenant_id={} file_id={} generation={} format={} attempt={}",
            tenant_id,
            knowledge_file_id,
            generation,
            extension,
            artifact.attempt_count,
        )

        with TemporaryDirectory(prefix="bisheng-pdf-artifact-") as temporary_directory:
            root = Path(temporary_directory)
            if extension == "pdf":
                source_path = root / "source.pdf"
                self._download_to(artifact.source_object_name, source_path)
                return self._finish_shared_candidate(
                    artifact=artifact,
                    origin=KnowledgeFilePdfArtifactOrigin.ORIGINAL,
                    object_name=artifact.source_object_name,
                    local_path=source_path,
                )

            preview_object_name = self._preview_candidate(file, artifact)
            if preview_object_name:
                preview_path = root / "preview.pdf"
                try:
                    self._download_to(preview_object_name, preview_path)
                    return self._finish_shared_candidate(
                        artifact=artifact,
                        origin=KnowledgeFilePdfArtifactOrigin.PARSE_PREVIEW,
                        object_name=preview_object_name,
                        local_path=preview_path,
                    )
                except (PdfArtifactStorageError, PdfValidationError, OSError) as exc:
                    logger.warning(
                        "knowledge_pdf_artifact_preview_fallback tenant_id={} file_id={} generation={} error_type={}",
                        tenant_id,
                        knowledge_file_id,
                        generation,
                        type(exc).__name__,
                    )

            source_path = root / f"source.{extension}"
            self._download_to(artifact.source_object_name, source_path)
            output_directory = root / "output"
            output_directory.mkdir(parents=True, exist_ok=True)
            conversion = self.converter_registry.convert(
                source_path,
                output_directory,
                self.conversion_context,
            )
            validation = validate_pdf(conversion.pdf_path)
            attempt_token = str(self.attempt_token_factory())
            if not _ATTEMPT_TOKEN_RE.fullmatch(attempt_token):
                raise PdfConversionError("Invalid internal attempt token")
            generated_object_name = f"knowledge/pdf-artifacts/{knowledge_file_id}/{generation}/{attempt_token}.pdf"
            uploaded = False
            try:
                self.storage.put_object_sync(
                    object_name=generated_object_name,
                    file=conversion.pdf_path,
                    content_type="application/pdf",
                )
                uploaded = True
                complete_result = self._complete(
                    artifact=artifact,
                    origin=KnowledgeFilePdfArtifactOrigin.GENERATED,
                    object_name=generated_object_name,
                    validation=validation,
                )
                if not complete_result.completed:
                    self._best_effort_remove(
                        generated_object_name,
                        tenant_id=tenant_id,
                        knowledge_file_id=knowledge_file_id,
                        generation=generation,
                    )
                    uploaded = False
                    return PdfArtifactProcessOutcome.STALE
                uploaded = False
                self._cleanup_replaced_generated(
                    complete_result,
                    tenant_id=tenant_id,
                    knowledge_file_id=knowledge_file_id,
                    generation=generation,
                    current_object_name=generated_object_name,
                )
                return PdfArtifactProcessOutcome.COMPLETED
            finally:
                if uploaded:
                    self._best_effort_remove(
                        generated_object_name,
                        tenant_id=tenant_id,
                        knowledge_file_id=knowledge_file_id,
                        generation=generation,
                    )


def _load_file(session, tenant_id: int, knowledge_file_id: int) -> KnowledgeFile | None:
    return (
        session.execute(
            select(KnowledgeFile).where(
                KnowledgeFile.id == knowledge_file_id,
                KnowledgeFile.tenant_id == tenant_id,
            )
        )
        .scalars()
        .first()
    )


def _process_pdf_artifact_attempt(
    *,
    tenant_id: int,
    knowledge_file_id: int,
    generation: int,
    config: KnowledgePdfArtifactConf,
) -> PdfArtifactProcessOutcome:
    current_tenant_id = get_current_tenant_id()
    if current_tenant_id != tenant_id:
        raise PdfArtifactTenantMismatchError("Celery tenant context does not match task parameters")

    storage = get_minio_storage_sync()
    with get_sync_db_session() as session:
        repository = KnowledgeFilePdfArtifactSyncRepositoryImpl(session)
        processor = PdfArtifactProcessor(
            repository=repository,
            storage=storage,
            file_loader=lambda expected_tenant_id, file_id: _load_file(
                session,
                expected_tenant_id,
                file_id,
            ),
            conversion_context=ConversionContext(timeout_seconds=config.conversion_timeout_seconds),
        )
        return processor.process(
            tenant_id=tenant_id,
            knowledge_file_id=knowledge_file_id,
            generation=generation,
        )


def _record_failure_with_new_session(
    *,
    tenant_id: int,
    knowledge_file_id: int,
    generation: int,
    completed_retries: int,
    config: KnowledgePdfArtifactConf,
    error: Exception,
) -> PdfArtifactTaskFailureDecision:
    with get_sync_db_session() as session:
        repository = KnowledgeFilePdfArtifactSyncRepositoryImpl(session)
        return record_pdf_artifact_task_failure(
            repository=repository,
            tenant_id=tenant_id,
            knowledge_file_id=knowledge_file_id,
            generation=generation,
            completed_retries=completed_retries,
            config=config,
            error=error,
        )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
    name="bisheng.worker.knowledge.pdf_artifact_worker.generate_knowledge_file_pdf_celery",
)
def generate_knowledge_file_pdf_celery(
    self,
    knowledge_file_id: int,
    generation: int,
    tenant_id: int,
) -> str:
    config = settings.get_knowledge().pdf_artifact
    try:
        outcome = _process_pdf_artifact_attempt(
            tenant_id=tenant_id,
            knowledge_file_id=knowledge_file_id,
            generation=generation,
            config=config,
        )
        logger.info(
            "knowledge_pdf_artifact_task_finished tenant_id={} file_id={} generation={} outcome={}",
            tenant_id,
            knowledge_file_id,
            generation,
            outcome.value,
        )
        return outcome.value
    except Exception as exc:
        completed_retries = int(getattr(self.request, "retries", 0) or 0)
        sanitized_error = PdfConversionError(_bounded_error_summary(exc))
        try:
            decision = _record_failure_with_new_session(
                tenant_id=tenant_id,
                knowledge_file_id=knowledge_file_id,
                generation=generation,
                completed_retries=completed_retries,
                config=config,
                error=exc,
            )
        except Exception as persistence_exc:
            logger.error(
                "knowledge_pdf_artifact_failure_state_persist_failed "
                "tenant_id={} file_id={} generation={} process_error_type={} persistence_error_type={}",
                tenant_id,
                knowledge_file_id,
                generation,
                type(exc).__name__,
                type(persistence_exc).__name__,
            )
            raise sanitized_error from None
        if decision.action == PdfArtifactTaskFailureAction.NOOP:
            logger.info(
                "knowledge_pdf_artifact_task_failure_ignored tenant_id={} file_id={} generation={} error_type={}",
                tenant_id,
                knowledge_file_id,
                generation,
                type(exc).__name__,
            )
            return PdfArtifactTaskFailureAction.NOOP.value
        if decision.action == PdfArtifactTaskFailureAction.RETRY:
            logger.error(
                "knowledge_pdf_artifact_task_retry tenant_id={} file_id={} generation={} retry={} error_type={}",
                tenant_id,
                knowledge_file_id,
                generation,
                completed_retries + 1,
                type(exc).__name__,
            )
            raise self.retry(
                exc=sanitized_error,
                countdown=decision.countdown,
                max_retries=config.max_retries,
            )
        logger.error(
            "knowledge_pdf_artifact_task_failed tenant_id={} file_id={} generation={} attempts={} error_type={}",
            tenant_id,
            knowledge_file_id,
            generation,
            completed_retries + 1,
            type(exc).__name__,
        )
        raise sanitized_error from None
