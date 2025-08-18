from typing import List

from loguru import logger
from pymilvus import Collection

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
            for file in files:
                file.status = KnowledgeFileStatus.REBUILDING.value
                KnowledgeFileDao.update(file)

            logger.info(f"Updated {len(files)} files to rebuilding status")

            # 2. 根据拿到collection_name去milvus中删除向量存储
            _delete_milvus_collection(knowledge)

            # 3. 根据index_name从es中拿到chunk信息，重新embedding插入milvus
            success_files, failed_files = _rebuild_embeddings(knowledge, files, new_model_id)

            # 4. 更新文件状态
            for file_id in success_files:
                file = next((f for f in files if f.id == file_id), None)
                if file:
                    file.status = KnowledgeFileStatus.SUCCESS.value
                    KnowledgeFileDao.update(file)

            for file_id in failed_files:
                file = next((f for f in files if f.id == file_id), None)
                if file:
                    file.status = KnowledgeFileStatus.FAILED.value
                    file.remark = "重建失败"
                    KnowledgeFileDao.update(file)

            # 5. 更新knowledge状态
            if failed_files:
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


def _delete_milvus_collection(knowledge: Knowledge):
    """删除Milvus集合"""
    try:
        embeddings = FakeEmbedding()
        vector_client = decide_vectorstores(knowledge.collection_name, "Milvus", embeddings)

        if isinstance(vector_client.col, Collection):
            logger.info(f"Deleting milvus collection: {knowledge.collection_name}")
            vector_client.col.drop(timeout=10)
            logger.info(f"Successfully deleted milvus collection: {knowledge.collection_name}")
        else:
            logger.warning(f"Milvus collection not found: {knowledge.collection_name}")

        vector_client.close_connection(vector_client.alias)

    except Exception as e:
        logger.warning(f"Failed to delete milvus collection {knowledge.collection_name}: {str(e)}")
        # 即使删除失败也继续执行，因为可能集合本来就不存在


def _rebuild_embeddings(knowledge: Knowledge, files: List[KnowledgeFile], new_model_id: str) -> tuple[
    List[int], List[int]]:
    """
    重建embeddings
    
    Returns:
        tuple: (成功的文件ID列表, 失败的文件ID列表)
    """
    success_files = []
    failed_files = []

    try:
        # 获取ES中的chunk信息
        index_name = knowledge.index_name or knowledge.collection_name
        embeddings = FakeEmbedding()
        es_client = decide_vectorstores(index_name, "ElasticKeywordsSearch", embeddings)

        # 获取新的embedding模型
        new_embeddings = decide_embeddings(new_model_id)

        # 为每个文件重新生成embeddings
        for file in files:
            try:
                logger.info(f"Rebuilding embeddings for file_id={file.id}")

                # 先检查ES索引是否存在
                if not es_client.client.indices.exists(index=index_name):
                    logger.error(f"ES index {index_name} does not exist")
                    failed_files.append(file.id)
                    continue

                # 获取ES索引的mapping信息（用于调试）
                try:
                    mapping = es_client.client.indices.get_mapping(index=index_name)
                    logger.debug(f"ES index mapping for {index_name}: {mapping}")
                except Exception as e:
                    logger.warning(f"Failed to get ES mapping: {str(e)}")

                # 从ES中获取该文件的所有chunks
                search_query = {
                    "query": {
                        "match": {
                            "metadata.file_id": file.id
                        }
                    },
                    "size": 10000  # 假设单个文件不会超过10000个chunk
                }

                logger.debug(f"ES search query: {search_query}")

                response = es_client.client.search(index=index_name, body=search_query)
                chunks = response.get("hits", {}).get("hits", [])

                logger.info(f"Found {len(chunks)} chunks in ES for file_id={file.id}")

                if not chunks:
                    logger.warning(f"No chunks found for file_id={file.id}")
                    success_files.append(file.id)  # 认为是成功的，因为没有数据需要处理
                    continue

                # 提取文本和元数据
                texts = []
                metadatas = []
                for chunk in chunks:
                    source = chunk["_source"]
                    texts.append(source["text"])
                    metadatas.append(source["metadata"])

                logger.info(f"Found {len(texts)} chunks for file_id={file.id}")

                # 重新生成embeddings并插入Milvus
                vector_client = decide_vectorstores(knowledge.collection_name, "Milvus", new_embeddings)
                vector_client.add_texts(texts=texts, metadatas=metadatas)
                vector_client.close_connection(vector_client.alias)

                success_files.append(file.id)
                logger.info(f"Successfully rebuilt embeddings for file_id={file.id}")

            except Exception as e:
                logger.exception(f"Failed to rebuild embeddings for file_id={file.id}: {str(e)}")
                failed_files.append(file.id)

    except Exception as e:
        logger.exception(f"Failed to rebuild embeddings: {str(e)}")
        # 如果整个过程失败，则所有文件都标记为失败
        failed_files.extend([f.id for f in files if f.id not in success_files])

    return success_files, failed_files
