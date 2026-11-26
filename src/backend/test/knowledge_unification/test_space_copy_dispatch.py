"""Actual copy task connects durable inputs, per-file failure, retry and source release."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import sqlalchemy as sa

from bisheng.core.context.background_execution import get_current_background_task
from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
from bisheng.knowledge.domain.schemas.processing_job import ProcessingRetryRequest
from bisheng.worker.knowledge.space_copy_jobs import execute_copy_job
from test.knowledge_unification import test_kn_copy as native
from test.knowledge_unification import test_kn_copy_index as transports
from test.knowledge_unification.test_kn_copy import (
    actual_processing_task as actual_processing_task,
)
from test.knowledge_unification.test_kn_copy import (
    admission as admission,
)
from test.knowledge_unification.test_kn_copy import (
    application as application,
)
from test.knowledge_unification.test_kn_copy import (
    business as business,
)
from test.knowledge_unification.test_kn_copy import command
from test.knowledge_unification.test_kn_copy import (
    job_tenant as job_tenant,
)
from test.knowledge_unification.test_kn_copy import (
    processing as processing,
)
from test.knowledge_unification.test_kn_copy import (
    store as store,
)
from test.knowledge_unification.test_kn_copy import (
    tenant as tenant,
)
from test.knowledge_unification.test_metadata_index_worker import response
from test.knowledge_unification.test_move_worker import NativeIterator

native_copy = native.copying
adapter = transports.copying


async def test_native_copy_worker_records_inputs_and_retries_without_live_source(
    native_copy, adapter, monkeypatch, actual_processing_task
):
    from bisheng.knowledge.domain.repositories import space_copy_repository

    monkeypatch.setattr(
        space_copy_repository,
        "KnowledgeUtils",
        SimpleNamespace(get_knowledge_file_object_name=lambda ident, name: f"original/{ident}.txt"),
    )
    ctx = native_copy.ctx
    async with ctx.sessions() as session, session.begin():
        root = await session.get(Knowledge, 40)
        root.index_name, root.collection_name = "source", "source"
        file = await session.get(KnowledgeFile, 81)
        file.object_name = "original/81.txt"
    plan = await native_copy.app.aprecheck(40, name="Actual background files", identity=ctx.user)
    result = await native_copy.app.aconfirm(40, command(plan), identity=ctx.user)
    owner, jid = SpaceCopyOwner(native_copy.app), result["processing_job"].job_id

    async def search(es, *, index, body=None, query=None, size=1000, **kwargs):
        wanted = (body or {"query": query})["query"]["term"]["metadata.document_id"]
        hits = [row for row in es.rows if row["_source"]["metadata"]["document_id"] == wanted]
        cursor = f"{es.name}-{len(es.cursors)}"
        es.cursors[cursor] = (hits, size)
        return response(
            {
                "_scroll_id": cursor,
                "_shards": {"failed": 0},
                "timed_out": False,
                "hits": {"total": {"value": len(hits), "relation": "eq"}, "hits": hits[:size]},
            }
        )

    async def delete_es(*, index, body=None, query=None, refresh):
        wanted = (body or {"query": query})["query"]["term"]["metadata.document_id"]
        old = len(adapter.new.rows)
        adapter.new.rows = [row for row in adapter.new.rows if row["_source"]["metadata"]["document_id"] != wanted]
        count = old - len(adapter.new.rows)
        return response({"total": count, "deleted": count, "version_conflicts": 0, "timed_out": False, "failures": []})

    def delete_mv(expr):
        wanted = int(expr.rsplit(" ", 1)[-1])
        adapter.col.rows = [row for row in adapter.col.rows if row["document_id"] != wanted]
        return SimpleNamespace(delete_count=0)

    def iterate(*, batch_size, limit, expr, output_fields):
        wanted = int(expr.rsplit(" ", 1)[-1])
        return NativeIterator([row for row in adapter.col.rows if row["document_id"] == wanted], adapter.col.events)

    monkeypatch.setattr(adapter.old, "search", lambda **kwargs: search(adapter.old, **kwargs))
    monkeypatch.setattr(adapter.new, "search", lambda **kwargs: search(adapter.new, **kwargs))
    monkeypatch.setattr(adapter.new, "delete_by_query", delete_es)
    monkeypatch.setattr(adapter.col, "delete", delete_mv)
    monkeypatch.setattr(adapter.col, "query_iterator", iterate)
    # One file's target embedding fails after its input was saved; its sibling
    # still finishes and the space remains usable.
    from bisheng.worker.knowledge import space_copy_worker

    vector = SimpleNamespace(
        col=adapter.col,
        embedding_func=SimpleNamespace(aembed_documents=AsyncMock(side_effect=RuntimeError("provider down"))),
    )
    monkeypatch.setattr(
        space_copy_worker.KnowledgeRag, "init_knowledge_milvus_vectorstore", AsyncMock(return_value=vector)
    )
    proof = get_current_background_task()
    assert (await execute_copy_job(jid, 0, proof=proof, owner=owner))["state"] == "partial_failed"
    async with ctx.sessions() as session:
        items = (await session.execute(sa.select(Item).where(Item.job_id == jid))).scalars().all()
        assert all(item.step in {"copy_input_ready", "copy_completed"} for item in items)
        assert all("copy_input" in item.checkpoint for item in items)
        assert (await session.get(Knowledge, result["knowledge"].id)).state == 1
        await SourceMoveInputRepository().arequire_released(session, space_id=40)
    async with ctx.sessions() as session, session.begin():
        await session.execute(
            sa.delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == 40, KnowledgeFile.tenant_id == 101)
        )
        await session.execute(sa.delete(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101))
    adapter.old.rows.clear()
    for key in tuple(adapter.objects.values):
        if key in {"original/81.txt", "preview/81.md", "knowledge/images/40/81/same.png"}:
            del adapter.objects.values[key]
    failed, _ = await owner.aread(jid)
    await owner.aretry(
        jid,
        ProcessingRetryRequest(idempotency_key="stored-only", expected_job_revision=failed.revision),
        identity=ctx.user,
    )
    current, _ = await owner.aread(jid)
    vector.embedding_func.aembed_documents.side_effect = lambda texts: [[0.1, 0.2] for _ in texts]
    assert (await execute_copy_job(jid, current.revision, proof=proof, owner=owner))["state"] == "succeeded"
