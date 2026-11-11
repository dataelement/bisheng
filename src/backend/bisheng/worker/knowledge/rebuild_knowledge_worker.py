import json
from copy import deepcopy
from dataclasses import dataclass

from loguru import logger
from pymilvus import Collection

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.errcode.knowledge import (
    KnowledgeFileFailedError,
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    KnowledgeUnificationError,
    ResourceReferenceInvalidError,
)
from bisheng.core.ai import FakeEmbeddings
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.core.database import get_sync_db_session
from bisheng.core.logger import trace_id_var
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication
from bisheng.knowledge.application.model_reference_read import get_knowledge_model_read_runtime_sync
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao, KnowledgeFileStatus
from bisheng.llm.domain import LLMService
from bisheng.resource_reference.application.contracts import canonical_target_id
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(acks_late=True)
def rebuild_knowledge_celery(
    knowledge_id: int,
    new_model_id: int | None,
    invoke_user_id: int,
    *,
    operation_id: str | None = None,
    expected_model_config_revision: int | None = None,
    expected_index_generation: str | None = None,
) -> str:
    """Rebuild the current business pending slot; the user ID is audit only."""
    trace_id_var.set(f"rebuild_knowledge_{knowledge_id}")
    logger.info(f"rebuild_knowledge_celery start knowledge_id={knowledge_id} new_model_id={new_model_id}")
    try:
        command = {
            "operation_id": operation_id,
            "expected_model_config_revision": expected_model_config_revision,
            "expected_index_generation": expected_index_generation,
        }
        knowledge, selected_model_id = _require_current_rebuild(knowledge_id, new_model_id, **command)

        # 1. according knowledge_id Found knowledgefile All in the tablestatus=2Andstatus=4File, put thestatusto4
        files = KnowledgeFileDao.get_files_by_multiple_status(
            knowledge_id, [KnowledgeFileStatus.SUCCESS.value, KnowledgeFileStatus.REBUILDING.value]
        )
        # 2. According to thecollection_namewentmilvusDelete Vector Store in
        _delete_rebuild_vectors(knowledge, invoke_user_id, **command)

        if not files:
            logger.info(f"knowledge_id={knowledge_id} has no success files")
            _finalize_rebuild(knowledge_id, **command)
            return f"knowledge {knowledge_id} rebuild completed (no files)"

        # Updating file status to rebuild in progress
        file_ids = [f.id for f in files]
        KnowledgeFileDao.update_status_bulk(file_ids, KnowledgeFileStatus.REBUILDING)

        logger.info(f"Updated {len(files)} files to rebuilding status")

        # 3. accordingindex_nameFROMesGot it inchunkinformation, reembeddingInsertmilvus
        success_files, failed_files = _rebuild_embeddings(
            knowledge, files, selected_model_id, invoke_user_id, **command
        )

        # 4. Update file status
        KnowledgeFileDao.update_status_bulk(success_files, KnowledgeFileStatus.SUCCESS)

        for file_id in failed_files:
            file = next((f for f in files if f.id == file_id), None)
            if file:
                file.status = KnowledgeFileStatus.FAILED.value
                file.remark = KnowledgeFileFailedError(data={"exception": "rebuild error"}).to_json_str()
                KnowledgeFileDao.update(file)

        # 5. Release the container; the failure lives on the files that failed.
        # Marking the whole knowledge FAILED existed to drive a later automatic
        # rebuild, which no longer happens — a failed file is recovered by
        # re-parsing it. All that flag does now is take the entire knowledge
        # down: permission targets require PUBLISHED, so a single bad file made
        # the space unreachable and reported it as "invalid resource type or ID".
        if failed_files:
            # ES is the retry source, including manually edited chunks.
            logger.error(f"knowledge_id={knowledge_id} rebuild failed, failed_files={failed_files}")
        else:
            logger.info(f"knowledge_id={knowledge_id} rebuild completed successfully")

        _finalize_rebuild(knowledge_id, **command)

        return f"knowledge {knowledge_id} rebuild completed"

    except Exception as e:
        logger.exception(f"rebuild_knowledge_celery error: {e!s}")
        # Global failures did not complete the operation. Keep its actual
        # pending slot/revision and let Celery retain the failure diagnostic.
        raise


def _rebuild_rag_scope(*, operation_id, expected_model_config_revision, expected_index_generation):
    return {
        "model_slot": "model_transition.pending_model_id",
        "expected_operation_id": operation_id,
        "expected_model_config_revision": expected_model_config_revision,
        "expected_index_generation": expected_index_generation,
    }


def _require_current_rebuild(
    knowledge_id, model_hint, *, operation_id, expected_model_config_revision, expected_index_generation
):
    if get_current_background_task() is None:
        raise ResourceReferenceInvalidError(reason="knowledge_rebuild_background_required")
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or type(expected_model_config_revision) is not int
        or expected_model_config_revision < 0
        or not isinstance(expected_index_generation, str)
        or not expected_index_generation
    ):
        raise KnowledgeOperationPlanConflictError(reason="knowledge_rebuild_command_expectations_required")
    with get_sync_db_session() as session:
        candidate = KnowledgeModelReferenceApplication.repository.get(session, knowledge_id)
        if candidate is not None and candidate.model_transition is None:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_rebuild_operation_missing")
        result = get_knowledge_model_read_runtime_sync().require(
            knowledge_id,
            session=session,
            slot_key="model_transition.pending_model_id",
            expected_operation_id=operation_id,
            expected_model_config_revision=expected_model_config_revision,
            expected_index_generation=expected_index_generation,
        )
        if model_hint is not None:
            try:
                if canonical_target_id(model_hint) != str(result.model_id):
                    raise ValueError("legacy model hint differs from the business pending slot")
            except (TypeError, ValueError) as error:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_rebuild_model_hint_obsolete") from error
        facts = json.loads(result.read.snapshot.payload_json)["knowledge"]
        return Knowledge(**facts), result.model_id


def _finalize_rebuild(knowledge_id, *, operation_id, expected_model_config_revision, expected_index_generation):
    with get_sync_db_session() as session:
        prepared = KnowledgeModelReferenceApplication.prepare_finalization(
            session,
            knowledge_id,
            operation_id=operation_id,
            expected_model_config_revision=expected_model_config_revision,
            expected_index_generation=expected_index_generation,
        )
        KnowledgeModelReferenceApplication.apply_finalization(session, prepared)
        session.commit()


def _delete_rebuild_vectors(knowledge, invoke_user_id, **command):
    # The existing collection-only deletion rule remains, but the standard
    # RAG admission now checks this exact pending operation before its IO.
    vector = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
        invoke_user_id=invoke_user_id,
        knowledge=knowledge,
        embeddings=FakeEmbeddings(),
        **_rebuild_rag_scope(**command),
    )
    if isinstance(vector.col, Collection):
        if not knowledge.collection_name.startswith("col"):
            raise ValueError("knowledge.collection_name must start with 'col' not support partition mode")
        vector.col.drop()


def _delete_file_vectors(vector, space_id, file_id):
    if vector.col is not None:
        vector.col.delete(f"document_id == {int(file_id)} && knowledge_id == {int(space_id)}")


def _rebuild_embeddings(
    knowledge: Knowledge, files: list[KnowledgeFile], new_model_id: int, invoke_user_id: int, **command
) -> tuple[list[int], list[int]]:
    """
    Rebuildembeddings

    Returns:
        tuple: (Success FilesIDVertical, Failed FilesIDVertical)
    """
    success_files = []
    failed_files = []
    vector_client = None

    try:
        # DapatkanEShitting the nail on the headchunkMessage
        index_name = knowledge.index_name
        scope = _rebuild_rag_scope(**command)
        es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge, **scope)

        # Get newembeddingModel and createMilvusClient
        logger.info(f"[DEBUG] Begin initializing newembeddingModelsmodel_id={new_model_id}")
        new_embeddings = LLMService.get_bisheng_knowledge_embedding_sync(
            model_id=new_model_id, invoke_user_id=invoke_user_id
        )
        logger.info(
            f"[DEBUG] Slider Created Successfully.embeddingModel Instance: {type(new_embeddings).__name__}, model_id={getattr(new_embeddings, 'model_id', 'unknown')}"
        )

        # TestembeddingIs the model available
        try:
            test_result = new_embeddings.embed_query("Test text")
            logger.info(
                f"[DEBUG] EmbeddingModel tested successfully, dimension returned: {len(test_result) if test_result else 'None'}"
            )
        except Exception as e:
            logger.error(f"[DEBUG] EmbeddingModel Test Failed: {e!s}")
            # Model test failure should terminate the entire process, not continue
            raise RuntimeError(f"EmbeddingModel not available: {e!s}") from e

        vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
            invoke_user_id=invoke_user_id,
            knowledge=knowledge,
            embeddings=new_embeddings,
            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
            **scope,
        )
        logger.info(f"[DEBUG] Slider Created Successfully.MilvusClientcollection_name={knowledge.collection_name}")

        # OthersESWhether the index is present (check in advance, avoid double-checking in the loop)
        if not es_client.client.indices.exists(index=index_name):
            logger.error(f"ES index {index_name} does not exist")
            raise RuntimeError(f"Rebuild source index {index_name} does not exist")

        # Regenerate for each fileembeddings
        for file in files:
            try:
                success = _process_single_file(file, es_client, index_name, vector_client)
            except KnowledgeUnificationError:
                raise
            except Exception as e:
                logger.exception(f"Failed to rebuild embeddings for file_id={file.id}: {e!s}")
                success = False
            if success:
                success_files.append(file.id)
                logger.info(f"Successfully rebuilt embeddings for file_id={file.id}")
            else:
                # Failed target cleanup is mandatory. If this fails, keep the
                # operation pending rather than publish inconsistent vectors.
                _delete_file_vectors(vector_client, knowledge.id, file.id)
                failed_files.append(file.id)

    except Exception as e:
        logger.exception(f"Failed to rebuild embeddings: {e!s}")
        raise

    return success_files, failed_files


@dataclass(frozen=True, slots=True)
class ProcessingFileResult:
    succeeded: bool
    chunk_count: int

    def __bool__(self):
        return self.succeeded


def _process_single_file(file, es_client, index_name, vector_client):
    return bool(_process_file_chunks(file, es_client, index_name, vector_client))


def _process_file_chunks(file, es_client, index_name, vector_client) -> ProcessingFileResult:
    """Processing of individual filesembeddingRebuild"""
    logger.info(f"Rebuilding embeddings for file_id={file.id}")

    # FROMESGet all of this file inchunks
    search_query = {"query": {"match": {"metadata.document_id": file.id}}}

    logger.debug(f"ES search query: {search_query}")

    chunks = get_all_es_chunks(es_client.client, index_name, search_query)

    logger.info(f"Found {len(chunks)} chunks in ES for file_id={file.id}")

    if not chunks:
        logger.warning(f"No chunks found for file_id={file.id}")
        return ProcessingFileResult(getattr(file, "status", None) == KnowledgeFileStatus.SUCCESS.value, 0)

    # Extract text and metadata
    texts = []
    metadatas = []
    for chunk in chunks:
        source = chunk["_source"]
        texts.append(source["text"])
        # Removepkfields, avoid insertingMilvusTime Conflict
        metadata = deepcopy(source["metadata"])
        metadata.pop("pk", None)
        metadatas.append(metadata)

    logger.info(f"Found {len(texts)} chunks for file_id={file.id}")

    # Insert data intoMilvus
    logger.info(f"[DEBUG] Upcoming Callsvector_client.add_texts, textsQuantity={len(texts)}")

    try:
        vector_client.add_texts(texts=texts, metadatas=metadatas)
        logger.info("[DEBUG] vector_client.add_textsCall successful")
        return ProcessingFileResult(True, len(texts))
    except Exception as add_error:
        logger.error(f"[DEBUG] vector_client.add_textsCall failed: {add_error!s}")
        raise add_error


def get_all_es_chunks(es_client, index_name, query):
    result = es_client.search(index=index_name, body=query, size=5000, scroll="1m")
    res = []

    def handle_hits(hits):
        for hit in hits:
            res.append(hit)

    handle_hits(result.get("hits", {}).get("hits", []))
    scroll_id = result.get("_scroll_id")
    try:
        while scroll_id:
            result = es_client.scroll(scroll_id=scroll_id, scroll="1m")
            next_scroll_id = result.get("_scroll_id")
            if next_scroll_id:
                scroll_id = next_scroll_id
            tmp_hits = result.get("hits", {}).get("hits", [])
            if not tmp_hits:
                break
            handle_hits(tmp_hits)
    finally:
        if scroll_id:
            es_client.clear_scroll(scroll_id=scroll_id)
    return res


def _require_processing_model(
    space_id: int,
    *,
    operation_id: str | None,
    expected_model_config_revision: int,
    expected_index_generation: str,
):
    if get_current_background_task() is None:
        raise ResourceReferenceInvalidError(reason="knowledge_rebuild_background_required")
    if (
        type(expected_model_config_revision) is not int
        or expected_model_config_revision < 0
        or not isinstance(expected_index_generation, str)
        or not expected_index_generation
    ):
        raise KnowledgeOperationPlanConflictError(reason="knowledge_rebuild_command_expectations_required")
    with get_sync_db_session() as session:
        candidate = KnowledgeModelReferenceApplication.repository.get(session, space_id)
        if candidate is None or candidate.type != 3:
            raise ResourceReferenceInvalidError(reason="knowledge_rebuild_space_required")
        slot = "model_transition.pending_model_id" if candidate.model_transition is not None else "model"
        if slot != "model" and not operation_id:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_rebuild_command_expectations_required")
        admitted = get_knowledge_model_read_runtime_sync().require(
            space_id,
            session=session,
            slot_key=slot,
            expected_operation_id=operation_id if slot != "model" else None,
            expected_model_config_revision=expected_model_config_revision,
            expected_index_generation=expected_index_generation,
        )
        knowledge = Knowledge(**json.loads(admitted.read.snapshot.payload_json)["knowledge"])
    scope = {
        "model_slot": slot,
        "expected_operation_id": admitted.operation_id,
        "expected_model_config_revision": admitted.model_config_revision,
        "expected_index_generation": admitted.index_generation,
    }
    return knowledge, admitted, scope


def reset_processing_target(*, space_id: int, invoke_user_id: int, **expectations) -> bool:
    """Reset the original physical target before any file succeeds in this job."""
    knowledge, _, scope = _require_processing_model(space_id, **expectations)
    vector = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
        invoke_user_id=invoke_user_id,
        knowledge=knowledge,
        embeddings=FakeEmbeddings(),
        **scope,
    )
    if vector.col is not None:
        if not isinstance(vector.col, Collection) or not knowledge.collection_name.startswith("col"):
            raise ValueError("rebuild target must use its original collection mode")
        vector.col.drop()
    return True


def rebuild_processing_file(
    file_id: int,
    *,
    space_id: int,
    invoke_user_id: int,
    operation_id: str | None,
    expected_model_config_revision: int,
    expected_index_generation: str,
) -> ProcessingFileResult:
    """Actual J1 per-file work; it never finalizes a task or business source."""
    knowledge, admitted, scope = _require_processing_model(
        space_id,
        operation_id=operation_id,
        expected_model_config_revision=expected_model_config_revision,
        expected_index_generation=expected_index_generation,
    )
    file = KnowledgeFileDao.query_by_id_sync(file_id)
    if file is None or file.knowledge_id != space_id or file.tenant_id != knowledge.tenant_id:
        raise ResourceReferenceInvalidError(reason="knowledge_rebuild_file_scope_changed")
    if file.status not in {
        KnowledgeFileStatus.SUCCESS.value,
        KnowledgeFileStatus.FAILED.value,
        KnowledgeFileStatus.TIMEOUT.value,
    }:
        raise KnowledgeProcessingConflictError(reason="processing_file_state_not_ready")
    es = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge, **scope)
    embedding = LLMService.get_bisheng_knowledge_embedding_sync(
        model_id=admitted.model_id, invoke_user_id=invoke_user_id
    )
    vector = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
        invoke_user_id=invoke_user_id,
        knowledge=knowledge,
        embeddings=embedding,
        metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
        **scope,
    )
    # Replacing this file's target vectors makes an interrupted/manual retry
    # idempotent without deleting another file or the original ES chunks.
    _delete_file_vectors(vector, space_id, file_id)
    try:
        result = _process_file_chunks(file, es, knowledge.index_name or knowledge.collection_name, vector)
        if not result.succeeded:
            _delete_file_vectors(vector, space_id, file_id)
        return result
    except Exception:
        _delete_file_vectors(vector, space_id, file_id)
        raise


@bisheng_celery.task(acks_late=True)
def rebuild_knowledge_file_chunk(file_id: int):
    trace_id_var.set(f"rebuild_knowledge_file_chunk_{file_id}")
    logger.info(f"start rebuild_knowledge_file_chunk file_id={file_id}")
    db_file = KnowledgeFileDao.query_by_id_sync(file_id)
    if not db_file:
        logger.warning(f"No knowledge file found for file_id={file_id}")
        return
    try:
        _rebuild_knowledge_file_chunk(db_file)
    except BaseErrorCode as e:
        KnowledgeFileDao.update_file_status([db_file.id], KnowledgeFileStatus.FAILED, e.to_json_str())
    except Exception as e:
        logger.exception(f"Failed to rebuild knowledge file chunk: {e!s}")
        KnowledgeFileDao.update_file_status(
            [db_file.id], KnowledgeFileStatus.FAILED, ServerError(exception=e).to_json_str()
        )


def _rebuild_knowledge_file_chunk(db_file: KnowledgeFile):
    db_knowledge = KnowledgeDao.query_by_id(db_file.knowledge_id)
    milvus_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(db_file.user_id, knowledge=db_knowledge)
    es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(db_knowledge)

    index_name = db_knowledge.index_name or db_knowledge.collection_name
    query = {"query": {"match": {"metadata.document_id": db_file.id}}}

    chunks = get_all_es_chunks(es_client.client, index_name, query)
    if not chunks:
        logger.warning("No chunks found for")
        return

    logger.info(f"Found {len(chunks)} chunks in ES for file_id={db_file.id}")

    from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils

    texts = []
    metadatas = []
    pks_to_delete = []

    for chunk in chunks:
        source = chunk["_source"]
        old_text = source.get("text", "")
        metadata = source.get("metadata", {})

        pk = metadata.pop("pk", None)
        if pk is not None:
            pks_to_delete.append(pk)

        # extract raw chunk
        raw_chunk = KnowledgeUtils.split_chunk_metadata(old_text)

        # update metadata
        metadata["document_name"] = db_file.file_name
        metadata["abstract"] = db_file.abstract
        metadata["updater"] = db_file.updater_name
        metadata["update_time"] = int(db_file.update_time.timestamp())

        # re-concatenate
        new_text = KnowledgeUtils.aggregate_chunk_metadata(raw_chunk, metadata)

        texts.append(new_text)
        metadatas.append(metadata)

    # Delete old data from ES
    es_client.client.delete_by_query(index=index_name, body=query)

    # Delete old data from Milvus
    if pks_to_delete and hasattr(milvus_client, "col") and milvus_client.col:
        try:
            milvus_client.col.delete(f"pk in {pks_to_delete}")
        except Exception as e:
            logger.warning(f"Failed to delete old pk(s) from Milvus: {e!s}")

    # Re-insert into Milvus and ES
    logger.info(f"Re-inserting {len(texts)} chunks for file_id={db_file.id} into vector stores")
    milvus_client.add_texts(texts=texts, metadatas=metadatas)
    es_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f"rebuild_knowledge_file_chunk completed successfully for file_id={db_file.id}")
