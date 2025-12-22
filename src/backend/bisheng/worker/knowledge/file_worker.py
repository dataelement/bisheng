import json
from typing import List

from loguru import logger
from pymilvus import Collection, MilvusException

from bisheng.api.services.knowledge_imp import decide_vectorstores, process_file_task, delete_knowledge_file_vectors, \
    KnowledgeUtils, delete_vector_files
from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.knowledge import KnowledgeFileFailedError
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeTypeEnum, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.utils import generate_uuid
from bisheng.worker.main import bisheng_celery
from bisheng_langchain.vectorstores import ElasticKeywordsSearch, Milvus


@bisheng_celery.task(acks_late=True)
def file_copy_celery(param: json) -> str:
    """将某个知识库的文件复制到另外一个知识库
    1. mysql的复制
    2. 文件的复制
    3. 向量的复制
    """

    source_knowledge_id = param.get("source_knowledge_id")
    target_id = param.get("target_id")
    login_user_id = param.get("login_user_id")
    logger.info(
        "file_copy_celery start source_id={} target_id={}",
        source_knowledge_id,
        target_id,
    )
    page_size = 20
    page_num = 1
    source_knowledge = KnowledgeDao.query_by_id(source_knowledge_id)
    target_knowledge = KnowledgeDao.query_by_id(target_id)

    target_list: List[KnowledgeFile] = KnowledgeFileDao.get_file_by_condition(
        target_id
    )  # 所有的文件
    if target_list:
        target_list = [t.md5 for t in target_list]
    while True:
        if source_knowledge.type == KnowledgeTypeEnum.NORMAL.value:
            files = KnowledgeFileDao.get_file_by_filters(
                source_knowledge_id, page=page_num, page_size=page_size
            )
            for one in files:
                if target_list and one.md5 in target_list:
                    # 重复任务防止重复写入
                    continue
                try:
                    copy_normal(
                        one,
                        source_knowledge,
                        target_knowledge,
                        login_user_id,
                    )
                except Exception as e:
                    logger.error(f"copy file error: {one.file_name} {e}")
        page_num += 1
        if not files or len(files) < page_size:
            break
    # 恢复状态
    logger.info("file_copy_celery end")
    target_knowledge.state = 1
    KnowledgeDao.update_state(knowledge_id=source_knowledge.id, state=KnowledgeState.PUBLISHED,
                              update_time=source_knowledge.update_time)
    KnowledgeDao.update_one(target_knowledge)
    return "copy task done"


def copy_normal(
        one: KnowledgeFile,
        source_knowledge: Knowledge,
        target_knowledge: Knowledge,
        op_user_id: int,
):
    one_dict = one.model_dump()
    one_dict.pop("id")
    one_dict.pop("update_time")
    one_dict["user_id"] = op_user_id
    one_dict["knowledge_id"] = target_knowledge.id
    one_dict["status"] = KnowledgeFileStatus.PROCESSING.value

    source_file_pdf = one.id
    source_file = one.object_name
    source_file_ext = one.object_name.split('.')[-1]
    bbox_file = one.bbox_object_name

    knowledge_new = KnowledgeFile(**one_dict)
    knowledge_new = KnowledgeFileDao.add_file(knowledge_new)

    # 迁移 file
    try:
        target_source_file = KnowledgeUtils.get_knowledge_file_object_name(knowledge_new.id, knowledge_new.file_name)

        minio_client = get_minio_storage_sync()

        # 拷贝源文件
        if minio_client.object_exists_sync(minio_client.bucket, source_file):
            minio_client.copy_object_sync(source_bucket=minio_client.bucket, source_object=source_file,
                                          dest_object=target_source_file, dest_bucket=minio_client.bucket)
        knowledge_new.object_name = target_source_file

        # 拷贝生成的pdf文件
        if minio_client.object_exists_sync(minio_client.bucket, f"{source_file_pdf}"):
            minio_client.copy_object_sync(source_bucket=minio_client.bucket, source_object=f"{source_file_pdf}",
                                          dest_object=f"{knowledge_new.id}", dest_bucket=minio_client.bucket)

        # 拷贝bbox文件
        if minio_client.object_exists_sync(object_name=bbox_file):
            target_bbox_file = KnowledgeUtils.get_knowledge_bbox_file_object_name(knowledge_new.id)
            minio_client.copy_object_sync(source_bucket=minio_client.bucket, source_object=bbox_file,
                                          dest_object=target_bbox_file, dest_bucket=minio_client.bucket)
            knowledge_new.bbox_object_name = target_bbox_file

        preview_file = None
        target_preview_file = None
        # 拷贝预览文件
        if source_file_ext in ['doc', 'ppt', 'pptx']:
            preview_file = KnowledgeUtils.get_knowledge_preview_file_object_name(one.id, one.file_name)
            target_preview_file = KnowledgeUtils.get_knowledge_preview_file_object_name(knowledge_new.id,
                                                                                        knowledge_new.file_name)
        if preview_file and target_preview_file:
            if minio_client.object_exists_sync(minio_client.bucket, preview_file):
                minio_client.copy_object_sync(source_bucket=minio_client.bucket, source_object=preview_file,
                                              dest_object=target_preview_file, dest_bucket=minio_client.bucket)

    except Exception as e:
        logger.exception(f"copy_file_error file_id={knowledge_new.id}")
        knowledge_new.remark = KnowledgeFileFailedError(exception=e).to_json_str()
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
        logger.error("source={} new={} e={}", one.id, knowledge_new.id, e)
        knowledge_new.remark = KnowledgeFileFailedError(exception=e).to_json_str()
        knowledge_new.status = KnowledgeFileStatus.FAILED.value
        KnowledgeFileDao.update(knowledge_new)


def copy_vector(
        source_konwledge: Knowledge,
        target_knowledge: Knowledge,
        source_file_id: int,
        target_file_id: int,
):
    # 迁移 vectordb
    embedding = FakeEmbedding()
    source_col = source_konwledge.collection_name
    source_milvus: Milvus = decide_vectorstores(source_col, "Milvus", embedding)
    # 当前es 不包含vector
    fields = [s.name for s in source_milvus.col.schema.fields if s.name != "pk"]
    source_data = source_milvus.col.query(
        expr=f"document_id=={source_file_id} && knowledge_id=={source_konwledge.id}",
        output_fields=fields,
    )
    for data in source_data:
        data["knowledge_id"] = target_knowledge.id
        data["document_id"] = target_file_id
    milvus_db: Milvus = decide_vectorstores(
        target_knowledge.collection_name, "Milvus", embedding
    )
    # 首次新建一个 collection
    if milvus_db.col is None:
        new_col = Collection(name=target_knowledge.collection_name, schema=source_milvus.col.schema,
                             using=source_milvus.alias,
                             consistency_level=source_milvus.consistency_level)
        milvus_db: Milvus = decide_vectorstores(
            target_knowledge.collection_name, "Milvus", embedding
        )
    if milvus_db:
        insert_milvus(source_data, fields, milvus_db)

    es_db = decide_vectorstores(
        target_knowledge.index_name, "ElasticKeywordsSearch", embedding
    )
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
            logger.error(
                "Failed to insert batch starting at entity: %s/%s", i, total_count
            )
            raise e
    logger.info("copy_done pk_size={}", len(res_list))


def insert_es(li: List, target: ElasticKeywordsSearch):
    from elasticsearch.helpers import bulk

    res_list = []
    ids = [generate_uuid() for _ in li]
    requests = []
    for i, data in enumerate(li):
        text = data.pop("text")
        data.pop("vector", "")  # es 不包含vector
        metadata = data
        request = {
            "_op_type": "index",
            "_index": target.index_name,
            "text": text,
            "metadata": metadata,
            "_id": ids[i],
        }
        requests.append(request)
    bulk(target.client, requests)

    target.client.indices.refresh(index=target.index_name)
    logger.info("copy_es_done pk_size={}", len(res_list))


@bisheng_celery.task(acks_late=True)
def parse_knowledge_file_celery(file_id: int, preview_cache_key: str = None, callback_url: str = None):
    """ 异步解析一个入库成功的文件 """
    trace_id_var.set(f'parse_file_{file_id}')
    logger.info(
        f"parse_knowledge_file_celery start preview_cache_key={preview_cache_key}, callback_url={callback_url}")
    try:
        # 入库成功后，再此判断文件信息是否还存在，不存在则删除
        _, knowledge = _parse_knowledge_file(file_id, preview_cache_key, callback_url)
    except Exception as e:
        logger.error("parse_knowledge_file_celery error: {}", str(e))
    finally:
        logger.debug(f"delete_knowledge_file_celery start file_id={file_id}")
        db_file = KnowledgeFileDao.get_file_by_ids([file_id])
        if not db_file:
            # 不存在则可能在解析过程中被删除了，需要删掉向量库的数据
            delete_vector_files([db_file.id], knowledge)


def _parse_knowledge_file(file_id: int, preview_cache_key: str = None, callback_url: str = None):
    db_file = KnowledgeFileDao.get_file_by_ids([file_id])
    if not db_file:
        logger.error("file_id={} not found in db", file_id)
        return
    db_file = db_file[0]
    if db_file.status not in [KnowledgeFileStatus.PROCESSING.value, KnowledgeFileStatus.WAITING.value]:
        logger.error(
            "file_id={} status={} not processing, skip parse",
            file_id,
            db_file.status,
        )
        return
    db_knowledge = KnowledgeDao.query_by_id(db_file.knowledge_id)
    if not db_knowledge:
        logger.error("knowledge_id={} not found", db_file.knowledge_id)
        return
    if db_file.status == KnowledgeFileStatus.WAITING.value:
        db_file.status = KnowledgeFileStatus.PROCESSING.value
        KnowledgeFileDao.update_file_status([db_file.id], KnowledgeFileStatus.PROCESSING)

    # 获取切分规则
    file_rule = FileProcessBase(**json.loads(db_file.split_rule))
    logger.debug("parse_knowledge_file_celery_start", file_id)
    process_file_task(db_knowledge,
                      db_files=[db_file],
                      separator=file_rule.separator,
                      separator_rule=file_rule.separator_rule,
                      chunk_size=file_rule.chunk_size,
                      chunk_overlap=file_rule.chunk_overlap,
                      callback_url=callback_url,
                      extra_metadata=db_file.user_metadata,
                      preview_cache_keys=[preview_cache_key],
                      retain_images=file_rule.retain_images,
                      enable_formula=file_rule.enable_formula,
                      force_ocr=file_rule.force_ocr,
                      filter_page_header_footer=file_rule.filter_page_header_footer)
    logger.debug("parse_knowledge_file_celery_over", file_id)
    return db_file, db_knowledge


@bisheng_celery.task(acks_late=True)
def retry_knowledge_file_celery(file_id: int, preview_cache_key: str = None, callback_url: str = None):
    """ 重试解析一个入库失败或者重名的文件 """
    trace_id_var.set(f'retry_knowledge_file_{file_id}')
    logger.info("retry_knowledge_file_celery start file_id={}", file_id)
    try:
        delete_knowledge_file_vectors(
            file_ids=[file_id], clear_minio=False
        )
    except Exception as e:
        logger.exception("retry_knowledge_file_celery delete vectors error: {}", str(e))
        KnowledgeFileDao.update_file_status([file_id], KnowledgeFileStatus.FAILED,
                                            KnowledgeFileFailedError(exception=e).to_json_str())
        return
    try:
        _parse_knowledge_file(file_id, preview_cache_key, callback_url)
    except Exception as e:
        logger.error("retry_knowledge_file_celery error: {}", str(e))


@bisheng_celery.task()
def delete_knowledge_file_celery(file_ids: List[int], knowledge_id: int, clear_minio: bool = True):
    """ 异步删除知识文件及其向量 """
    trace_id_var.set(f'delete_knowledge_file_{file_ids}')
    logger.info("delete_knowledge_file_celery start file_ids={}", file_ids)
    try:
        knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge:
            logger.warning(f"knowledge_id={knowledge_id} is deleted, skip delete file")
            return
        delete_vector_files(file_ids, knowledge)
    except Exception as e:
        logger.error("delete_knowledge_file_celery error: {}", str(e))
