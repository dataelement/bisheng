from typing import List

from loguru import logger

from bisheng.api.services.knowledge_imp import (
    decide_vectorstores
)
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.errcode.knowledge import KnowledgeFileFailedError
from bisheng.core.logger import trace_id_var
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.llm.domain import LLMService
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(acks_late=True)
def rebuild_knowledge_celery(knowledge_id: int, new_model_id: int, invoke_user_id: int) -> str:
    """
    Asynchronous task to rebuild knowledge base
    
    Args:
        knowledge_id: The knowledge base uponID
        new_model_id: New.. embeddingModelsID
        invoke_user_id: Call UserID
        
    Returns:
        str: Task Execution Results
    """
    trace_id_var.set(f'rebuild_knowledge_{knowledge_id}')
    logger.info(f"rebuild_knowledge_celery start knowledge_id={knowledge_id} new_model_id={new_model_id}")
    try:
        # Get Knowledge Base Information
        knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge:
            logger.error(f"knowledge_id={knowledge_id} not found")
            return f"knowledge {knowledge_id} not found"

        # 1. according knowledge_id Found knowledgefile All in the tablestatus=2Andstatus=4File, put thestatusto4
        files = KnowledgeFileDao.get_files_by_multiple_status(
            knowledge_id,
            [KnowledgeFileStatus.SUCCESS.value, KnowledgeFileStatus.REBUILDING.value]
        )
        # 2. According to thecollection_namewentmilvusDelete Vector Store in
        KnowledgeService.delete_knowledge_file_in_vector(knowledge=knowledge, del_es=False)

        if not files:
            logger.info(f"knowledge_id={knowledge_id} has no success files")
            # Directly update knowledge base status to success
            knowledge.state = KnowledgeState.PUBLISHED.value
            KnowledgeDao.update_one(knowledge)
            return f"knowledge {knowledge_id} rebuild completed (no files)"

        # Updating file status to rebuild in progress
        file_ids = [f.id for f in files]
        KnowledgeFileDao.update_status_bulk(file_ids, KnowledgeFileStatus.REBUILDING)

        logger.info(f"Updated {len(files)} files to rebuilding status")

        # 3. accordingindex_nameFROMesGot it inchunkinformation, reembeddingInsertmilvus
        success_files, failed_files = _rebuild_embeddings(knowledge, files, new_model_id, invoke_user_id)

        # 4. Update file status
        KnowledgeFileDao.update_status_bulk(success_files, KnowledgeFileStatus.SUCCESS)

        for file_id in failed_files:
            file = next((f for f in files if f.id == file_id), None)
            if file:
                file.status = KnowledgeFileStatus.FAILED.value
                file.remark = KnowledgeFileFailedError(data={"exception": "rebuild error"}).to_json_str()
                KnowledgeFileDao.update(file)

        # 5. Update knowledge base status
        if failed_files:

            # DeleteesIndex andmilvusCollections to avoid data inconsistencies
            _delete_es_files(knowledge, failed_files)

            knowledge.state = KnowledgeState.FAILED.value
            logger.error(f"knowledge_id={knowledge_id} rebuild failed, failed_files={failed_files}")
        else:
            knowledge.state = KnowledgeState.PUBLISHED.value
            logger.info(f"knowledge_id={knowledge_id} rebuild completed successfully")

        KnowledgeDao.update_one(knowledge)

        return f"knowledge {knowledge_id} rebuild completed"

    except Exception as e:
        logger.exception(f"rebuild_knowledge_celery error: {str(e)}")
        # Unexpected handles during asynchronous tasksknowledgeSet to4
        try:
            knowledge = KnowledgeDao.query_by_id(knowledge_id)
            if knowledge:
                knowledge.state = KnowledgeState.FAILED.value
                KnowledgeDao.update_one(knowledge)
        except Exception as e2:
            logger.exception(f"Failed to update knowledge state after error: {str(e2)}")

        raise e


def _delete_es_files(knowledge: Knowledge, file_ids: List[int]):
    """DeleteESFile data in"""
    try:
        index_name = knowledge.index_name or knowledge.collection_name
        embeddings = FakeEmbedding()
        es_client = decide_vectorstores(index_name, "ElasticKeywordsSearch", embeddings)

        if not es_client.client.indices.exists(index=index_name):
            logger.warning(f"ES index {index_name} does not exist, skipping deletion")
            return

        for file_id in file_ids:
            delete_query = {
                "query": {
                    "match": {
                        "metadata.document_id": file_id
                    }
                }
            }
            response = es_client.client.delete_by_query(index=index_name, body=delete_query)
            deleted = response.get("deleted", 0)
            logger.info(f"Deleted {deleted} documents from ES for file_id={file_id}")

    except Exception as e:
        logger.exception(f"Failed to delete ES files for knowledge_id={knowledge.id}: {str(e)}")


def _rebuild_embeddings(knowledge: Knowledge, files: List[KnowledgeFile], new_model_id: int, invoke_user_id: int) -> \
        tuple[List[int], List[int]]:
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
        index_name = knowledge.index_name or knowledge.collection_name
        embeddings = FakeEmbedding()
        es_client = decide_vectorstores(index_name, "ElasticKeywordsSearch", embeddings)

        # Get newembeddingModel and createMilvusClient
        logger.info(f"[DEBUG] Begin initializing newembeddingModelsmodel_id={new_model_id}")
        new_embeddings = LLMService.get_bisheng_knowledge_embedding_sync(model_id=new_model_id,
                                                                         invoke_user_id=invoke_user_id)
        logger.info(
            f"[DEBUG] Slider Created Successfully.embeddingModel Instance: {type(new_embeddings).__name__}, model_id={getattr(new_embeddings, 'model_id', 'unknown')}")

        # TestembeddingIs the model available
        try:
            test_result = new_embeddings.embed_query("Test text")
            logger.info(
                f"[DEBUG] EmbeddingModel tested successfully, dimension returned: {len(test_result) if test_result else 'None'}")
        except Exception as e:
            logger.error(f"[DEBUG] EmbeddingModel Test Failed: {str(e)}")
            # Model test failure should terminate the entire process, not continue
            raise Exception(f"EmbeddingModel not available: {str(e)}")

        vector_client = decide_vectorstores(knowledge.collection_name, "Milvus", new_embeddings)
        logger.info(f"[DEBUG] Slider Created Successfully.MilvusClientcollection_name={knowledge.collection_name}")

        # OthersESWhether the index is present (check in advance, avoid double-checking in the loop)
        if not es_client.client.indices.exists(index=index_name):
            logger.error(f"ES index {index_name} does not exist")
            # Index does not exist, all files failed
            failed_files = [f.id for f in files]
            return success_files, failed_files

        # Regenerate for each fileembeddings
        for file in files:
            try:
                success = _process_single_file(file, es_client, index_name, vector_client)
                if success:
                    success_files.append(file.id)
                    logger.info(f"Successfully rebuilt embeddings for file_id={file.id}")
                else:
                    failed_files.append(file.id)
            except Exception as e:
                logger.exception(f"Failed to rebuild embeddings for file_id={file.id}: {str(e)}")
                failed_files.append(file.id)

    except Exception as e:
        logger.exception(f"Failed to rebuild embeddings: {str(e)}")
        # If the entire process fails, all unsuccessful files are marked as failed
        failed_files.extend([f.id for f in files if f.id not in success_files])

    return success_files, failed_files


def _process_single_file(file, es_client, index_name, vector_client):
    """Processing of individual filesembeddingRebuild"""
    logger.info(f"Rebuilding embeddings for file_id={file.id}")

    # FROMESGet all of this file inchunks
    search_query = {
        "query": {
            "match": {
                "metadata.document_id": file.id
            }
        },
        "size": 10000
    }

    logger.debug(f"ES search query: {search_query}")

    response = es_client.client.search(index=index_name, body=search_query)
    chunks = response.get("hits", {}).get("hits", [])

    logger.info(f"Found {len(chunks)} chunks in ES for file_id={file.id}")

    if not chunks:
        logger.warning(f"No chunks found for file_id={file.id}")
        return True  # No data to process, considered a success

    # Extract text and metadata
    texts = []
    metadatas = []
    for chunk in chunks:
        source = chunk["_source"]
        texts.append(source["text"])
        # Removepkfields, avoid insertingMilvusTime Conflict
        if "pk" in source["metadata"]:
            del source["metadata"]["pk"]

        metadatas.append(source["metadata"])

    logger.info(f"Found {len(texts)} chunks for file_id={file.id}")

    # Insert data intoMilvus
    logger.info(f"[DEBUG] Upcoming Callsvector_client.add_texts，textsQuantity={len(texts)}")
    logger.info(f"[DEBUG] First text example: {texts[0][:100] if texts else 'No texts'}...")

    try:
        vector_client.add_texts(texts=texts, metadatas=metadatas)
        logger.info(f"[DEBUG] vector_client.add_textsCall successful")
        return True
    except Exception as add_error:
        logger.error(f"[DEBUG] vector_client.add_textsCall failed: {str(add_error)}")
        raise add_error


def get_all_es_chunks(es_client, index_name, query):
    result = es_client.search(index=index_name,
                              body=query,
                              size=5000,
                              scroll="1m")
    res = []

    def handle_hits(hits):
        for hit in hits:
            res.append(hit)

    handle_hits(result.get("hits", {}).get("hits", []))
    scroll_id = result.get('_scroll_id')
    while scroll_id:
        result = es_client.scroll(scroll_id=scroll_id, scroll='1m')
        tmp_hits = result.get('hits', {}).get('hits', [])
        if not tmp_hits:
            break
        handle_hits(tmp_hits)
        scroll_id = result.get('_scroll_id')
    if scroll_id:
        es_client.clear_scroll(scroll_id=scroll_id)
    return res


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
        logger.exception(f"Failed to rebuild knowledge file chunk: {str(e)}")
        KnowledgeFileDao.update_file_status([db_file.id], KnowledgeFileStatus.FAILED,
                                            ServerError(exception=e).to_json_str())


def _rebuild_knowledge_file_chunk(db_file: KnowledgeFile):
    db_knowledge = KnowledgeDao.query_by_id(db_file.knowledge_id)
    milvus_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(db_file.user_id, knowledge=db_knowledge)
    es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(db_knowledge)

    index_name = db_knowledge.index_name or db_knowledge.collection_name
    query = {
        "query": {
            "match": {
                "metadata.document_id": db_file.id
            }
        }
    }

    chunks = get_all_es_chunks(es_client.client, index_name, query)
    if not chunks:
        logger.warning(f"No chunks found for")
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
            logger.warning(f"Failed to delete old pk(s) from Milvus: {str(e)}")

    # Re-insert into Milvus and ES
    logger.info(f"Re-inserting {len(texts)} chunks for file_id={db_file.id} into vector stores")
    milvus_client.add_texts(texts=texts, metadatas=metadatas)
    es_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f"rebuild_knowledge_file_chunk completed successfully for file_id={db_file.id}")
