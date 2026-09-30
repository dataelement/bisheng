"""自动发布等待下游、终止诊断及恢复结案的持久化契约。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_background_job import KnowledgeBackgroundJob as Job
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.auto_publish_service import AutoPublishService
from test.knowledge.test_background_jobs import build_service


@pytest.fixture
async def projection_job(async_db_engine, monkeypatch):
    from bisheng.knowledge.rag import shared_space_storage

    monkeypatch.setattr(
        shared_space_storage, "get_shared_storage_conf", lambda: SimpleNamespace(projection_max_retries=4)
    )
    service = await build_service(monkeypatch, async_db_engine)
    publish = AsyncMock(side_effect=AssertionError("不能重复发布"))
    monkeypatch.setattr(AutoPublishService, "execute", publish)
    async with AsyncSession(async_db_engine) as session:
        session.add_all(
            [
                KnowledgeFile(
                    id=i,
                    tenant_id=7,
                    knowledge_id=i,
                    file_name="文件.pdf",
                    status=2,
                    reference_document_id=91,
                    entry_type="manager" if i == 100 else "publish",
                    entry_status="active",
                    projection_status="ready" if i == 100 else "failed",
                    desired_content_generation=4,
                    applied_content_generation=4,
                    desired_entry_generation=1,
                    applied_entry_generation=1,
                    projection_retry_count=1,
                    projection_last_error=None if i == 100 else "ObjectDereferencedError: parse_type",
                )
                for i in (100, 101)
            ]
        )
        await session.commit()
    job_id = await service.repository_call(
        "request",
        tenant_id=7,
        kind="auto_publish",
        identity="source100",
        payload={"file_id": 100, "projection_ids": [100, 101]},
    )
    return service, job_id, publish


async def test_retryable_projection_wait_preserves_budget_and_deadline(async_db_engine, projection_job):
    service, job_id, publish = projection_job
    deadline = None
    for _ in range(9):
        assert await service.process(job_id, 7) == "waiting"
        async with AsyncSession(async_db_engine) as session:
            job = await session.get(Job, job_id)
            assert job.attempts == 0
            deadline = deadline or job.payload["wait_deadline"]
            assert job.payload["wait_deadline"] == deadline
            job.next_retry_at = None
            await session.commit()
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(Job, job_id)
        job.payload = {**job.payload, "wait_deadline": (datetime.now() - timedelta(seconds=1)).isoformat()}
        await session.commit()
    assert await service.process(job_id, 7) == "dead"
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(Job, job_id)
        assert "projection_wait_expired" in job.last_error
        assert job.payload["projection_failure"]["entries"][1]["file_id"] == 101
    publish.assert_not_awaited()


@pytest.mark.parametrize(
    "reason,retry_count",
    [
        ("retry_exhausted:ObjectDereferencedError: parse_type", 1),
        ("RuntimeError:document_content_rebuild_budget_exhausted", 1),
        ("ObjectDereferencedError: parse_type", 4),
    ],
)
async def test_terminal_projection_records_details_and_recovers_without_republishing(
    async_db_engine,
    projection_job,
    reason,
    retry_count,
):
    service, job_id, publish = projection_job
    async with AsyncSession(async_db_engine) as session:
        row = await session.get(KnowledgeFile, 101)
        row.projection_last_error = reason
        row.projection_retry_count = retry_count
        await session.commit()
    assert await service.process(job_id, 7) == "dead"
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(Job, job_id)
        attempts = job.attempts
        detail = job.payload["projection_failure"]["entries"][1]
        assert detail["file_id"] == 101 and detail["document_id"] == 91
        assert detail["error"] == reason
        assert "101" in job.last_error and "91" in job.last_error
    # 未恢复时仅限频核验，不重置预算或产生任务。
    assert await service.drain() == {}
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(Job, job_id)
        assert job.status == "dead" and job.attempts == attempts
        assert job.next_retry_at > datetime.now()
        row = await session.get(KnowledgeFile, 101)
        row.projection_status = "ready"
        row.projection_last_error = None
        job.next_retry_at = None
        await session.commit()
    assert await service.drain() == {}
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(Job, job_id)
        assert job.status == "done" and job.attempts == attempts
        assert job.last_error is None
        assert job.payload["projection_failure"]["entries"][1]["error"] == reason
    publish.assert_not_awaited()


@pytest.mark.parametrize("invalid", ["generation", "deleted", "tenant", "document", "missing", None])
async def test_legacy_dead_job_requires_all_original_projections_verified(async_db_engine, projection_job, invalid):
    service, job_id, _ = projection_job
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(Job, job_id)
        job.status, job.attempts, job.last_error = "dead", 8, "RuntimeError:published_projection_failed"
        row = await session.get(KnowledgeFile, 101)
        row.projection_status = "ready"
        if invalid == "generation":
            row.applied_content_generation = 3
        elif invalid == "deleted":
            row.deleted_at = datetime.now()
        elif invalid == "tenant":
            row.tenant_id = 8
        elif invalid == "document":
            row.reference_document_id = 92
        elif invalid == "missing":
            await session.delete(row)
        await session.commit()
    assert await service.drain() == {}
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(Job, job_id)
        assert job.status == ("dead" if invalid else "done") and job.attempts == 8


async def test_recovery_is_bounded_and_does_not_revive_other_failures(async_db_engine, projection_job):
    service, first_id, publish = projection_job
    second_id = await service.repository_call(
        "request",
        tenant_id=7,
        kind="auto_publish",
        identity="second",
        payload={"file_id": 100, "projection_ids": [100, 101]},
    )
    other_id = await service.repository_call(
        "request",
        tenant_id=7,
        kind="auto_publish",
        identity="other",
        payload={"file_id": 100, "projection_ids": [100, 101]},
    )
    async with AsyncSession(async_db_engine) as session:
        (await session.get(KnowledgeFile, 101)).projection_status = "ready"
        for job_id in (first_id, second_id, other_id):
            job = await session.get(Job, job_id)
            job.status, job.attempts = "dead", 8
            job.last_error = (
                "RuntimeError:published_projection_failed" if job_id != other_id else "RuntimeError:FGA unavailable"
            )
        await session.commit()
    for expected_count in (1, 2):
        assert await service.drain(limit=1) == {}
        async with AsyncSession(async_db_engine) as session:
            jobs = [await session.get(Job, job_id) for job_id in (first_id, second_id, other_id)]
            assert sum(job.status == "done" for job in jobs) == expected_count
            assert jobs[2].status == "dead"
            assert all(job.attempts == 8 for job in jobs)
            for job in jobs:
                if job.status == "done":
                    assert (
                        job.payload["projection_recovery"]["previous_error"]
                        == "RuntimeError:published_projection_failed"
                    )
    publish.assert_not_awaited()
