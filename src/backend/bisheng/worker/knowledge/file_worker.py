import json
from typing import List

from bisheng.api.services.knowledge_imp import decide_vectorstores
from bisheng.core.celery_app import celery_app
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao, KnowledgeTypeEnum
from bisheng.database.models.knowledge_file import (KnowledgeFile, KnowledgeFileDao,
                                                    KnowledgeFileStatus, QAKnoweldgeDao,
                                                    QAKnowledge)
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.utils import generate_uuid
from bisheng.utils.minio_client import MinioClient
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from loguru import logger
from pymilvus import Collection, Milvus, MilvusException


@celery_app.task(acks_late=True)
def file_copy_celery(param: json) -> str:
    """将某个知识库的文件复制到另外一个知识库
    1. mysql的复制
    2. 文件的复制
    3. 向量的复制
    """

    source_knowledge_id = param.get('source_knowledge_id')
    target_id = param.get('target_id')
    login_user = param.get('login_user')
    logger.info('file_copy_celery start source_id={} target_id={}', source_knowledge_id, target_id)
    minio_client = MinioClient()
    page_size = 20
    page_num = 1
    source_knowledge = KnowledgeDao.query_by_id(source_knowledge_id)
    target_knowledge = KnowledgeDao.query_by_id(target_id)

    target_list: List[KnowledgeFile] = KnowledgeFileDao.get_file_by_condition(target_id)  # 所有的文件
    if target_list:
        target_list = [t.md5 for t in target_list]
    while True:
        if source_knowledge.type == KnowledgeTypeEnum.NORMAL.value:
            files = KnowledgeFileDao.get_file_by_filters(source_knowledge_id,
                                                         page=page_num,
                                                         page_size=page_size)
            for one in files:
                if target_list and one.md5 in target_list:
                    # 重复任务防止重复写入
                    continue
                try:
                    copy_normal(
                        minio_client,
                        one,
                        source_knowledge,
                        target_knowledge,
                        login_user.user_id,
                    )
                except Exception as e:
                    logger.error(f'copy file error: {one.file_name} {e}')

        else:
            qa: List[QAKnowledge] = QAKnoweldgeDao.get_qa_knowledge_by_knowledge_id(
                source_knowledge_id, page=page_num, page_size=page_size)
            for one in qa:
                copy_qa(one, source_knowledge, target_knowledge, login_user.user_id)
        page_num += 1
        if not files or len(files) < page_size:
            break
    # 恢复状态
    logger.info('file_copy_celery end')
    source_knowledge.state = 1
    target_knowledge.state = 1
    KnowledgeDao.update_one(source_knowledge)
    KnowledgeDao.update_one(target_knowledge)
    return 'copy task done'


def copy_normal(
    minio_client: MinioClient,
    one: KnowledgeFile,
    source_knowledge: Knowledge,
    target_knowledge: Knowledge,
    op_user_id: int,
):
    one_dict = one.model_dump()
    one_dict.pop('id')
    one_dict.pop('update_time')
    one_dict['user_id'] = op_user_id
    one_dict['knowledge_id'] = target_knowledge.id
    one_dict['status'] = KnowledgeFileStatus.PROCESSING.value

    source_file_pdf = one.id
    source_file = one.object_name
    bbox_file = one.bbox_object_name

    knowledge_new = KnowledgeFile(**one_dict)
    knowledge_new = KnowledgeFileDao.add_file(knowledge_new)

    # 迁移 file
    try:
        source_type = source_file.rsplit('.', 1)[-1]
        source_path = source_file.split('/')[0]
        target_source_file = f'{source_path}/{knowledge_new.id}.{source_type}'
        minio_client.copy_object(source_file, target_source_file)
        knowledge_new.object_name = target_source_file

        target_file_pdf = f'{knowledge_new.id}'
        minio_client.copy_object(f'{source_file_pdf}', target_file_pdf)

        if minio_client.object_exists('bisheng', bbox_file):
            target_bbox_file = f'partitions/{knowledge_new.id}.json'
            minio_client.copy_object(bbox_file, target_bbox_file)
            knowledge_new.bbox_object_name = target_bbox_file
    except Exception as e:
        logger.error('copy_file_error file_id={} e={}', knowledge_new.id, str(e))
        knowledge_new.remark = str(e)[:500]
        knowledge_new.status = KnowledgeFileStatus.FAILED.value
        KnowledgeFileDao.update(knowledge_new)
        return

    # copy vector
    try:
        if one.status == KnowledgeFileStatus.SUCCESS.value:
            copy_vector(source_knowledge, target_knowledge, one.id, knowledge_new.id)
            knowledge_new.status = KnowledgeFileStatus.SUCCESS.value
        else:
            knowledge_new.status = one.status
        KnowledgeFileDao.update(knowledge_new)
    except Exception as e:
        logger.exception(e)
        logger.error('source={} new={} e={}', one.id, knowledge_new.id, e)
        knowledge_new.remark = str(e)[:500]
        knowledge_new.status = KnowledgeFileStatus.FAILED.value
        KnowledgeFileDao.update(knowledge_new)


def copy_qa(qa: QAKnowledge, source_knowledge: Knowledge, target_knowledge: Knowledge,
            op_user_id: int):
    one_dict = qa.model_dump()
    one_dict.pop('id')
    one_dict.pop('create_time')
    one_dict.pop('update_time')
    one_dict['user_id'] = op_user_id
    one_dict['knowledge_id'] = target_knowledge.id
    one_dict['status'] = KnowledgeFileStatus.PROCESSING.value

    qa_knowledge = QAKnowledge(**one_dict)
    qa_new = QAKnoweldgeDao.insert_qa(qa_knowledge)
    try:
        copy_vector(source_knowledge, target_knowledge, qa.id, qa_new.id)
        qa_new.status = KnowledgeFileStatus.SUCCESS.value
        QAKnoweldgeDao.update(qa_new)
    except Exception as e:
        logger.error(e)
        qa_new.status = KnowledgeFileStatus.FAILED.value
        QAKnoweldgeDao.update(qa_new)


def copy_vector(
    source_konwledge: Knowledge,
    target_knowledge: Knowledge,
    source_file_id: int,
    target_file_id: int,
):
    # 迁移 vectordb
    embedding = FakeEmbedding()
    source_col = source_konwledge.collection_name
    source_milvus: Milvus = decide_vectorstores(source_col, 'Milvus', embedding)
    # 当前es 不包含vector
    fields = [s.name for s in source_milvus.col.schema.fields if s.name != 'pk']
    source_data = source_milvus.col.query(
        expr=f"file_id=={source_file_id} && knowledge_id=='{source_konwledge.id}'",
        output_fields=fields,
    )
    for data in source_data:
        data['knowledge_id'] = str(target_knowledge.id)
        data['file_id'] = target_file_id
    milvus_db: Milvus = decide_vectorstores(target_knowledge.collection_name, 'Milvus', embedding)
    if milvus_db:
        insert_milvus(source_data, fields, milvus_db)

    es_db = decide_vectorstores(target_knowledge.index_name, 'ElasticKeywordsSearch', embedding)
    if es_db:
        insert_es(source_data, es_db)


def insert_milvus(li: List, fields: list, target: Milvus):
    total_count = len(li)
    batch_size = 1000
    res_list = []
    for i in range(0, total_count, batch_size):
        # Grab end index
        end = min(i + batch_size, total_count)
        # Convert dict to list of lists batch for insertion
        insert_list = [[data[x] for data in li[i:end]] for x in fields]
        # Insert into the collection.
        try:
            res: Collection
            res = target.col.insert(insert_list, timeout=100)
            res_list.extend(res.primary_keys)
        except MilvusException as e:
            logger.error('Failed to insert batch starting at entity: %s/%s', i, total_count)
            raise e
    logger.info('copy_done pk_size={}', len(res_list))


def insert_es(li: List, target: ElasticKeywordsSearch):
    from elasticsearch.helpers import bulk
    res_list = []
    ids = [generate_uuid() for _ in li]
    requests = []
    for i, data in enumerate(li):
        text = data.pop('text')
        data.pop('vector', '')  # es 不包含vector
        metadata = data
        request = {
            '_op_type': 'index',
            '_index': target.index_name,
            'text': text,
            'metadata': metadata,
            '_id': ids[i],
        }
        requests.append(request)
    bulk(target.client, requests)

    target.client.indices.refresh(index=target.index_name)
    logger.info('copy_es_done pk_size={}', len(res_list))
