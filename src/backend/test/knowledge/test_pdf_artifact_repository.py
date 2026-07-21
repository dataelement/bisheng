from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
    KnowledgeFilePdfArtifactOrigin,
    KnowledgeFilePdfArtifactStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_pdf_artifact_repository_impl import (
    KnowledgeFilePdfArtifactRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_pdf_artifact_repository import (
    PdfArtifactClaimState,
    PdfArtifactSourceSnapshot,
)


@pytest.fixture
async def repository() -> KnowledgeFilePdfArtifactRepositoryImpl:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFile.__table__.create)
        await connection.run_sync(KnowledgeFilePdfArtifact.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield KnowledgeFilePdfArtifactRepositoryImpl(session)
    await engine.dispose()


def _snapshot(md5: str = "source-v1") -> PdfArtifactSourceSnapshot:
    return PdfArtifactSourceSnapshot(
        tenant_id=7,
        knowledge_file_id=101,
        source_object_name="original/101.docx",
        source_md5=md5,
    )


async def test_request_generation_creates_waiting_then_invalidates_success(
    repository: KnowledgeFilePdfArtifactRepositoryImpl,
) -> None:
    first = await repository.request_generation(_snapshot())
    assert first.artifact.generation == 1
    assert first.artifact.status == KnowledgeFilePdfArtifactStatus.WAITING.value
    assert first.previous_object_name is None

    completed = await repository.complete_generation(
        tenant_id=7,
        knowledge_file_id=101,
        generation=1,
        origin=KnowledgeFilePdfArtifactOrigin.GENERATED,
        object_name="knowledge/pdf-artifacts/101/1/a.pdf",
        artifact_sha256="a" * 64,
        page_count=2,
        artifact_size=120,
        completed_at=datetime(2026, 7, 20),
    )
    assert completed.completed is True

    second = await repository.request_generation(_snapshot("source-v2"))
    assert second.artifact.generation == 2
    assert second.artifact.status == KnowledgeFilePdfArtifactStatus.WAITING.value
    assert second.artifact.source_md5 == "source-v2"
    assert second.artifact.artifact_sha256 is None
    assert second.previous_object_name == "knowledge/pdf-artifacts/101/1/a.pdf"
    assert second.previous_origin == KnowledgeFilePdfArtifactOrigin.GENERATED.value

    assert await repository.find_available(7, 101) is None


async def test_on_demand_request_reuses_inflight_generation(
    repository: KnowledgeFilePdfArtifactRepositoryImpl,
) -> None:
    first = await repository.request_on_demand_generation(_snapshot())
    second = await repository.request_on_demand_generation(_snapshot())

    assert first.artifact.generation == 1
    assert second.artifact.generation == 1
    assert second.artifact.status == KnowledgeFilePdfArtifactStatus.WAITING.value

    await repository.claim_generation(7, 101, 1, datetime(2026, 7, 20))
    processing = await repository.request_on_demand_generation(_snapshot())

    assert processing.artifact.generation == 1
    assert processing.artifact.status == KnowledgeFilePdfArtifactStatus.PROCESSING.value


async def test_on_demand_request_restarts_failed_or_changed_source(
    repository: KnowledgeFilePdfArtifactRepositoryImpl,
) -> None:
    first = await repository.request_on_demand_generation(_snapshot())
    await repository.fail_generation(7, 101, first.artifact.generation, "conversion failed")

    retried = await repository.request_on_demand_generation(_snapshot())
    retried_generation = retried.artifact.generation
    changed = await repository.request_on_demand_generation(_snapshot("source-v2"))

    assert retried_generation == 2
    assert changed.artifact.generation == 3
    assert changed.artifact.source_md5 == "source-v2"


async def test_on_demand_forced_repair_is_generation_scoped(
    repository: KnowledgeFilePdfArtifactRepositoryImpl,
) -> None:
    first = await repository.request_generation(_snapshot())
    await repository.complete_generation(
        tenant_id=7,
        knowledge_file_id=101,
        generation=first.artifact.generation,
        origin=KnowledgeFilePdfArtifactOrigin.GENERATED,
        object_name="knowledge/pdf-artifacts/101/1/broken.pdf",
        artifact_sha256="a" * 64,
        page_count=1,
        artifact_size=100,
        completed_at=datetime(2026, 7, 20),
    )

    repair = await repository.request_on_demand_generation(
        _snapshot(),
        invalid_generation=1,
    )
    concurrent = await repository.request_on_demand_generation(
        _snapshot(),
        invalid_generation=1,
    )

    assert repair.artifact.generation == 2
    assert repair.artifact.status == KnowledgeFilePdfArtifactStatus.WAITING.value
    assert concurrent.artifact.generation == 2


async def test_claim_and_retry_are_generation_scoped(
    repository: KnowledgeFilePdfArtifactRepositoryImpl,
) -> None:
    await repository.request_generation(_snapshot())

    claim = await repository.claim_generation(7, 101, 1, datetime(2026, 7, 20))
    assert claim.state == PdfArtifactClaimState.CLAIMED
    assert claim.artifact is not None
    assert claim.artifact.attempt_count == 1
    assert claim.artifact.status == KnowledgeFilePdfArtifactStatus.PROCESSING.value

    assert await repository.mark_retry(7, 101, 99, "stale") is False
    assert await repository.mark_retry(7, 101, 1, "temporary failure") is True
    current = await repository.find_current(7, 101)
    assert current is not None
    assert current.status == KnowledgeFilePdfArtifactStatus.WAITING.value
    assert current.last_error == "temporary failure"


async def test_first_success_wins_and_late_failure_cannot_override(
    repository: KnowledgeFilePdfArtifactRepositoryImpl,
) -> None:
    await repository.request_generation(_snapshot())
    await repository.claim_generation(7, 101, 1, datetime(2026, 7, 20))

    first = await repository.complete_generation(
        tenant_id=7,
        knowledge_file_id=101,
        generation=1,
        origin=KnowledgeFilePdfArtifactOrigin.ORIGINAL,
        object_name="original/101.pdf",
        artifact_sha256="b" * 64,
        page_count=1,
        artifact_size=64,
        completed_at=datetime(2026, 7, 20),
    )
    second = await repository.complete_generation(
        tenant_id=7,
        knowledge_file_id=101,
        generation=1,
        origin=KnowledgeFilePdfArtifactOrigin.GENERATED,
        object_name="knowledge/pdf-artifacts/101/1/late.pdf",
        artifact_sha256="c" * 64,
        page_count=1,
        artifact_size=65,
        completed_at=datetime(2026, 7, 20),
    )

    assert first.completed is True
    assert second.completed is False
    assert await repository.fail_generation(7, 101, 1, "late failure") is False
    available = await repository.find_available(7, 101)
    assert available is not None
    assert available.object_name == "original/101.pdf"
    assert available.status == KnowledgeFilePdfArtifactStatus.SUCCESS.value


async def test_old_generation_cannot_mutate_new_generation(
    repository: KnowledgeFilePdfArtifactRepositoryImpl,
) -> None:
    await repository.request_generation(_snapshot())
    await repository.request_generation(_snapshot("source-v2"))

    stale_claim = await repository.claim_generation(7, 101, 1, datetime(2026, 7, 20))
    assert stale_claim.state == PdfArtifactClaimState.STALE
    assert await repository.fail_generation(7, 101, 1, "stale") is False
    current = await repository.find_current(7, 101)
    assert current is not None
    assert current.generation == 2
    assert current.status == KnowledgeFilePdfArtifactStatus.WAITING.value


async def test_artifact_state_changes_do_not_touch_knowledge_file_business_fields(
    repository: KnowledgeFilePdfArtifactRepositoryImpl,
) -> None:
    original_update_time = datetime(2026, 7, 1, 8, 30)
    file = KnowledgeFile(
        id=101,
        tenant_id=7,
        knowledge_id=9,
        file_name="report.docx",
        object_name="original/101.docx",
        md5="source-v1",
        status=KnowledgeFileStatus.SUCCESS.value,
        remark="keep-business-state",
        update_time=original_update_time,
    )
    repository.session.add(file)
    await repository.session.commit()

    await repository.request_generation(_snapshot())
    await repository.claim_generation(7, 101, 1, datetime(2026, 7, 20))
    await repository.fail_generation(7, 101, 1, "conversion failed")

    await repository.session.refresh(file)
    assert file.status == KnowledgeFileStatus.SUCCESS.value
    assert file.remark == "keep-business-state"
    assert file.update_time == original_update_time
