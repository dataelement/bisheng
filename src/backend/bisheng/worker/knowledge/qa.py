from loguru import logger

from bisheng.api.services.knowledge_imp import QA_save_knowledge
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.knowledge_file import (
    QAKnoweldgeDao,
)
from bisheng.worker import bisheng_celery


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
