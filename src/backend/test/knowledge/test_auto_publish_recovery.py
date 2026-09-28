"""自动发布中断后沿用原任务和原发布参数恢复。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_background_job import KnowledgeBackgroundJob as Job
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum, KnowledgeSpaceScopeDao
from bisheng.knowledge.domain.services.auto_publish_config_service import AutoPublishConfigService
from bisheng.knowledge.domain.services.auto_publish_service import AutoPublishService
from bisheng.knowledge.domain.services.auto_publish_target_resolver import AutoPublishTarget, AutoPublishTargetResolver
from test.knowledge.test_background_jobs import build_service
from test.knowledge.test_knowledge_document_distribution_publish import _seed_manager, _service


async def test_interrupted_publish_resumes_original_context_without_reactivating_manager(async_db_engine, monkeypatch):
    from bisheng.core import database
    from bisheng.knowledge.domain import constants
    from bisheng.knowledge.domain.services import knowledge_document_distribution_service as distribution

    service = await build_service(monkeypatch, async_db_engine)

    @asynccontextmanager
    async def factory():
        async with AsyncSession(async_db_engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(database, "get_async_db_session", factory)
    async with factory() as session:
        await _seed_manager(session)

    async def load(file_id):
        async with factory() as session:
            return await session.get(KnowledgeFile, file_id)

    monkeypatch.setattr(KnowledgeFileDao, "query_by_id", load)
    monkeypatch.setattr(
        KnowledgeSpaceScopeDao,
        "aget_by_space_id",
        AsyncMock(return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.DEPARTMENT)),
    )
    monkeypatch.setattr(constants, "get_file_category_code_from_split_rule", lambda _: "POL")
    monkeypatch.setattr(AutoPublishConfigService, "get_enabled_rules", AsyncMock(return_value=[]))
    monkeypatch.setattr(AutoPublishConfigService, "match_rule", lambda *a, **kw: SimpleNamespace(target_space_id=20))
    monkeypatch.setattr(AutoPublishTargetResolver, "resolve_target_space_id", AsyncMock(return_value=20))
    monkeypatch.setattr(
        AutoPublishTargetResolver,
        "resolve_or_create_target_folder",
        AsyncMock(return_value=AutoPublishTarget(20, None, 0, "")),
    )

    fail_permissions = True
    job_id = await service.repository_call(
        "request", tenant_id=7, kind="auto_publish", identity="source100", payload={"file_id": 100}
    )

    async def tuples(operations):
        # 首次权限操作前必须已持久化完整目标，且 manager 仍不可见。
        async with factory() as session:
            job = await session.get(Job, job_id)
            assert job.payload["publish_context"]["target_space_id"] == 20
            assert (await session.get(KnowledgeFile, 100)).entry_status == "preparing"
        if fail_permissions:
            raise RuntimeError("FGA unavailable")

    real_class = distribution.KnowledgeDocumentDistributionService
    monkeypatch.setattr(
        distribution, "KnowledgeDocumentDistributionService", lambda **kw: _service(kw["session"], tuple_writer=tuples)
    )
    assert await service.process(job_id, 7) == "pending"
    async with factory() as session:
        job = await session.get(Job, job_id)
        assert job.attempts == 1
        assert job.payload["publish_context"]["approval_instance_id"] == -1000020
        assert (await session.get(KnowledgeFile, 100)).entry_status == "preparing"
        job.next_retry_at = None
        await session.commit()

    fail_permissions = False
    monkeypatch.setattr(
        real_class, "normalize_manager", AsyncMock(side_effect=AssertionError("must not reactivate manager"))
    )
    monkeypatch.setattr(
        AutoPublishConfigService,
        "get_enabled_rules",
        AsyncMock(side_effect=AssertionError("must not resolve a new target")),
    )

    # 激活后的旧权限清理允许 manager 为 active。
    async def recovered_tuples(operations):
        if any(operation.action == "write" for operation in operations):
            async with factory() as session:
                assert (await session.get(KnowledgeFile, 100)).entry_status == "preparing"

    monkeypatch.setattr(
        distribution,
        "KnowledgeDocumentDistributionService",
        lambda **kw: _service(kw["session"], tuple_writer=recovered_tuples),
    )
    assert await service.process(job_id, 7) == "waiting"
    async with factory() as session:
        job = await session.get(Job, job_id)
        assert job.attempts == 1
        entries = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.reference_document_id == 91))).all()
        assert len([entry for entry in entries if entry.entry_type == "publish"]) == 1
        for entry in entries:
            assert entry.entry_status == "active"
            entry.projection_status = "ready"
        job.next_retry_at = None
        await session.commit()
    assert await service.process(job_id, 7) == "done"


async def test_preparing_without_context_is_not_normalized_or_retargeted(monkeypatch):
    file = KnowledgeFile(
        id=1391,
        tenant_id=1,
        knowledge_id=10,
        file_name="旧文件",
        status=2,
        entry_type="manager",
        entry_status="preparing",
        reference_document_id=9,
        approval_instance_id=-13910134,
    )
    monkeypatch.setattr(KnowledgeFileDao, "query_by_id", AsyncMock(return_value=file))
    scope = AsyncMock(side_effect=AssertionError("must not infer recovery target"))
    monkeypatch.setattr(KnowledgeSpaceScopeDao, "aget_by_space_id", scope)
    with pytest.raises(RuntimeError, match="auto_publish_recovery_context_missing"):
        await AutoPublishService.execute(file_id=1391, tenant_id=1)
    assert file.entry_status == "preparing"
    scope.assert_not_awaited()


@pytest.mark.parametrize("change", [{"tenant_id": 8}, {"document_id": 92}, {"target_space_id": 21}])
async def test_resume_rejects_mismatched_context(async_db_engine, monkeypatch, change):
    from dataclasses import asdict
    from bisheng.core import database
    from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
        KnowledgeDocumentDistributionService,
        PublishKnowledgeDocumentCommand,
    )

    @asynccontextmanager
    async def factory():
        async with AsyncSession(async_db_engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(database, "get_async_db_session", factory)
    async with factory() as session:
        await _seed_manager(session)
        file = await session.get(KnowledgeFile, 100)
        file.entry_status = "preparing"
        file.approval_instance_id = -1000020
        await session.commit()
    monkeypatch.setattr(KnowledgeFileDao, "query_by_id", AsyncMock(return_value=file))
    publish = AsyncMock()
    monkeypatch.setattr(KnowledgeDocumentDistributionService, "publish_approved", publish)
    context = asdict(
        PublishKnowledgeDocumentCommand(
            tenant_id=7,
            document_id=91,
            source_entry_id=100,
            approval_instance_id=-1000020,
            target_space_id=20,
        )
    )
    context.update(change)
    with pytest.raises(RuntimeError, match="auto_publish_recovery_context_mismatch"):
        await AutoPublishService.execute(file_id=100, tenant_id=7, publish_context=context)
    publish.assert_not_awaited()
    async with factory() as session:
        assert (await session.get(KnowledgeFile, 100)).entry_status == "preparing"
