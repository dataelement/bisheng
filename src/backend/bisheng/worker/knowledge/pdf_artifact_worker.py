"""统一 PDF Artifact 的 Celery 重试外壳。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.core.config.settings import KnowledgePdfArtifactConf
from bisheng.core.database import get_sync_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_pdf_artifact_repository_impl import (
    KnowledgeFilePdfArtifactSyncRepositoryImpl,
)
from bisheng.knowledge.domain.services.pdf_artifact_generation_service import (
    PdfArtifactProcessor,
    PdfArtifactProcessOutcome,
    PdfArtifactSourceChangedError,
    PdfArtifactStorageError,
    PdfArtifactTenantMismatchError,
)
from bisheng.knowledge.domain.services.pdf_artifact_generation_service import (
    process_pdf_artifact_attempt as shared_process_pdf_artifact_attempt,
)
from bisheng.knowledge.domain.services.pdf_artifact_generation_service import (
    process_pdf_artifact_on_demand as shared_process_pdf_artifact_on_demand,
)
from bisheng.knowledge.pdf.converter import PdfConversionError
from bisheng.worker.main import bisheng_celery

__all__ = [
    "PdfArtifactProcessOutcome",
    "PdfArtifactProcessor",
    "PdfArtifactSourceChangedError",
    "PdfArtifactStorageError",
    "PdfArtifactTenantMismatchError",
    "generate_knowledge_file_pdf_celery",
    "process_pdf_artifact_on_demand",
    "record_pdf_artifact_task_failure",
]


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


def _process_pdf_artifact_attempt(
    *,
    tenant_id: int,
    knowledge_file_id: int,
    generation: int,
    config: KnowledgePdfArtifactConf,
    lock_already_held: bool = False,
) -> PdfArtifactProcessOutcome:
    """兼容既有测试/调用方的共享生成入口。"""

    return shared_process_pdf_artifact_attempt(
        tenant_id=tenant_id,
        knowledge_file_id=knowledge_file_id,
        generation=generation,
        config=config,
        lock_already_held=lock_already_held,
    )


def process_pdf_artifact_on_demand(
    *,
    tenant_id: int,
    knowledge_file_id: int,
    generation: int,
    config: KnowledgePdfArtifactConf,
) -> PdfArtifactProcessOutcome:
    """下载请求已持有文件锁时调用的共享处理入口。"""

    return shared_process_pdf_artifact_on_demand(
        tenant_id=tenant_id,
        knowledge_file_id=knowledge_file_id,
        generation=generation,
        config=config,
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
