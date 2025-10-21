from typing import List

from elasticsearch.helpers import bulk
from loguru import logger

from bisheng.api.services.knowledge_imp import QA_save_knowledge, decide_vectorstores
from bisheng.database.models.knowledge import KnowledgeDao, KnowledgeState
from bisheng.database.models.knowledge_file import (
    QAKnoweldgeDao, QAKnowledge, KnowledgeFileStatus, QAKnowledgeUpsert, QAStatus,
)
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.utils import generate_uuid
from bisheng.worker import bisheng_celery
from bisheng_langchain.vectorstores import Milvus


@bisheng_celery.task
def insert_qa_celery(qa_id: int):
    """
    Insert a QA pair into the milvus and es.
    """
    with logger.contextualize(trace_id=f"insert_qa_{qa_id}"):
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
def copy_qa_knowledge_celery(source_knowledge_id: int, target_knowledge_id: int, login_user_id: int):
    """
    复制QA知识点
    :param login_user_id: 登录用户ID
    :param source_knowledge_id: 源知识点ID
    :param target_knowledge_id: 目标知识点ID
    :return:
    """
    with logger.contextualize(trace_id=f"copy_qa_knowledge_{source_knowledge_id}_to_{target_knowledge_id}"):

        source_knowledge = KnowledgeDao.query_by_id(source_knowledge_id)

        target_knowledge = KnowledgeDao.query_by_id(target_knowledge_id)

        qa_count = QAKnoweldgeDao.count_by_id(source_knowledge_id)

        if qa_count == 0:
            logger.info(f"No QA knowledge to copy from knowledge id {source_knowledge_id}.")
            return

        source_milvus: Milvus = decide_vectorstores(source_knowledge.collection_name, "Milvus", FakeEmbedding())

        target_milvus: Milvus = decide_vectorstores(target_knowledge.collection_name, "Milvus", FakeEmbedding())

        # 分批 复制QA知识点 从第一页开始
        batch_size = 100
        for page in range((qa_count + batch_size - 1) // batch_size):
            page += 1
            qa_list: List[QAKnowledge] = QAKnoweldgeDao.get_qa_knowledge_by_knowledge_id(
                knowledge_id=source_knowledge_id,
                page=page,
                page_size=batch_size
            )
            # 复制QA知识点 批量 插入
            new_qa_list = []
            for qa in qa_list:
                qa_dict = qa.model_dump()
                qa_dict.pop("id")
                qa_dict.pop("create_time")
                qa_dict.pop("update_time")
                qa_dict["user_id"] = login_user_id
                qa_dict["knowledge_id"] = target_knowledge_id
                qa_dict["status"] = KnowledgeFileStatus.PROCESSING.value
                new_qa = QAKnowledgeUpsert(**qa_dict)
                new_qa_list.append(new_qa)

            result = QAKnoweldgeDao.batch_insert_qa(new_qa_list)

            id_mapping = {qa_list[i].id: result[i].id for i in range(len(qa_list))}

            # 复制向量
            source_ids = [int(qa.id) for qa in qa_list]
            fields = [s.name for s in source_milvus.col.schema.fields if s.name != "pk"]
            vectors = source_milvus.col.query(
                expr=f"file_id in {source_ids} && knowledge_id == '{source_knowledge_id}'",
                output_fields=fields)

            for vector in vectors:
                vector["file_id"] = id_mapping[vector["file_id"]]
                vector["knowledge_id"] = str(target_knowledge_id)
                vector.pop("pk")

            target_milvus.col.insert(vectors)

            logger.info(f"Copied {len(qa_list)} QA knowledge from knowledge id {source_knowledge_id} "
                        f"to knowledge id {target_knowledge_id}.")

            # es 复制
            es_db = decide_vectorstores(
                target_knowledge.index_name, "ElasticKeywordsSearch", FakeEmbedding()
            )

            es_texts = []
            es_metadatas = []
            for vector in vectors:
                text = vector.pop("text")
                es_texts.append(text)
                es_metadatas.append(vector)

            es_db.add_texts(es_texts, es_metadatas)

            # TODO 不需要修改状态 使用原有状态
            # 批量更新状态为完成
            # QAKnoweldgeDao.batch_update_status_by_ids(
            #     qa_ids=[new_qa.id for new_qa in result],
            #     status=QAStatus.ENABLED
            # )

            logger.info(f"Updated status to SUCCESS for copied QA knowledge in knowledge id {target_knowledge_id}.")

            logger.info(f"Finished copying batch {page + 1} of QA knowledge.")

        # 全部复制完成 更新状态

        target_knowledge.state = 1
        KnowledgeDao.update_state(knowledge_id=source_knowledge.id, state=KnowledgeState.PUBLISHED,
                                  update_time=source_knowledge.update_time)
        KnowledgeDao.update_one(target_knowledge)

        logger.info(f"Finished copying all QA knowledge from knowledge id {source_knowledge_id} "
                    f"to knowledge id {target_knowledge_id}.")
