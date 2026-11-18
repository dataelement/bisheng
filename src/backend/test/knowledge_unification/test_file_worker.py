"""T067: actual native source admission and txt loader/transform pipeline.

Real SQL/model/R2 and real parsing/splitting run. Only storage, optional
configuration/summary and vector/provider transports are isolated.
"""

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import Session

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.application import model_reference_read
from bisheng.knowledge.application.file_processing_adapter import (
    resolve_file_processing_snapshot,
    system_processing_defaults,
)
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models import knowledge_file as file_model
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag import knowledge_file_pipeline as pipeline
from bisheng.knowledge.rag.pipeline.transformer import (
    abstract,
    extra_file,
    file_encoding,
    image_upload,
    preview_cache,
    thumbnail,
)
from bisheng.sensitive_word.domain.schemas import SensitiveWordCheckResult, SensitiveWordHit
from bisheng.worker import tenant_context as workers
from bisheng.worker.knowledge import file_worker as module
from bisheng.worker.knowledge import rebuild_knowledge_worker as rebuild
from test.knowledge_unification import test_job_service as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application


def source_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
async def files(application, monkeypatch, tmp_path):
    context = application.context
    backend = Path(__file__).resolve().parents[2]
    # Root conftest replaces this class before pipeline import. Load its real
    # source in isolation; metadata formatting and image paths stay actual.
    import bisheng.common.services.base as base

    real_base = source_module("_processing_real_base", backend / "bisheng/common/services/base.py")
    monkeypatch.setattr(base, "BaseService", real_base.BaseService)
    real_utils = source_module(
        "_processing_real_utils", backend / "bisheng/knowledge/domain/services/knowledge_utils.py"
    ).KnowledgeUtils
    for dependent in (pipeline, abstract, image_upload, preview_cache):
        monkeypatch.setattr(dependent, "KnowledgeUtils", real_utils)
    monkeypatch.setattr(real_utils, "get_knowledge_abstract_llm", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(
        file_encoding,
        "bisheng_settings",
        SimpleNamespace(aget_shougang_conf=AsyncMock(return_value=SimpleNamespace(enabled=False))),
    )
    monkeypatch.setattr(pipeline.SensitiveWordPolicyService, "is_effective", lambda **kwargs: False)
    monkeypatch.setattr(pipeline.UserDao, "get_user", lambda ident: SimpleNamespace(user_name="operator"))
    storage = Mock()
    for dependent in (extra_file, image_upload, thumbnail):
        monkeypatch.setattr(dependent, "get_minio_storage_sync", lambda: storage)
    source = tmp_path / "source.txt"
    source.write_text("alpha beta gamma delta epsilon zeta eta theta", encoding="utf-8")
    monkeypatch.setattr(pipeline, "download_minio_file", lambda **kwargs: (str(source), None))
    async with context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.index_name, root.collection_name = "idx40", "col40"
        for ident in (81, 82):
            row = await session.get(KnowledgeFile, ident)
            row.file_name = f"source-{ident}.txt"
            row.object_name = f"source/{ident}.txt"
        await session.commit()
    runtime = await fixtures.fixtures.module.get_knowledge_model_read_runtime()
    monkeypatch.setattr(model_reference_read, "_runtime", runtime)

    @contextmanager
    def sessions():
        with Session(context.sync, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(rebuild, "get_sync_db_session", sessions)
    monkeypatch.setattr(file_model, "get_sync_db_session", sessions)
    vector = SimpleNamespace(col=Mock(), add_documents=Mock())
    es = SimpleNamespace(client=Mock(), add_documents=Mock())
    es.client.indices.exists.return_value = True
    monkeypatch.setattr(KnowledgeRag, "init_milvus_vectorstore", Mock(return_value=vector))
    monkeypatch.setattr(KnowledgeRag, "init_es_vectorstore_sync", Mock(return_value=es))
    provider = Mock(return_value=Mock())
    monkeypatch.setattr("bisheng.llm.domain.LLMService.get_bisheng_knowledge_embedding_sync", provider)
    sender = SimpleNamespace(
        name="bisheng.worker.knowledge.processing_jobs.execute_processing_job",
        request=SimpleNamespace(id="actual-file-processing", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    workers.restore_tenant_context(sender=sender)
    effective = resolve_file_processing_snapshot(
        file_name="source.txt",
        file_source="space_upload",
        system_defaults=system_processing_defaults(40),
        space_defaults=None,
        space_config_version=0,
        batch_overrides={
            "document": {
                "split_mode": "custom",
                "chunk_size": 12,
                "chunk_overlap": 0,
                "separator": [" "],
                "separator_rule": ["after"],
            }
        },
    )
    try:
        yield SimpleNamespace(
            context=context, vector=vector, es=es, provider=provider, source=source, effective=effective, sender=sender
        )
    finally:
        workers.reset_tenant_context(sender=sender)


def prepare(files, kind="file_resplit"):
    return module.prepare_processing_file(
        81,
        space_id=40,
        invoke_user_id=7,
        kind=kind,
        processing_snapshot={
            "schema_version": 1,
            "mode": kind,
            "original_status": 2,
            "effective_processing": files.effective.model_dump(mode="json"),
            "source_revision": "a" * 64,
        },
        expected_model_config_revision=0,
        expected_index_generation="g0",
    )


def write(files, prepared):
    return module.write_processing_file(
        prepared, space_id=40, invoke_user_id=7, expected_model_config_revision=0, expected_index_generation="g0"
    )


@pytest.mark.parametrize("kind", ["file_reprocess", "file_resplit"])
async def test_actual_prepare_and_write_only_selected_file_and_no_hidden_sql_commit(files, kind):
    prepared = prepare(files, kind)
    assert len(prepared.documents) > 1
    files.provider.assert_not_called()
    files.vector.add_documents.assert_not_called()
    result = write(files, prepared)
    assert result.succeeded and result.chunk_count == len(prepared.documents) and result.file_id == 81
    assert {doc.metadata["document_id"] for doc in files.vector.add_documents.call_args.args[0]} == {81}
    files.vector.col.drop.assert_not_called()
    assert "81" in files.vector.col.delete.call_args.args[0] and "82" not in files.vector.col.delete.call_args.args[0]
    async with files.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).split_rule == '{"original":"kept"}'
        assert (await session.get(KnowledgeFile, 81)).status == 2
        assert (await session.get(KnowledgeFile, 82)).status == 2


async def test_current_configuration_change_rejects_before_new_provider_or_index_io(files):
    prepared = prepare(files)
    async with files.context.sessions() as session:
        (await session.get(Knowledge, 40)).model_config_revision += 1
        await session.commit()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        write(files, prepared)
    files.provider.assert_not_called()
    files.vector.col.delete.assert_not_called()


async def test_missing_model_never_uses_prepared_or_snapshot_model(files):
    prepared = prepare(files)
    async with files.context.sessions() as session:
        (await session.get(Knowledge, 40)).model = None
        await session.commit()
    with pytest.raises((ResourceReferenceInvalidError, ReferenceCoverageNotReadyError)):
        write(files, prepared)
    files.provider.assert_not_called()


async def test_actual_source_replacement_rejects_prepared_documents(files):
    prepared = prepare(files)
    async with files.context.sessions() as session:
        (await session.get(KnowledgeFile, 81)).object_name = "replacement/81.txt"
        await session.commit()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        write(files, prepared)
    files.provider.assert_not_called()
    files.vector.col.delete.assert_not_called()


def test_store_failure_returns_actual_failure_and_cleans_only_selected_file(files):
    prepared = prepare(files)
    files.es.add_documents.side_effect = RuntimeError("ES write failed")
    result = write(files, prepared)
    assert result.status == 3 and not result.succeeded and result.chunk_count == len(prepared.documents)
    assert files.vector.col.delete.call_count == 2
    files.vector.col.drop.assert_not_called()


def test_empty_parse_is_real_failed_outcome_without_store_write(files):
    files.source.write_text("", encoding="utf-8")
    result = write(files, prepare(files))
    assert not result.succeeded and result.status == 3 and result.chunk_count == 0
    files.provider.assert_not_called()


def test_real_safety_transformer_has_distinct_violation_outcome(files, monkeypatch):
    monkeypatch.setattr(pipeline.SensitiveWordPolicyService, "is_effective", lambda **kwargs: True)
    result = SensitiveWordCheckResult(enabled=True, hits=[SensitiveWordHit(word="alpha", count=1)])
    monkeypatch.setattr(pipeline.SensitiveWordPolicyService, "check_text", lambda **kwargs: result)
    outcome = write(files, prepare(files))
    assert outcome.status == 7 and not outcome.succeeded
    files.provider.assert_not_called()


def test_missing_worker_proof_rejects_before_actual_parse(files):
    workers.reset_tenant_context(sender=files.sender)
    with pytest.raises(ResourceReferenceInvalidError):
        prepare(files)
