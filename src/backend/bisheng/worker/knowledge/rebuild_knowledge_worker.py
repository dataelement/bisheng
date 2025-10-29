from typing import List

from loguru import logger

from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import (
    decide_vectorstores,
    decide_embeddings
)
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao, KnowledgeState
from bisheng.database.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus
)
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.worker import bisheng_celery


@bisheng_celery.task(acks_late=True)
def rebuild_knowledge_celery(knowledge_id: int, new_model_id: str) -> str:
    """
    重建知识库的异步任务
    
    Args:
        knowledge_id: 知识库ID
        new_model_id: 新的embedding模型ID
        
    Returns:
        str: 任务执行结果
    """
    with logger.contextualize(trace_id=f'rebuild_knowledge_{knowledge_id}'):
        logger.info(f"rebuild_knowledge_celery start knowledge_id={knowledge_id} new_model_id={new_model_id}")

        try:
            # 获取知识库信息
            knowledge = KnowledgeDao.query_by_id(knowledge_id)
            if not knowledge:
                logger.error(f"knowledge_id={knowledge_id} not found")
                return f"knowledge {knowledge_id} not found"

            # 1. 根据knowledge_id找到knowledgefile表中所有status=2和status=4的文件，把status改为4
            files = KnowledgeFileDao.get_files_by_multiple_status(
                knowledge_id,
                [KnowledgeFileStatus.SUCCESS.value, KnowledgeFileStatus.REBUILDING.value]
            )

            if not files:
                logger.info(f"knowledge_id={knowledge_id} has no success files")
                # 直接更新知识库状态为成功
                knowledge.state = KnowledgeState.PUBLISHED.value
                KnowledgeDao.update_one(knowledge)
                return f"knowledge {knowledge_id} rebuild completed (no files)"

            # 更新文件状态为重建中
            file_ids = [f.id for f in files]
            KnowledgeFileDao.update_status_bulk(file_ids, KnowledgeFileStatus.REBUILDING)

            logger.info(f"Updated {len(files)} files to rebuilding status")

            # 2. 根据拿到collection_name去milvus中删除向量存储
            KnowledgeService.delete_knowledge_file_in_vector(knowledge=knowledge, del_es=False)

            # 3. 根据index_name从es中拿到chunk信息，重新embedding插入milvus
            success_files, failed_files = _rebuild_embeddings(knowledge, files, new_model_id)

            # 4. 更新文件状态
            KnowledgeFileDao.update_status_bulk(success_files, KnowledgeFileStatus.SUCCESS)

            for file_id in failed_files:
                file = next((f for f in files if f.id == file_id), None)
                if file:
                    file.status = KnowledgeFileStatus.FAILED.value
                    file.remark = "重建失败"
                    KnowledgeFileDao.update(file)

            # 5. 更新knowledge状态
            if failed_files:

                # 删除es索引和milvus集合，避免数据不一致
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
            # 异步任务期间出现意外把knowledge置为4
            try:
                knowledge = KnowledgeDao.query_by_id(knowledge_id)
                if knowledge:
                    knowledge.state = KnowledgeState.FAILED.value
                    KnowledgeDao.update_one(knowledge)
            except Exception as e2:
                logger.exception(f"Failed to update knowledge state after error: {str(e2)}")

            raise e


def _delete_es_files(knowledge: Knowledge, file_ids: List[int]):
    """删除ES中的文件数据"""
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
                        "metadata.file_id": file_id
                    }
                }
            }
            response = es_client.client.delete_by_query(index=index_name, body=delete_query)
            deleted = response.get("deleted", 0)
            logger.info(f"Deleted {deleted} documents from ES for file_id={file_id}")

    except Exception as e:
        logger.exception(f"Failed to delete ES files for knowledge_id={knowledge.id}: {str(e)}")


def _rebuild_embeddings(knowledge: Knowledge, files: List[KnowledgeFile], new_model_id: str) -> tuple[
    List[int], List[int]]:
    """
    重建embeddings

    Returns:
        tuple: (成功的文件ID列表, 失败的文件ID列表)
    """
    success_files = []
    failed_files = []
    vector_client = None

    try:
        # 获取ES中的chunk信息
        index_name = knowledge.index_name or knowledge.collection_name
        embeddings = FakeEmbedding()
        es_client = decide_vectorstores(index_name, "ElasticKeywordsSearch", embeddings)

        # 获取新的embedding模型并创建Milvus客户端
        logger.info(f"[DEBUG] 开始初始化新的embedding模型，model_id={new_model_id}")
        new_embeddings = decide_embeddings(new_model_id)
        logger.info(
            f"[DEBUG] 成功创建embedding模型实例: {type(new_embeddings).__name__}, model_id={getattr(new_embeddings, 'model_id', 'unknown')}")

        # 测试embedding模型是否可用
        try:
            test_result = new_embeddings.embed_query("测试文本")
            logger.info(f"[DEBUG] Embedding模型测试成功，返回维度: {len(test_result) if test_result else 'None'}")
        except Exception as e:
            logger.error(f"[DEBUG] Embedding模型测试失败: {str(e)}")
            # 模型测试失败应该终止整个流程，而不是继续
            raise Exception(f"Embedding模型不可用: {str(e)}")

        vector_client = decide_vectorstores(knowledge.collection_name, "Milvus", new_embeddings)
        logger.info(f"[DEBUG] 成功创建Milvus客户端，collection_name={knowledge.collection_name}")

        # 检查ES索引是否存在（提前检查，避免在循环中重复检查）
        if not es_client.client.indices.exists(index=index_name):
            logger.error(f"ES index {index_name} does not exist")
            # 索引不存在，所有文件都失败
            failed_files = [f.id for f in files]
            return success_files, failed_files

        # 获取ES索引的mapping信息（用于调试）
        try:
            mapping = es_client.client.indices.get_mapping(index=index_name)
            logger.debug(f"ES index mapping for {index_name}: {mapping}")
        except Exception as e:
            logger.warning(f"Failed to get ES mapping: {str(e)}")

        # 为每个文件重新生成embeddings
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
        # 如果整个过程失败，则所有未成功的文件都标记为失败
        failed_files.extend([f.id for f in files if f.id not in success_files])

    finally:
        # 确保关闭Milvus连接
        if vector_client is not None:
            try:
                vector_client.close_connection(vector_client.alias)
                logger.info(f"[DEBUG] 已关闭Milvus连接: {vector_client.alias}")
            except Exception as close_error:
                logger.warning(f"Failed to close milvus connection: {str(close_error)}")

    return success_files, failed_files


def _process_single_file(file, es_client, index_name, vector_client):
    """处理单个文件的embedding重建"""
    logger.info(f"Rebuilding embeddings for file_id={file.id}")

    # 从ES中获取该文件的所有chunks
    search_query = {
        "query": {
            "match": {
                "metadata.file_id": file.id
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
        return True  # 没有数据需要处理，视为成功

    # 提取文本和元数据
    texts = []
    metadatas = []
    for chunk in chunks:
        source = chunk["_source"]
        texts.append(source["text"])
        # 移除pk字段，避免插入Milvus时冲突
        if "pk" in source["metadata"]:
            del source["metadata"]["pk"]

        metadatas.append(source["metadata"])

    logger.info(f"Found {len(texts)} chunks for file_id={file.id}")

    # 插入数据到Milvus
    logger.info(f"[DEBUG] 即将调用vector_client.add_texts，texts数量={len(texts)}")
    logger.info(f"[DEBUG] 第一个文本示例: {texts[0][:100] if texts else 'No texts'}...")

    try:
        vector_client.add_texts(texts=texts, metadatas=metadatas)
        logger.info(f"[DEBUG] vector_client.add_texts调用成功")
        return True
    except Exception as add_error:
        logger.error(f"[DEBUG] vector_client.add_texts调用失败: {str(add_error)}")
        raise add_error
