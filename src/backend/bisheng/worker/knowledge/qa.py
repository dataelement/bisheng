from loguru import logger
from pymilvus import Collection

from bisheng.api.services.knowledge_imp import QA_save_knowledge
from bisheng.common.errcode.knowledge import KnowledgeFileFailedError, KnowledgeUnificationError
from bisheng.core.ai import FakeEmbeddings
from bisheng.core.logger import trace_id_var
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import (
    QAKnoweldgeDao,
    QAKnowledge,
    QAKnowledgeUpsert,
    QAStatus,
)
from bisheng.worker.knowledge.rebuild_knowledge_worker import (
    _delete_rebuild_vectors,
    _finalize_rebuild,
    _rebuild_rag_scope,
    _require_current_rebuild,
)
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task
def insert_qa_celery(qa_id: int):
    """
    Insert a QA pair into the milvus and es.
    """
    trace_id_var.set(f"insert_qa_{qa_id}")
    qa_info = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(qa_id)
    if not qa_info:
        logger.error(f"QA with id {qa_id} not found.")
        return
    knowledge_info = KnowledgeDao.query_by_id(qa_info.knowledge_id)
    if not knowledge_info:
        logger.error(f"Knowledge with id {qa_info.knowledge_id} not found.")
        return
    QA_save_knowledge(knowledge_info, qa_info)


@bisheng_celery.task
def copy_qa_knowledge_celery(source_knowledge_id: int, target_knowledge_id: int, login_user_id: int, tenant_id=None):
    from bisheng.knowledge.application.copy_execution import assert_copy_actor, claim_copy, copy_execution_scope
    from bisheng.knowledge.domain.repositories.copy_repository import CopyRepository

    with copy_execution_scope(tenant_id):
        pair = claim_copy(tenant_id, source_knowledge_id, target_knowledge_id, login_user_id)
        if pair is None:
            return "duplicate copy ignored"
        source_knowledge, target_knowledge = pair
        try:
            qa_count = QAKnoweldgeDao.count_by_id(source_knowledge_id)

            if qa_count == 0:
                logger.info(f"No QA knowledge to copy from knowledge id {source_knowledge_id}.")
                raise KnowledgeFileFailedError(msg="Source QA became empty")

            source_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
                0, knowledge=source_knowledge, embeddings=FakeEmbeddings()
            )

            # create new collection name for target knowledge
            new_col = Collection(
                name=target_knowledge.collection_name,
                schema=source_milvus.col.schema,
                using=source_milvus.alias,
                consistency_level=source_milvus.consistency_level,
            )

            target_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
                0, knowledge=target_knowledge, embeddings=FakeEmbeddings()
            )

            # Batched SalinQAkey learning points Start from the first page
            batch_size = 100
            for page in range((qa_count + batch_size - 1) // batch_size):
                page += 1
                qa_list: list[QAKnowledge] = QAKnoweldgeDao.get_qa_knowledge_by_knowledge_id(
                    knowledge_id=source_knowledge_id, page=page, page_size=batch_size
                )
                result = []
                try:
                    # SalinQAkey learning points Batch Insert
                    new_qa_list = []
                    for qa in qa_list:
                        qa_dict = qa.model_dump()
                        qa_dict.pop("id")
                        qa_dict.pop("create_time")
                        qa_dict.pop("update_time")
                        qa_dict["user_id"] = login_user_id
                        qa_dict["knowledge_id"] = target_knowledge_id
                        new_qa = QAKnowledgeUpsert(**qa_dict)
                        new_qa_list.append(new_qa)

                    result = QAKnoweldgeDao.batch_insert_qa(new_qa_list)

                    id_mapping = {qa_list[i].id: result[i].id for i in range(len(qa_list))}

                    # Copy Vector
                    source_ids = [int(qa.id) for qa in qa_list if qa.status == QAStatus.ENABLED.value]
                    fields = [s.name for s in source_milvus.col.schema.fields if s.name != "pk"]
                    vectors = source_milvus.col.query(
                        expr=f"file_id in {source_ids} && knowledge_id == '{source_knowledge_id}'", output_fields=fields
                    )

                    for vector in vectors:
                        vector["file_id"] = id_mapping[vector["file_id"]]
                        vector["knowledge_id"] = str(target_knowledge_id)
                        vector.pop("pk")

                    if vectors.__len__() != 0:
                        target_milvus.col.insert(vectors)

                    logger.info(
                        f"Copied {len(qa_list)} QA knowledge from knowledge id {source_knowledge_id} "
                        f"to knowledge id {target_knowledge_id}."
                    )

                    # es Salin
                    es_db = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=target_knowledge)
                    es_texts = []
                    es_metadatas = []
                    for vector in vectors:
                        text = vector.pop("text")
                        vector.pop("vector")
                        es_texts.append(text)
                        es_metadatas.append(vector)

                    if es_texts.__len__() != 0:
                        es_db.add_texts(es_texts, es_metadatas)

                    logger.info(
                        f"Updated status to SUCCESS for copied QA knowledge in knowledge id {target_knowledge_id}."
                    )

                    logger.info(f"Finished copying batch {page + 1} of QA knowledge.")
                except Exception as e:
                    logger.error(f"Error copying batch {page + 1} of QA knowledge: {e}")

                    QAKnoweldgeDao.batch_update_status_by_ids(
                        qa_ids=[new_qa.id for new_qa in result],
                        status=QAStatus.FAILED,
                        remark=KnowledgeFileFailedError(exception=e).to_json_str(),
                    )
                    raise
            assert_copy_actor(tenant_id, source_knowledge, login_user_id)
            CopyRepository.finish(tenant_id, source_knowledge_id, target_knowledge_id, succeeded=True)
        except Exception:
            logger.exception("QA copy failed source={} target={}", source_knowledge_id, target_knowledge_id)
            CopyRepository.finish(tenant_id, source_knowledge_id, target_knowledge_id, succeeded=False)
            raise


@bisheng_celery.task
def rebuild_qa_knowledge_celery(
    knowledge_id: int,
    embedding_model_id: int | None,
    invoke_user_id: int,
    *,
    operation_id: str | None = None,
    expected_model_config_revision: int | None = None,
    expected_index_generation: str | None = None,
):
    """Rebuild QA from the actual pending model and finalize SQL/R2 together."""
    trace_id_var.set(f"rebuild_qa_knowledge_{knowledge_id}")
    try:
        command = {
            "operation_id": operation_id,
            "expected_model_config_revision": expected_model_config_revision,
            "expected_index_generation": expected_index_generation,
        }
        knowledge_info, _ = _require_current_rebuild(knowledge_id, embedding_model_id, **command)
        scope = _rebuild_rag_scope(**command)

        # DeletemilvusCorresponding data in
        _delete_rebuild_vectors(knowledge_info, invoke_user_id, **command)

        es_db = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge_info, **scope)

        # InquiryesAll data in Delete
        es_result = es_db.client.search(
            body={"query": {"term": {"metadata.knowledge_id": str(knowledge_id)}}}, filter_path=["hits.total.value"]
        )

        total = es_result.get("hits", {}).get("total", {}).get("value", 0)

        logger.info(f"Found {total} documents in Elasticsearch for knowledge id {knowledge_id}.")

        if total <= 0:
            logger.info(f"No documents to delete in Elasticsearch for knowledge id {knowledge_id}.")
            _finalize_rebuild(knowledge_id, **command)
            return

        milvus_db = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
            invoke_user_id=invoke_user_id, knowledge=knowledge_info, **scope
        )

        # Batched RebuildQAThe knowledge base upon Start from the first page
        batch_size = 100
        for page in range((total + batch_size - 1) // batch_size):
            page += 1
            texts = []
            metadatas = []

            es_result = es_db.client.search(
                body={
                    "query": {"term": {"metadata.knowledge_id": str(knowledge_id)}},
                    "from": (page - 1) * batch_size,
                    "size": batch_size,
                },
                filter_path=["hits.hits._source"],
            )

            hits = es_result.get("hits", {}).get("hits", [])

            file_ids = [hit.get("_source", {}).get("metadata", {}).get("file_id") for hit in hits]

            try:
                QAKnoweldgeDao.batch_update_status_by_ids(qa_ids=file_ids, status=QAStatus.PROCESSING)

                for hit in hits:
                    source = hit.get("_source", {})
                    text = source.get("text", "")
                    metadata = source.get("metadata", {})
                    texts.append(text)
                    metadata.pop("vector", None)
                    metadatas.append(metadata)

                # Insertmilvus
                milvus_db.add_texts(texts, metadatas)

                QAKnoweldgeDao.batch_update_status_by_ids(qa_ids=file_ids, status=QAStatus.ENABLED)

                logger.info(f"Rebuilt batch {page} of QA knowledge into Milvus for knowledge id {knowledge_id}.")
            except KnowledgeUnificationError:
                raise
            except Exception as e:
                logger.exception(f"Error rebuilding batch {page} of QA knowledge: {e}")

                QAKnoweldgeDao.batch_update_status_by_ids(
                    qa_ids=file_ids, status=QAStatus.FAILED, remark=KnowledgeFileFailedError(exception=e).to_json_str()
                )

        _finalize_rebuild(knowledge_id, **command)
        logger.info(f"Finished rebuilding QA knowledge for knowledge id {knowledge_id}.")
    except Exception as e:
        logger.exception(f"Error rebuilding QA knowledge for knowledge id {knowledge_id}: {e}")
        # Global/guard failures leave the business transition unfinished;
        # only a successful finalization may publish and remove its old slot.
        raise
