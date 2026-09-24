from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from unittest.mock import AsyncMock

from sqlalchemy import create_engine
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_background_job import KnowledgeBackgroundJob as Job
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.repositories.implementations.knowledge_background_repository_impl import (
    KnowledgeBackgroundRepositoryImpl as Repository,
)
from bisheng.knowledge.domain.services.knowledge_background_service import KnowledgeBackgroundService
from bisheng.knowledge.domain.services.knowledge_fulltext_parse_hook import persist_parse_result_with_fulltext_intent


def test_parse_success_and_publish_intent_commit_together(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (KnowledgeFile, KnowledgeFulltextOutbox, Job):
        model.__table__.create(engine)

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    file = KnowledgeFile(
        id=1, tenant_id=1, knowledge_id=1, file_type=1, file_name="文件", status=2, file_subcategory_code="POL-A"
    )
    persist_parse_result_with_fulltext_intent(file, session_factory=factory, multi_tenant_enabled=False)
    with Session(engine) as session:
        row = session.exec(select(Job)).one()
        assert row.kind == "auto_publish" and row.status == "pending"
        assert session.get(KnowledgeFile, 1).status == 2
        assert Repository(session).request_auto_publish(session.get(KnowledgeFile, 1)) == row.id
        session.commit()
        assert len(session.exec(select(Job)).all()) == 1
    engine.dispose()


def test_lease_and_failure_budget_survive_repeated_delivery():
    engine = create_engine("sqlite://")
    Job.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as session:
        repo = Repository(session)
        job_id = repo.request(tenant_id=1, kind="auto_publish", identity="1", payload={"file_id": 1})
        session.commit()
        for attempt in range(8):
            row = session.get(Job, job_id)
            row.next_retry_at = None
            session.commit()
            claimed = repo.claim(job_id, str(attempt), datetime.now())
            session.commit()
            assert claimed.attempts == attempt + 1
            assert repo.claim(job_id, "duplicate", datetime.now()) is None
            assert not repo.settle(job_id, "wrong", status="done", payload={})
            assert repo.settle(job_id, str(attempt), status="pending", payload=claimed.payload, error="unavailable")
            session.commit()
        row.next_retry_at = None
        session.commit()
        assert repo.claim(job_id, "extra", datetime.now()) is None
        session.commit()
        assert session.get(Job, job_id, populate_existing=True).status == "dead"
        assert repo.request(tenant_id=1, kind="auto_publish", identity="1", payload={}) == job_id
        assert session.get(Job, job_id).attempts == 8
    engine.dispose()


async def build_service(monkeypatch, engine):
    import importlib

    module = importlib.import_module("bisheng.knowledge.domain.services.knowledge_background_service")

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(module, "get_async_db_session", factory)
    return KnowledgeBackgroundService()


async def test_publish_wait_does_not_publish_again(async_db_engine, monkeypatch):
    service = await build_service(monkeypatch, async_db_engine)
    from bisheng.knowledge.domain.services.auto_publish_service import AutoPublishResult, AutoPublishService

    execute = AsyncMock(return_value=AutoPublishResult(published=True, manager_file_id=1, publish_entry_id=2))
    monkeypatch.setattr(AutoPublishService, "execute", execute)
    async with AsyncSession(async_db_engine) as session:
        session.add_all(
            [
                KnowledgeFile(
                    id=i,
                    knowledge_id=1,
                    tenant_id=1,
                    file_name="文件",
                    status=2,
                    entry_type="manager" if i == 1 else "publish",
                    entry_status="active",
                    projection_status="pending",
                )
                for i in (1, 2)
            ]
        )
        await session.commit()
    job_id = await service.repository_call(
        "request", tenant_id=1, kind="auto_publish", identity="file1", payload={"file_id": 1}
    )
    assert await service.process(job_id, 1) == "waiting"
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(Job, job_id)
        assert job.payload["projection_ids"] == [1, 2]
        job.next_retry_at = None
        for file_id in (1, 2):
            (await session.get(KnowledgeFile, file_id)).projection_status = "ready"
        await session.commit()
    assert await service.process(job_id, 1) == "done"
    execute.assert_awaited_once()


async def test_container_cursor_advances_past_failed_items_without_input_cap(async_db_engine, monkeypatch):
    service = await build_service(monkeypatch, async_db_engine)
    now = datetime.now().replace(microsecond=0)
    async with AsyncSession(async_db_engine) as session:
        folder = KnowledgeFile(id=1, knowledge_id=1, tenant_id=1, file_type=0, file_name="目录", deleted_at=now)
        session.add(folder)
        session.add_all(
            [
                KnowledgeFile(
                    id=i,
                    knowledge_id=1,
                    tenant_id=1,
                    file_name="引用",
                    file_level_path="None/1",
                    reference_document_id=i,
                    entry_type="share",
                    entry_status="active",
                )
                for i in range(2, 1003)
            ]
        )
        await session.commit()
        job_id = await session.run_sync(lambda sync: Repository(sync).request_container(folder, now))
        await session.commit()
    for _ in range(11):
        assert await service.process(job_id, 1) == "waiting"
        async with AsyncSession(async_db_engine) as session:
            job = await session.get(Job, job_id)
            job.next_retry_at = None
            assert job.attempts == 0
            await session.commit()
    async with AsyncSession(async_db_engine) as session:
        parent = await session.get(Job, job_id)
        children = list((await session.exec(select(Job).where(Job.parent_id == job_id))).all())
        assert len(children) == 1001
        assert parent.payload["cursor"] == 1002 and parent.payload["enumerated"]

    async def item(job, owner, payload):
        if payload["entry_id"] == 2:
            raise RuntimeError("bad entry")
        return "done"

    service._container_entry = item
    bad = next(child for child in children if child.payload["entry_id"] == 2)
    good = next(child for child in children if child.payload["entry_id"] == 3)
    assert await service.process(bad.id, 1) == "pending"
    assert await service.process(good.id, 1) == "done"


async def test_delete_failure_keeps_objects_and_resumes_only_unfinished_stage(async_db_engine, monkeypatch):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    service = await build_service(monkeypatch, async_db_engine)
    knowledge_imp = importlib.import_module("bisheng.api.services.knowledge_imp")
    monkeypatch.setattr(
        knowledge_imp, "_knowledge_file_owned_object_names", lambda file: {"original/file.pdf"}, raising=False
    )
    monkeypatch.setattr(knowledge_imp, "_artifact_owned_object_name", lambda artifact: None, raising=False)
    vector = SimpleNamespace(col=MagicMock())
    es = MagicMock()
    es.indices.exists.return_value = True
    es.delete_by_query.side_effect = [{"failures": [{"reason": "unavailable"}]}, {"failures": []}]
    monkeypatch.setattr(KnowledgeRag, "init_knowledge_milvus_vectorstore_sync", lambda *a, **kw: vector)
    monkeypatch.setattr(KnowledgeRag, "init_knowledge_es_vectorstore_sync", lambda **kw: SimpleNamespace(client=es))
    storage = SimpleNamespace(bucket="files", remove_object=AsyncMock())
    minio = importlib.import_module("bisheng.core.storage.minio.minio_manager")
    monkeypatch.setattr(minio, "get_minio_storage", AsyncMock(return_value=storage))
    original = service.repository_call

    async def repository(method, *args, **kwargs):
        if method == "object_is_referenced":
            return False
        return await original(method, *args, **kwargs)

    service.repository_call = repository
    job_ids = await service.repository_call(
        "request_delete",
        tenant_id=1,
        knowledge=Knowledge(id=9, name="legacy", type=0, user_id=1, index_name="old-index"),
        files=[{"id": 1, "object_name": "original/file.pdf"}],
        artifacts=[],
    )
    job_id = job_ids[0]
    assert await service.process(job_id, 1) == "pending"
    storage.remove_object.assert_not_awaited()
    async with AsyncSession(async_db_engine) as session:
        job = await session.get(Job, job_id)
        assert job.payload["completed_stages"] == ["milvus"]
        job.next_retry_at = None
        await session.commit()
    assert await service.process(job_id, 1) == "done"
    assert vector.col.delete.call_count == 1
    assert es.delete_by_query.call_count == 2
    storage.remove_object.assert_awaited_once_with(bucket_name="files", object_name="original/file.pdf")


async def test_published_commit_before_checkpoint_is_recovered_without_republish(async_db_engine, monkeypatch):
    from bisheng.knowledge.domain.services.auto_publish_service import AutoPublishService

    service = await build_service(monkeypatch, async_db_engine)
    execute = AsyncMock(side_effect=AssertionError("must not republish"))
    monkeypatch.setattr(AutoPublishService, "execute", execute)
    async with AsyncSession(async_db_engine) as session:
        session.add_all(
            [
                KnowledgeFile(
                    id=10,
                    tenant_id=1,
                    knowledge_id=20,
                    file_name="管理入口",
                    status=2,
                    reference_document_id=7,
                    entry_type="manager",
                    entry_status="active",
                    projection_status="ready",
                ),
                KnowledgeFile(
                    id=11,
                    tenant_id=1,
                    knowledge_id=9,
                    file_name="发布入口",
                    status=2,
                    reference_document_id=7,
                    entry_type="publish",
                    entry_status="active",
                    projection_status="ready",
                    approval_instance_id=-(10 * 10000 + 20),
                ),
            ]
        )
        await session.commit()
    job_id = await service.repository_call(
        "request", tenant_id=1, kind="auto_publish", identity="10", payload={"file_id": 10}
    )
    assert await service.process(job_id, 1) == "done"
    execute.assert_not_awaited()


def test_manual_restore_only_changes_terminal_records_and_retains_progress():
    from bisheng.knowledge.domain.repositories.implementations.background_task_maintenance_repository_impl import (
        BackgroundTaskMaintenanceRepositoryImpl,
    )

    engine = create_engine("sqlite://")
    Job.__table__.create(engine)
    with Session(engine) as session:
        session.add(
            Job(
                id="a",
                tenant_id=1,
                kind="delete_file",
                status="dead",
                attempts=8,
                payload={"completed_stages": ["es"], "wait_deadline": "old"},
            )
        )
        session.add(Job(id="b", tenant_id=1, kind="delete_file", status="processing", attempts=1))
        session.commit()
        repository = BackgroundTaskMaintenanceRepositoryImpl(session)
        assert repository.inspect_or_restore("background", ["a"])[0]["status"] == "dead"
        repository.inspect_or_restore("background", ["a", "b"], restore=True)
        session.commit()
        assert session.get(Job, "a").status == "pending"
        assert session.get(Job, "a").payload == {"completed_stages": ["es"]}
        assert session.get(Job, "b").status == "processing"
    engine.dispose()


def test_nested_folder_delivery_reuses_same_deletion_root():
    engine = create_engine("sqlite://")
    for model in (KnowledgeFile, Job):
        model.__table__.create(engine)
    now = datetime.now()
    with Session(engine) as session:
        root = KnowledgeFile(
            id=10, tenant_id=1, knowledge_id=1, file_type=0, file_name="根目录", file_level_path="", deleted_at=now
        )
        child = KnowledgeFile(
            id=11, tenant_id=1, knowledge_id=1, file_type=0, file_name="子目录", file_level_path="/10", deleted_at=now
        )
        session.add_all([root, child])
        session.commit()
        repo = Repository(session)
        assert repo.request_container(child, now) == repo.request_container(root, now)
        session.commit()
        assert session.exec(select(Job)).one().payload["folder_id"] == 10
    engine.dispose()
