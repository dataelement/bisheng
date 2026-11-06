"""Named deletion cleanup uses current owned identity or the persisted lease plan.

覆盖 AC: AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
Real Knowledge/delete-job SQL; external vector transports are doubles.
"""

import asyncio
from contextlib import contextmanager
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain import knowledge_rag as module
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob, deletion_now
from bisheng.llm.domain.models.llm_server import LLMModel
from test.knowledge_unification import test_kn_rag_model_admission as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
rag = fixtures.rag


@pytest.fixture
async def cleanup(rag, monkeypatch):
    context, _ = rag
    KnowledgeSpaceDeleteJob.__table__.create(context.sync)
    names = tenant_filter._tenant_aware_tables | {KnowledgeSpaceDeleteJob.__tablename__}
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)

    @contextmanager
    def sessions():
        with Session(context.sync) as session:
            yield session

    monkeypatch.setattr(module, "get_sync_db_session", sessions, raising=False)
    actual = Knowledge(
        id=40,
        tenant_id=101,
        name="source",
        type=3,
        model="11",
        index_name="actual_index",
        collection_name="actual_collection",
    )
    historical = Knowledge(
        id=40,
        tenant_id=101,
        name="source",
        type=3,
        model="404",
        index_name="historical_index",
        collection_name="historical_collection",
    )
    job = KnowledgeSpaceDeleteJob(
        tenant_id=101,
        space_id=40,
        applicant_user_id=7,
        manifest={
            "knowledge": historical.model_dump(
                include={"id", "tenant_id", "name", "type", "model", "index_name", "collection_name"}
            ),
            "file_ids": [1],
        },
        state="RUNNING",
        lease_token="current-lease",
        attempts=1,
        lease_until=deletion_now() + timedelta(minutes=10),
    )
    async with context.sessions() as session:
        session.add(job)
        await session.commit()
    return context, actual, historical, job


async def test_deleted_model_does_not_prevent_named_management_cleanup(cleanup):
    context, actual, _, _ = cleanup
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
    await asyncio.to_thread(KnowledgeRag.init_knowledge_milvus_cleanup_sync, knowledge=actual)
    await asyncio.to_thread(KnowledgeRag.init_knowledge_es_cleanup_sync, knowledge=actual)
    assert module.MilvusFactory.init_vectorstore.call_args.args[0] == "actual_collection"
    assert module.ElasticsearchFactory.init_vectorstore_sync.call_args.args[0] == "actual_index"
    module.LLMService.get_bisheng_knowledge_embedding_sync.assert_not_called()


async def test_current_persisted_job_can_clean_its_old_index_after_resource_disappears(cleanup):
    context, _, historical, job = cleanup
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101))
    await asyncio.to_thread(KnowledgeRag.init_knowledge_milvus_cleanup_sync, knowledge=historical, deletion_job=job)
    await asyncio.to_thread(KnowledgeRag.init_knowledge_es_cleanup_sync, knowledge=historical, deletion_job=job)
    assert module.MilvusFactory.init_vectorstore.call_args.args[0] == "historical_collection"
    assert module.ElasticsearchFactory.init_vectorstore_sync.call_args.args[0] == "historical_index"


@pytest.mark.parametrize("invalid", ["fake_job", "lease", "target", "index", "tenant", "expired"])
async def test_untrusted_job_or_changed_target_never_redirects_cleanup(cleanup, invalid):
    context, actual, historical, original = cleanup
    job = original.model_copy(deep=True)
    knowledge = historical.model_copy(deep=True)
    if invalid == "fake_job":
        job.id = "not-a-persisted-job"
    elif invalid == "lease":
        job.lease_token = "superseded-lease"
    elif invalid == "target":
        job.space_id = 99
    elif invalid == "index":
        knowledge.index_name = actual.index_name
        knowledge.collection_name = actual.collection_name
    elif invalid == "tenant":
        job.tenant_id = 202
    else:
        async with context.sessions() as session, session.begin():
            await session.execute(
                sa.update(KnowledgeSpaceDeleteJob)
                .where(KnowledgeSpaceDeleteJob.id == original.id, KnowledgeSpaceDeleteJob.tenant_id == 101)
                .values(lease_until=deletion_now() - timedelta(minutes=1))
            )
    with pytest.raises(ResourceReferenceInvalidError):
        await asyncio.to_thread(KnowledgeRag.init_knowledge_milvus_cleanup_sync, knowledge=knowledge, deletion_job=job)
    module.MilvusFactory.init_vectorstore.assert_not_called()


async def test_arbitrary_current_resource_index_override_is_rejected(cleanup):
    _, actual, historical, _ = cleanup
    actual.collection_name = historical.collection_name
    with pytest.raises(ResourceReferenceInvalidError):
        await asyncio.to_thread(KnowledgeRag.init_knowledge_milvus_cleanup_sync, knowledge=actual)
    module.MilvusFactory.init_vectorstore.assert_not_called()
