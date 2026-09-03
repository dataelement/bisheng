from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.api.services import knowledge_imp
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.rag.pipeline.types import PipelineStage


def _space(*, knowledge_type: int = KnowledgeTypeEnum.SPACE.value):
    return SimpleNamespace(
        id=3,
        tenant_id=1,
        type=knowledge_type,
        model="7",
        collection_name="col_legacy_3",
        index_name="idx_legacy_3",
    )


def _file():
    return SimpleNamespace(
        id=41,
        tenant_id=1,
        user_id=7,
        updater_id=7,
        knowledge_id=3,
        file_name="document.pdf",
        file_type=FileType.FILE.value,
        object_name="source/document.pdf",
        parse_type=None,
        status=KnowledgeFileStatus.PROCESSING.value,
        remark="",
        simhash=None,
        similar_status=0,
    )


def _install_common_fakes(monkeypatch, *, routed: bool):
    from bisheng.api.services import workstation as workstation_api
    from bisheng.worker.knowledge import file_worker

    space = _space()
    pipeline_calls = []

    class FakePipeline:
        def __init__(self, **kwargs):
            pipeline_calls.append(kwargs)

        def run(self, config=None):
            if routed:
                assert config is not None
                assert config.stop_at is PipelineStage.TRANSFORMER
            return SimpleNamespace(
                documents=[
                    Document(
                        page_content="hello",
                        metadata={"chunk_index": 0, "document_name": "document.pdf"},
                    )
                ]
            )

    monkeypatch.setattr(
        knowledge_imp.KnowledgeDao,
        "query_by_id",
        staticmethod(lambda _knowledge_id: space),
    )
    monkeypatch.setattr(knowledge_imp, "KnowledgeFilePipeline", FakePipeline)
    monkeypatch.setattr(
        knowledge_imp,
        "persist_parse_result_with_fulltext_intent",
        lambda _file: None,
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeSpaceContentStat,
        "enqueue_file_stat_sync",
        staticmethod(lambda _file_ids: None),
    )
    monkeypatch.setattr(
        knowledge_imp.telemetry_service,
        "log_event_sync",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeSpaceAutoTagService,
        "generate_recommended_tags_after_parse",
        classmethod(lambda cls, **_kwargs: None),
    )
    monkeypatch.setattr(
        workstation_api.WorkStationService,
        "query_knowledge_space_config_with_meta",
        lambda: (
            SimpleNamespace(auto_tag_visible=False, review_tag_visible=False),
            False,
            1,
            False,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        file_worker.refresh_file_similarity_candidates_celery,
        "apply_async",
        lambda **_kwargs: None,
    )
    return space, pipeline_calls


def test_routed_parse_writes_directly_without_initializing_legacy_stores(monkeypatch):
    from bisheng.knowledge.domain.services.shared_space_direct_ingestion_service import (
        SharedSpaceDirectIngestionService,
    )

    _, pipeline_calls = _install_common_fakes(monkeypatch, routed=True)
    direct_ingest = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.rag.shared_space_storage.resolve_space_shared_routing",
        lambda *_args, **_kwargs: SimpleNamespace(routing_version=3),
    )
    monkeypatch.setattr(
        SharedSpaceDirectIngestionService,
        "ingest_documents_sync",
        direct_ingest,
    )
    legacy_milvus = MagicMock()
    legacy_es = MagicMock()
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag,
        "init_knowledge_milvus_vectorstore_sync",
        legacy_milvus,
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag,
        "init_knowledge_es_vectorstore_sync",
        legacy_es,
    )

    file_record = _file()
    knowledge_imp.addEmbedding(3, [file_record])

    assert file_record.status == KnowledgeFileStatus.SUCCESS.value
    assert pipeline_calls[0]["vector_store"] == []
    direct_ingest.assert_called_once()
    legacy_milvus.assert_not_called()
    legacy_es.assert_not_called()


def test_routed_parse_failure_does_not_fallback_to_legacy_stores(monkeypatch):
    from bisheng.knowledge.domain.services.shared_space_direct_ingestion_service import (
        SharedSpaceDirectIngestionService,
    )

    _install_common_fakes(monkeypatch, routed=True)
    monkeypatch.setattr(
        "bisheng.knowledge.rag.shared_space_storage.resolve_space_shared_routing",
        lambda *_args, **_kwargs: SimpleNamespace(routing_version=3),
    )
    monkeypatch.setattr(
        SharedSpaceDirectIngestionService,
        "ingest_documents_sync",
        MagicMock(side_effect=RuntimeError("shared write failed")),
    )
    legacy_milvus = MagicMock()
    legacy_es = MagicMock()
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag,
        "init_knowledge_milvus_vectorstore_sync",
        legacy_milvus,
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag,
        "init_knowledge_es_vectorstore_sync",
        legacy_es,
    )

    file_record = _file()
    knowledge_imp.addEmbedding(3, [file_record])

    assert file_record.status == KnowledgeFileStatus.FAILED.value
    legacy_milvus.assert_not_called()
    legacy_es.assert_not_called()


@pytest.mark.parametrize(
    "knowledge_type",
    [KnowledgeTypeEnum.SPACE.value, KnowledgeTypeEnum.NORMAL.value],
    ids=["space-not-routed", "non-space"],
)
def test_non_shared_routes_keep_legacy_ingestion(monkeypatch, knowledge_type):
    space, pipeline_calls = _install_common_fakes(monkeypatch, routed=False)
    space.type = knowledge_type
    monkeypatch.setattr(
        "bisheng.knowledge.rag.shared_space_storage.resolve_space_shared_routing",
        lambda *_args, **_kwargs: None,
    )
    milvus_store = object()
    es_store = object()
    legacy_milvus = MagicMock(return_value=milvus_store)
    legacy_es = MagicMock(return_value=es_store)
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag,
        "init_knowledge_milvus_vectorstore_sync",
        legacy_milvus,
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag,
        "init_knowledge_es_vectorstore_sync",
        legacy_es,
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeUtils,
        "ensure_milvus_schema_ready",
        staticmethod(lambda **kwargs: kwargs["vector_client"]),
    )

    file_record = _file()
    knowledge_imp.addEmbedding(3, [file_record])

    assert file_record.status == KnowledgeFileStatus.SUCCESS.value
    assert pipeline_calls[0]["vector_store"] == [milvus_store, es_store]
    legacy_milvus.assert_called_once()
    legacy_es.assert_called_once()


def test_direct_ingestion_embeds_and_writes_content_before_membership(monkeypatch):
    from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
        SharedContentIngestionTarget,
    )
    from bisheng.knowledge.domain.services.shared_space_direct_ingestion_service import (
        SharedSpaceDirectIngestionService,
    )
    from bisheng.knowledge.rag.shared_space_storage import TenantRoutingSnapshot

    target = SharedContentIngestionTarget(
        tenant_id=1,
        canonical_document_id=81,
        canonical_version_id=91,
        content_file_id=41,
        content_generation=2,
        membership_generation=3,
        knowledge_ids=(3, 4),
    )
    routing = TenantRoutingSnapshot(
        tenant_id=1,
        shared_enabled=True,
        routing_version=3,
        write_frozen=False,
        collection_name="col_space_shared_1",
        index_name="idx_space_shared_1",
        embedding_model_id=7,
        schema_fingerprint="fp",
        migration_state="",
    )
    embeddings = SimpleNamespace(embed_documents=MagicMock(return_value=[[0.1, 0.2]]))
    writer = SimpleNamespace(
        upsert_content=AsyncMock(),
        update_membership=AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.shared_space_direct_ingestion_service."
        "LLMService.get_bisheng_knowledge_embedding_sync",
        lambda **_kwargs: embeddings,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.shared_space_direct_ingestion_service."
        "build_shared_space_components_for_tenant",
        lambda *_args, **_kwargs: (writer, object()),
    )
    monkeypatch.setattr(
        SharedSpaceDirectIngestionService,
        "_prepare_target",
        AsyncMock(return_value=target),
    )
    finalize = AsyncMock()
    monkeypatch.setattr(
        SharedSpaceDirectIngestionService,
        "_finalize_target",
        finalize,
    )

    SharedSpaceDirectIngestionService.ingest_documents_sync(
        knowledge=_space(),
        file_record=_file(),
        documents=[
            Document(
                page_content="hello",
                metadata={"chunk_index": 0, "tenant_id": 1},
            )
        ],
        routing=routing,
    )

    request = writer.upsert_content.await_args.args[0]
    assert request.identity.canonical_document_id == 81
    assert request.knowledge_ids == (3, 4)
    assert request.chunks[0].vector == [0.1, 0.2]
    assert "tenant_id" not in request.chunks[0].metadata
    membership = writer.update_membership.await_args.args[0]
    assert membership.membership_generation == 3
    finalize.assert_awaited_once_with(target=target)


async def test_prepare_shared_ingestion_reuses_unapplied_generation():
    from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
        KnowledgeDocumentDistributionService,
    )

    source_file = SimpleNamespace(
        id=41,
        tenant_id=1,
        status=KnowledgeFileStatus.PROCESSING.value,
        knowledge_id=3,
        reference_document_id=None,
        entry_type=None,
        entry_status=None,
        desired_content_generation=0,
        applied_content_generation=0,
        desired_entry_generation=0,
        applied_entry_generation=0,
        projection_status="pending",
        projection_retry_count=0,
        projection_next_retry_at=None,
        projection_lease_owner=None,
        projection_lease_until=None,
        projection_last_error=None,
    )
    document = SimpleNamespace(id=81, content_generation=0)
    version = SimpleNamespace(id=91, document_id=81)
    session = MagicMock()
    session.flush = AsyncMock()
    file_repository = MagicMock()
    file_repository.mark_document_entries_content_generation = AsyncMock()
    file_repository.find_distribution_entries_by_document_id = AsyncMock(
        side_effect=lambda *_args, **_kwargs: [source_file]
    )
    version_repository = MagicMock()
    version_repository.find_by_knowledge_file_id = AsyncMock(return_value=version)
    service = KnowledgeDocumentDistributionService(
        session=session,
        document_repository=MagicMock(),
        version_repository=version_repository,
        file_repository=file_repository,
        permission_activation_service=MagicMock(),
    )
    service._load_or_create_primary_document = AsyncMock(return_value=(source_file, document))
    service._commit = AsyncMock()

    first = await service.prepare_shared_content_ingestion(
        tenant_id=1,
        source_file_id=41,
    )
    second = await service.prepare_shared_content_ingestion(
        tenant_id=1,
        source_file_id=41,
    )

    assert first.content_generation == 1
    assert second.content_generation == 1
    assert document.content_generation == 1
    file_repository.mark_document_entries_content_generation.assert_awaited_once()


async def test_normal_projection_worker_does_not_attach_legacy_chunk_loader(
    monkeypatch,
):
    import importlib
    import sys
    from pathlib import Path

    from bisheng.knowledge.domain.services import (
        shared_space_projection_support,
    )

    backend_root = Path(__file__).resolve().parents[2]
    sys.modules["bisheng.worker"].__path__ = [str(backend_root / "bisheng/worker")]
    sys.modules["bisheng.worker.knowledge"].__path__ = [str(backend_root / "bisheng/worker/knowledge")]
    document_projection = importlib.import_module("bisheng.worker.knowledge.document_projection")

    writer = SimpleNamespace(schema_spec=SimpleNamespace(embedding_model_id=7))
    monkeypatch.setattr(
        shared_space_projection_support,
        "resolve_shared_space_storage_enabled",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        document_projection,
        "shared_storage_writer_factory",
        lambda **_kwargs: writer,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.rag.shared_space_storage.get_shared_storage_conf",
        lambda: SimpleNamespace(projection_max_retries=8),
    )

    service = await document_projection._build_document_projection_service(
        MagicMock(),
        file_repository=MagicMock(),
        document_repository=MagicMock(),
        version_repository=MagicMock(),
        tenant_id=1,
    )

    assert service.shared_storage_enabled is True
    assert service.shared_content_chunk_loader is None
