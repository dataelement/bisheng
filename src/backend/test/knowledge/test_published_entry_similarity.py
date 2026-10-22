from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_background_job import KnowledgeBackgroundJob
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from test.knowledge.test_file_similarity_metadata_modes import configure, seed
from test.knowledge.test_knowledge_version_service_similar_scan import _build_svc


async def setup_entries(session, monkeypatch):
    configure(monkeypatch, enable_tfidf_refine=False)
    session.add_all([Knowledge(id=i, tenant_id=1, name=f"s{i}", type=3, user_id=1) for i in (1, 2, 3)])
    await session.commit()
    for file_id, space_id in ((10, 1), (20, 2)):
        manager = await seed(session, file_id, space_id, tenant_id=1)
        version = (
            await session.exec(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == file_id)
            )
        ).one()
        manager.reference_document_id = version.document_id
        manager.entry_type, manager.entry_status, manager.projection_status = "manager", "active", "ready"
        session.add(manager)
        session.add(
            KnowledgeFile(
                id=file_id + 100,
                tenant_id=1,
                knowledge_id=3,
                file_name=f"published{file_id}.pdf",
                status=2,
                entry_type="publish",
                entry_status="active",
                projection_status="ready",
                reference_document_id=version.document_id,
                simhash=None,
            )
        )
    await session.commit()
    return _build_svc(session)


async def test_second_publish_detects_existing_entry_and_checks_entry_permission(async_db_session, monkeypatch):
    svc = await setup_entries(async_db_session, monkeypatch)
    allowed = AsyncMock(return_value=True)
    result = await svc.get_shougang_publish_similar_candidates_for_file_in_space(20, 3, can_view_file=allowed)
    assert [item.primary_knowledge_file_id for item in result] == [110]
    assert result[0].can_associate is False
    assert result[0].content_file_id == 10
    assert {call.args[0] for call in allowed.await_args_list} == {110}
    allowed.return_value = False
    assert await svc.get_shougang_publish_similar_candidates_for_file_in_space(20, 3, can_view_file=allowed) == []


async def test_target_library_cache_badge_and_withdrawal(async_db_session, monkeypatch):
    svc = await setup_entries(async_db_session, monkeypatch)
    assert await svc.refresh_similar_candidates_for_file(120) == 1
    result = await svc.get_similar_candidates_for_file(120)
    assert [item.primary_knowledge_file_id for item in result] == [110]
    assert result[0].can_associate is False
    assert await svc.similar_candidate_repo.find_actionable_source_file_ids([120]) == {120}
    entry = await async_db_session.get(KnowledgeFile, 110)
    entry.entry_status = "deleting"
    async_db_session.add(entry)
    await async_db_session.commit()
    assert await svc.get_similar_candidates_for_file(120) == []
    assert await svc.similar_candidate_repo.find_actionable_source_file_ids([120]) == set()


async def test_refinement_reads_current_content_through_target_membership(async_db_session, monkeypatch):
    from types import SimpleNamespace

    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

    svc = await setup_entries(async_db_session, monkeypatch)
    configure(monkeypatch, enable_tfidf_refine=True)
    monkeypatch.setattr(
        KnowledgeDao, "aquery_by_id", AsyncMock(side_effect=lambda i: SimpleNamespace(id=i, tenant_id=1, type=3))
    )
    svc._fetch_chunk_texts = AsyncMock(side_effect=lambda space, ids: dict.fromkeys(ids, "相同正文"))
    svc._tokenize_files_cached = AsyncMock(side_effect=lambda items: [["相同正文"] for _ in items])
    result = await svc.get_shougang_publish_similar_candidates_for_file_in_space(20, 3)
    assert [item.primary_knowledge_file_id for item in result] == [110]
    assert {(call.args[0].id, tuple(call.args[1])) for call in svc._fetch_chunk_texts.await_args_list} == {
        (2, (20,)),
        (3, (10,)),
    }


async def test_current_primary_change_invalidates_cached_fingerprint(async_db_session, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument

    svc = await setup_entries(async_db_session, monkeypatch)
    assert await svc.refresh_similar_candidates_for_file(120) == 1
    source_version = await svc.version_repo.find_by_knowledge_file_id(10)
    document = await async_db_session.get(KnowledgeDocument, source_version.document_id)
    source_version.is_primary = False
    body = KnowledgeFile(
        id=30,
        tenant_id=1,
        knowledge_id=1,
        file_name="new.pdf",
        status=2,
        file_encoding="GF-ZD-SC-20261000000003",
        file_subcategory_code="A",
        simhash="aaaaaaaaaaaaaaaa",
    )
    version = KnowledgeDocumentVersion(document_id=document.id, knowledge_file_id=30, is_primary=True, version_no=2)
    async_db_session.add_all([body, version, source_version])
    await async_db_session.flush()
    document.primary_version_id = version.id
    document.content_generation = 1
    entry = await async_db_session.get(KnowledgeFile, 110)
    entry.applied_content_generation = entry.desired_content_generation = 1
    async_db_session.add_all([document, entry])
    await async_db_session.commit()
    assert await svc.get_similar_candidates_for_file(120) == []
    assert await svc.refresh_similar_candidates_for_file(120) == 1
    result = await svc.get_similar_candidates_for_file(120)
    assert result[0].content_file_id == 30
    assert result[0].current_primary_version_no == 2


async def test_candidate_changes_during_score_are_recalculated(async_db_session, monkeypatch):
    svc = await setup_entries(async_db_session, monkeypatch)
    score = svc._score_similarity_candidates
    calls = 0

    async def change_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = await score(*args, **kwargs)
        if calls == 1:
            file = await async_db_session.get(KnowledgeFile, 10)
            file.simhash = "5555555555555555"
            async_db_session.add(file)
            await async_db_session.commit()
        return result

    monkeypatch.setattr(svc, "_score_similarity_candidates", change_once)
    assert await svc.refresh_similar_candidates_for_file(120) == 0
    assert calls == 2


async def test_library_view_denial_keeps_global_pending_state(async_db_session, monkeypatch):
    from types import SimpleNamespace

    svc = await setup_entries(async_db_session, monkeypatch)
    await svc.refresh_similar_candidates_for_file(120)

    async def resolve(**kwargs):
        return SimpleNamespace(capabilities=SimpleNamespace(can_view=kwargs["file_id"] != 110))

    svc.document_entry_resolver = SimpleNamespace(resolve=resolve)
    assert await svc.get_similar_candidates_for_file(120) == []
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    monkeypatch.setattr(
        KnowledgeFileDao,
        "aget_files_by_similar_status",
        AsyncMock(return_value=[await async_db_session.get(KnowledgeFile, 120)]),
    )
    assert await svc.list_pending_similar_files(3) == []
    assert (await async_db_session.get(KnowledgeFile, 120)).similar_status == 1


@pytest.mark.parametrize("state", ["preparing", "deleting", "share", "pending", "different_tenant"])
async def test_inactive_or_unrelated_entry_is_not_recommended(async_db_session, monkeypatch, state):
    svc = await setup_entries(async_db_session, monkeypatch)
    entry = await async_db_session.get(KnowledgeFile, 110)
    if state in {"preparing", "deleting"}:
        entry.entry_status = state
    elif state == "share":
        entry.entry_type = state
    elif state == "pending":
        entry.projection_status = state
    else:
        entry.tenant_id = 2
    async_db_session.add(entry)
    await async_db_session.commit()
    assert await svc.get_shougang_publish_similar_candidates_for_file_in_space(20, 3) == []


async def test_existing_legal_publish_version_target_remains_available(async_db_session, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument

    svc = await setup_entries(async_db_session, monkeypatch)
    file = await async_db_session.get(KnowledgeFile, 10)
    document = await async_db_session.get(KnowledgeDocument, file.reference_document_id)
    file.knowledge_id = document.knowledge_id = 3
    await async_db_session.delete(await async_db_session.get(KnowledgeFile, 110))
    async_db_session.add_all([file, document])
    await async_db_session.commit()
    result = await svc.get_shougang_publish_similar_candidates_for_file_in_space(20, 3)
    assert [item.primary_knowledge_file_id for item in result] == [10]
    assert result[0].can_associate


async def test_ready_and_refresh_intent_rollback_together(async_db_session):
    entry = KnowledgeFile(
        id=90,
        tenant_id=1,
        knowledge_id=3,
        file_name="ready.pdf",
        status=2,
        entry_type="manager",
        entry_status="active",
        reference_document_id=8,
        projection_status="processing",
        projection_lease_owner="worker",
        desired_content_generation=2,
        desired_entry_generation=3,
    )
    async_db_session.add(entry)
    await async_db_session.commit()
    await KnowledgeFileRepositoryImpl(async_db_session).apply_projection_result(
        entry_id=90, lease_owner="worker", target_content_generation=2, target_entry_generation=3
    )
    await async_db_session.rollback()
    assert (await async_db_session.get(KnowledgeFile, 90)).projection_status == "processing"
    assert (await async_db_session.exec(select(KnowledgeBackgroundJob))).all() == []


async def test_durable_worker_retries_and_preserves_dismissal(async_db_engine, monkeypatch):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.common.services.config_service import settings
    from bisheng.core.config.settings import KnowledgeConf
    from bisheng.knowledge.domain.services import knowledge_similarity_entry_service as module
    from test.knowledge.test_background_jobs import build_service

    service = await build_service(monkeypatch, async_db_engine)
    monkeypatch.setattr(
        settings,
        "async_get_knowledge",
        AsyncMock(return_value=KnowledgeConf(version_management={"enabled": True, "enable_tfidf_refine": False})),
    )
    async with AsyncSession(async_db_engine, expire_on_commit=False) as session:
        await setup_entries(session, monkeypatch)
        entry = await session.get(KnowledgeFile, 120)
        job_id = await service.repository_call("request_similarity_refresh", entry)
    run = module.refresh_published_similarity
    attempts = 0

    async def flaky(session, payload):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("storage unavailable")
        return await run(session, payload)

    monkeypatch.setattr(module, "refresh_published_similarity", flaky)
    assert await service.process(job_id, 1) == "pending"
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(KnowledgeBackgroundJob, job_id)
        job.next_retry_at = None
        session.add(job)
        await session.commit()
    assert await service.process(job_id, 1) == "done"
    assert await service.process(job_id, 1) == "not_due"
    async with AsyncSession(async_db_engine) as session:
        entry = await session.get(KnowledgeFile, 120)
        assert entry.similar_status == 1
        entry.similar_status = 2
        entry.desired_entry_generation = entry.applied_entry_generation = 1
        session.add(entry)
        await session.commit()
        next_id = await service.repository_call("request_similarity_refresh", entry)
    assert await service.process(next_id, 1) == "done"
    async with AsyncSession(async_db_engine) as session:
        assert (await session.get(KnowledgeFile, 120)).similar_status == 2


@pytest.mark.parametrize("kind", ["manager", "publish"])
async def test_projection_completion_requests_one_durable_refresh(async_db_session, kind):
    entry = KnowledgeFile(
        id=90,
        tenant_id=1,
        knowledge_id=3,
        file_name="ready.pdf",
        status=2,
        entry_type=kind,
        entry_status="active",
        reference_document_id=8,
        projection_status="processing",
        projection_lease_owner="worker",
        desired_content_generation=2,
        desired_entry_generation=3,
    )
    async_db_session.add(entry)
    await async_db_session.commit()
    repo = KnowledgeFileRepositoryImpl(async_db_session)
    assert await repo.apply_projection_result(
        entry_id=90, lease_owner="worker", target_content_generation=2, target_entry_generation=3
    )
    await async_db_session.commit()
    jobs = (
        await async_db_session.exec(
            select(KnowledgeBackgroundJob).where(KnowledgeBackgroundJob.kind == "refresh_similarity")
        )
    ).all()
    assert len(jobs) == 1
    assert jobs[0].payload["file_id"] == 90
    assert not await repo.apply_projection_result(
        entry_id=90, lease_owner="worker", target_content_generation=2, target_entry_generation=3
    )
    assert len((await async_db_session.exec(select(KnowledgeBackgroundJob))).all()) == 1
