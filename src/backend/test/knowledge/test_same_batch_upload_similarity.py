"""Same-batch similarity repair. Uses an isolated database, not live search or a queue."""

from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from bisheng.common.errcode.knowledge_space import UploadBatchKeyRejectedError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import KnowledgeFileSimilarityCandidate
from bisheng.knowledge.domain.models.knowledge_upload_batch import KnowledgeUploadBatch
from bisheng.knowledge.domain.repositories.implementations.knowledge_background_repository_impl import (
    KnowledgeBackgroundRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileCreateReq
from bisheng.knowledge.domain.services import knowledge_upload_batch_service as batch_service
from bisheng.knowledge.domain.services.knowledge_upload_batch_service import (
    UploadBatchEpochStale,
    attach_upload_batch_file,
    finish_parsed_file_similarity,
    prepare_upload_batch,
    reconcile_upload_batch,
    run_similarity_after_parse,
)
from test.knowledge.test_file_similarity_metadata_modes import configure, seed
from test.knowledge.test_knowledge_version_service_similar_scan import _build_svc

KEY_A = "11111111-1111-4111-8111-111111111111"
KEY_B = "22222222-2222-4222-8222-222222222222"


def _bind_session(monkeypatch, session: AsyncSession) -> None:
    @asynccontextmanager
    async def _session():
        yield session

    monkeypatch.setattr(batch_service, "get_async_db_session", _session)


async def _candidate_targets(session: AsyncSession, source_file_id: int) -> set[int]:
    rows = (
        await session.exec(
            select(KnowledgeFileSimilarityCandidate).where(
                KnowledgeFileSimilarityCandidate.source_file_id == source_file_id
            )
        )
    ).all()
    return {int(row.candidate_file_id) for row in rows}


def test_invalid_upload_batch_key_is_rejected_before_files_exist():
    with pytest.raises(ValidationError):
        FileCreateReq(file_path=["/tmp/a.pdf"], upload_batch_key="not-a-uuid")
    blank = FileCreateReq(file_path=["/tmp/a.pdf"], upload_batch_key="  ")
    assert blank.upload_batch_key is None


async def test_other_user_cannot_join_batch_and_no_file_is_created(async_db_session, monkeypatch):
    _bind_session(monkeypatch, async_db_session)
    await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    with pytest.raises(UploadBatchKeyRejectedError):
        await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=12, upload_batch_key=KEY_A)
    files = (await async_db_session.exec(select(KnowledgeFile))).all()
    assert files == []


async def test_same_key_is_one_batch_and_omitted_key_starts_another(async_db_session, monkeypatch):
    _bind_session(monkeypatch, async_db_session)
    first = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    second = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    third = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=None)
    fourth = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=None)
    assert first == second
    assert third != fourth
    assert third != first


async def test_later_file_makes_both_sides_list_each_other(async_db_session, monkeypatch):
    configure(monkeypatch, enable_tfidf_refine=False)
    _bind_session(monkeypatch, async_db_session)
    async_db_session.add(Knowledge(id=1, name="space", type=3, user_id=11, tenant_id=1))
    await async_db_session.commit()
    await seed(async_db_session, 101, tenant_id=1)
    later = await seed(async_db_session, 102, tenant_id=1)
    later.status = KnowledgeFileStatus.PROCESSING.value
    async_db_session.add(later)
    await async_db_session.commit()
    batch_id = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    await attach_upload_batch_file(batch_id=batch_id, file_id=101, tenant_id=1)
    await attach_upload_batch_file(batch_id=batch_id, file_id=102, tenant_id=1)
    scheduled: list[tuple[int, int]] = []

    await finish_parsed_file_similarity(101, schedule=lambda batch, epoch: scheduled.append((batch, epoch)))
    assert 102 not in await _candidate_targets(async_db_session, 101)

    later.status = KnowledgeFileStatus.SUCCESS.value
    async_db_session.add(later)
    await async_db_session.commit()
    await finish_parsed_file_similarity(102, schedule=lambda batch, epoch: scheduled.append((batch, epoch)))
    await reconcile_upload_batch(scheduled[-1][0], scheduled[-1][1])

    assert await _candidate_targets(async_db_session, 101) == {102}
    assert await _candidate_targets(async_db_session, 102) == {101}


async def test_failed_parse_does_not_join_similarity(async_db_session, monkeypatch):
    configure(monkeypatch, enable_tfidf_refine=False)
    _bind_session(monkeypatch, async_db_session)
    async_db_session.add(Knowledge(id=1, name="space", type=3, user_id=11, tenant_id=1))
    await async_db_session.commit()
    await seed(async_db_session, 101, tenant_id=1)
    failed = await seed(async_db_session, 103, tenant_id=1)
    failed.status = KnowledgeFileStatus.FAILED.value
    async_db_session.add(failed)
    await async_db_session.commit()
    batch_id = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    await attach_upload_batch_file(batch_id=batch_id, file_id=101, tenant_id=1)
    await attach_upload_batch_file(batch_id=batch_id, file_id=103, tenant_id=1)
    scheduled: list[tuple[int, int]] = []
    await finish_parsed_file_similarity(101, schedule=lambda batch, epoch: scheduled.append((batch, epoch)))
    await reconcile_upload_batch(scheduled[-1][0], scheduled[-1][1])
    assert await _candidate_targets(async_db_session, 101) == set()
    assert await _candidate_targets(async_db_session, 103) == set()
    refreshed = await async_db_session.get(KnowledgeFile, 103)
    assert refreshed.status == KnowledgeFileStatus.FAILED.value


async def test_dismissed_file_is_not_recalculated(async_db_session, monkeypatch):
    configure(monkeypatch, enable_tfidf_refine=False)
    _bind_session(monkeypatch, async_db_session)
    async_db_session.add(Knowledge(id=1, name="space", type=3, user_id=11, tenant_id=1))
    await async_db_session.commit()
    dismissed = await seed(async_db_session, 101, tenant_id=1)
    dismissed.similar_status = 2
    async_db_session.add(dismissed)
    await seed(async_db_session, 102, tenant_id=1)
    await async_db_session.commit()
    batch_id = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    await attach_upload_batch_file(batch_id=batch_id, file_id=101, tenant_id=1)
    await attach_upload_batch_file(batch_id=batch_id, file_id=102, tenant_id=1)
    scheduled: list[tuple[int, int]] = []
    await finish_parsed_file_similarity(102, schedule=lambda batch, epoch: scheduled.append((batch, epoch)))
    await reconcile_upload_batch(scheduled[-1][0], scheduled[-1][1])
    kept = await async_db_session.get(KnowledgeFile, 101)
    assert kept.similar_status == 2
    assert await _candidate_targets(async_db_session, 101) == set()
    assert await _candidate_targets(async_db_session, 102) == {101}


async def test_stale_epoch_does_not_overwrite_candidates(async_db_session, monkeypatch):
    configure(monkeypatch, enable_tfidf_refine=False)
    _bind_session(monkeypatch, async_db_session)
    async_db_session.add(Knowledge(id=1, name="space", type=3, user_id=11, tenant_id=1))
    await async_db_session.commit()
    await seed(async_db_session, 101, tenant_id=1)
    await seed(async_db_session, 102, tenant_id=1)
    batch_id = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    await attach_upload_batch_file(batch_id=batch_id, file_id=101, tenant_id=1)
    await attach_upload_batch_file(batch_id=batch_id, file_id=102, tenant_id=1)
    batch = await async_db_session.get(KnowledgeUploadBatch, batch_id)
    batch.revision = 6
    async_db_session.add(batch)
    await async_db_session.commit()
    service = _build_svc(async_db_session)
    await service.refresh_similar_candidates_for_file(101, batch_epoch=(batch_id, 6))
    assert await _candidate_targets(async_db_session, 101) == {102}
    with pytest.raises(UploadBatchEpochStale):
        await service.refresh_similar_candidates_for_file(101, batch_epoch=(batch_id, 5))
    assert await _candidate_targets(async_db_session, 101) == {102}


async def test_separate_confirmations_do_not_rescore_the_earlier_file(async_db_session, monkeypatch):
    configure(monkeypatch, enable_tfidf_refine=False)
    _bind_session(monkeypatch, async_db_session)
    async_db_session.add(Knowledge(id=1, name="space", type=3, user_id=11, tenant_id=1))
    await async_db_session.commit()
    await seed(async_db_session, 101, tenant_id=1)
    await seed(async_db_session, 102, tenant_id=1)
    first = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    second = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_B)
    await attach_upload_batch_file(batch_id=first, file_id=101, tenant_id=1)
    await attach_upload_batch_file(batch_id=second, file_id=102, tenant_id=1)
    scheduled: list[tuple[int, int]] = []
    await finish_parsed_file_similarity(102, schedule=lambda batch, epoch: scheduled.append((batch, epoch)))
    await reconcile_upload_batch(scheduled[-1][0], scheduled[-1][1])
    assert await _candidate_targets(async_db_session, 101) == set()
    assert await _candidate_targets(async_db_session, 102) == {101}


async def test_different_company_is_not_a_candidate(async_db_session, monkeypatch):
    configure(monkeypatch, enable_tfidf_refine=False)
    _bind_session(monkeypatch, async_db_session)
    async_db_session.add(Knowledge(id=1, name="space", type=3, user_id=11, tenant_id=1))
    await async_db_session.commit()
    await seed(async_db_session, 101, tenant_id=1)
    await seed(async_db_session, 102, tenant_id=1, encoding="OT-ZD-SC-20261000000001")
    batch_id = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    await attach_upload_batch_file(batch_id=batch_id, file_id=101, tenant_id=1)
    await attach_upload_batch_file(batch_id=batch_id, file_id=102, tenant_id=1)
    scheduled: list[tuple[int, int]] = []
    await finish_parsed_file_similarity(102, schedule=lambda batch, epoch: scheduled.append((batch, epoch)))
    await reconcile_upload_batch(scheduled[-1][0], scheduled[-1][1])
    assert 102 not in await _candidate_targets(async_db_session, 101)
    assert 101 not in await _candidate_targets(async_db_session, 102)


async def test_similarity_failure_keeps_parse_success(async_db_session, monkeypatch):
    _bind_session(monkeypatch, async_db_session)
    async_db_session.add(Knowledge(id=1, name="space", type=3, user_id=11, tenant_id=1))
    await async_db_session.commit()
    ready = await seed(async_db_session, 101, tenant_id=1)
    batch_id = await prepare_upload_batch(tenant_id=1, knowledge_id=1, user_id=11, upload_batch_key=KEY_A)
    await attach_upload_batch_file(batch_id=batch_id, file_id=101, tenant_id=1)

    async def explode(*_args, **_kwargs):
        raise RuntimeError("similarity down")

    monkeypatch.setattr(batch_service, "_refresh_file", explode)
    scheduled: list[tuple[int, int]] = []
    await finish_parsed_file_similarity(101, schedule=lambda batch, epoch: scheduled.append((batch, epoch)))
    current = await async_db_session.get(KnowledgeFile, ready.id)
    assert current.status == KnowledgeFileStatus.SUCCESS.value
    assert scheduled == [(batch_id, 1)]


def test_parse_hook_swallows_similarity_errors():
    def explode(_factory):
        raise RuntimeError("similarity down")

    run_similarity_after_parse(101, runner=explode)


def test_publish_refresh_does_not_reference_upload_batch():
    import inspect

    source = inspect.getsource(KnowledgeBackgroundRepositoryImpl.request_similarity_refresh)
    assert "upload_batch" not in source
    assert "reconcile_upload_batch" not in source
