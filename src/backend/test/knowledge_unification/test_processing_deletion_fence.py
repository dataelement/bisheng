"""Real SQL/pipeline cancellation; only storage and search transports isolated."""

from unittest.mock import Mock

import pytest
from sqlalchemy import delete, select
from sqlmodel import Session

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_fence import KnowledgeProcessingArtifact
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.knowledge.domain.repositories.processing_fence_repository import (
    ProcessingCancelled,
    ProcessingFenceRepository,
)
from bisheng.knowledge.domain.services.processing_write_guard import ProcessingWriteGuard
from bisheng.knowledge.rag.pipeline.base import NormalPipeline
from test.knowledge_unification import test_file_worker as native

store, tenant, business, admission, processing, application, files = (
    native.store,
    native.tenant,
    native.business,
    native.admission,
    native.processing,
    native.application,
    native.files,
)


def mark_deleted(files, operation="knowledge_file_delete", state="PENDING", tenant_id=101):
    with Session(files.context.sync) as session:
        session.add(
            KnowledgeSpaceDeleteJob(
                tenant_id=tenant_id,
                space_id=40,
                applicant_user_id=7,
                operation_type=operation,
                manifest={"file_ids": [81]},
                state=state,
            )
        )
        session.commit()


async def test_prepared_result_never_ingested_after_delete_or_redelivery(files):
    prepared = native.prepare(files)
    mark_deleted(files)
    for _ in range(2):
        with pytest.raises(ProcessingCancelled):
            native.write(files, prepared)
    files.vector.add_documents.assert_not_called()
    files.es.add_documents.assert_not_called()
    files.provider.assert_not_called()


async def test_cancel_after_loader_stops_transform_and_vector_io(files):
    loader, transformer, vector = Mock(), Mock(), Mock()
    loader.load.side_effect = lambda: (mark_deleted(files), [])[1]
    with pytest.raises(ProcessingCancelled):
        NormalPipeline(
            loader=loader,
            transformers=[transformer],
            vector_store=[vector],
            processing_guard=ProcessingWriteGuard(40, 81),
        ).run()
    transformer.transform_documents.assert_not_called()
    vector.add_documents.assert_not_called()


async def test_stale_success_cannot_update_or_recreate_deleted_file(files):
    with Session(files.context.sync) as session:
        stale = session.get(KnowledgeFile, 81)
        session.expunge(stale)
    mark_deleted(files)
    with pytest.raises(ProcessingCancelled):
        ProcessingFenceRepository().persist_file(stale)
    with Session(files.context.sync) as session:
        session.execute(delete(KnowledgeFile).where(KnowledgeFile.id == 81, KnowledgeFile.tenant_id == 101))
        session.commit()
    with pytest.raises(ProcessingCancelled):
        ProcessingFenceRepository().persist_file(stale)
    with Session(files.context.sync) as session:
        assert session.get(KnowledgeFile, 81) is None


async def test_upload_inventory_survives_failure_without_file_patch(files):
    storage = Mock()
    storage.put_object_sync.side_effect = RuntimeError("lost upload response")
    guard = ProcessingWriteGuard(40, 81)
    with pytest.raises(RuntimeError, match="lost upload response"):
        guard.upload(storage, object_name="thumbnails/generated-before-crash.jpg", file=b"image")
    with Session(files.context.sync) as session:
        assert session.execute(select(KnowledgeProcessingArtifact.object_name)).scalars().all() == [
            "thumbnails/generated-before-crash.jpg"
        ]
        assert session.get(KnowledgeFile, 81).thumbnails is None
    mark_deleted(files)
    with pytest.raises(ProcessingCancelled):
        guard.upload(storage, object_name="late-object", file=b"late")
    assert storage.put_object_sync.call_count == 1


async def test_file_delete_preserves_other_file_and_other_tenant_work(files):
    mark_deleted(files, tenant_id=202)
    ProcessingWriteGuard(40, 81).checkpoint()
    mark_deleted(files)
    ProcessingWriteGuard(40, 82).checkpoint()
    ProcessingWriteGuard(40).checkpoint()


async def test_completed_clear_allows_new_work_but_missing_space_never_does(files):
    mark_deleted(files, operation="knowledge_space_clear", state="SUCCEEDED")
    ProcessingWriteGuard(40, 82).checkpoint()
    with Session(files.context.sync) as session:
        session.execute(delete(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101))
        session.commit()
    for file_id in (0, 81, 82):
        with pytest.raises(ProcessingCancelled):
            ProcessingWriteGuard(40, file_id).checkpoint()


async def test_durable_minio_purge_removes_output_not_saved_on_file_row(files, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.core.storage.minio import minio_manager
    from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
        KnowledgeSpaceDirectDeleteService,
    )

    guard = ProcessingWriteGuard(40, 81)
    guard.upload(Mock(), object_name="generated-orphan", file=b"image")
    storage = Mock(bucket="files")
    storage.remove_object = AsyncMock()
    storage.object_exists = AsyncMock(return_value=False)
    monkeypatch.setattr(minio_manager, "get_minio_storage", AsyncMock(return_value=storage))
    service = KnowledgeSpaceDirectDeleteService(
        session_factory=files.context.sessions, repository=Mock(advance=AsyncMock())
    )
    job = KnowledgeSpaceDeleteJob(
        tenant_id=101,
        space_id=40,
        applicant_user_id=7,
        operation_type="knowledge_file_delete",
        manifest={"file_ids": [81], "object_names": []},
    )
    await service._purge_step("minio", job)
    await service._purge_step("minio", job)  # crash/retry remains idempotent
    assert storage.remove_object.await_count == 2
    storage.remove_object.assert_awaited_with(bucket_name="files", object_name="generated-orphan")


async def test_clear_verification_never_matches_later_uploaded_documents(files, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
    from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
        KnowledgeSpaceDirectDeleteService,
    )

    files.es.client.delete_by_query.return_value = {"failures": []}
    files.es.client.count.return_value = {"count": 0}
    files.vector.col.query.return_value = [{"count(*)": 0}]
    monkeypatch.setattr(KnowledgeRag, "init_knowledge_es_cleanup_sync", Mock(return_value=files.es))
    monkeypatch.setattr(KnowledgeRag, "init_knowledge_milvus_cleanup_sync", Mock(return_value=files.vector))
    service = KnowledgeSpaceDirectDeleteService(repository=Mock(renew_verification=AsyncMock()))
    job = KnowledgeSpaceDeleteJob(
        tenant_id=101,
        space_id=40,
        applicant_user_id=7,
        operation_type="knowledge_space_clear",
        state="SUCCEEDED",
        manifest={
            "file_ids": [81],
            "knowledge": {
                "id": 40,
                "tenant_id": 101,
                "name": "space",
                "type": 3,
                "index_name": "idx40",
                "collection_name": "col40",
            },
        },
    )
    await service._purge_step("es", job, verification=True)
    await service._purge_step("milvus", job, verification=True)
    assert files.es.client.delete_by_query.call_args.kwargs["query"] == {"terms": {"metadata.document_id": [81]}}
    assert files.vector.col.delete.call_args.kwargs["expr"] == "document_id in [81]"


@pytest.fixture
def legacy_processing_module(monkeypatch):
    import importlib.util
    from pathlib import Path

    source = Path(__file__).parents[2] / "bisheng/api/services/knowledge_imp.py"
    spec = importlib.util.spec_from_file_location("knowledge_imp_deletion_under_test", source)
    actual = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(actual)
    return actual


async def test_legacy_envelope_does_not_turn_cancellation_into_a_failure_merge(
    files, legacy_processing_module, monkeypatch
):
    module = legacy_processing_module
    monkeypatch.setattr(module, "addEmbedding", Mock(side_effect=ProcessingCancelled("deleted")))
    lookup = Mock(side_effect=AssertionError("cancelled work cannot enter failure persistence"))
    monkeypatch.setattr(module.KnowledgeFileDao, "select_list", lookup)
    with pytest.raises(ProcessingCancelled):
        module.process_file_task(Knowledge(id=40, type=3), [])
    lookup.assert_not_called()


async def test_legacy_envelope_missing_file_keeps_original_error_without_recreation(
    files, legacy_processing_module, monkeypatch
):
    module = legacy_processing_module
    failure = RuntimeError("parse response lost")
    monkeypatch.setattr(module, "addEmbedding", Mock(side_effect=failure))
    monkeypatch.setattr(module.KnowledgeFileDao, "select_list", Mock(return_value=[]))
    update = Mock(side_effect=AssertionError("deleted row cannot be merged back"))
    monkeypatch.setattr(module.KnowledgeFileDao, "update", update)
    with pytest.raises(RuntimeError, match="parse response lost"):
        module.process_file_task(Knowledge(id=40, type=3), [KnowledgeFile(id=81, knowledge_id=40)])
    update.assert_not_called()
