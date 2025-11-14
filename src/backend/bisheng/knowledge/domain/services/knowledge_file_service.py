from loguru import logger
from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeFileNotExistError
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.schemas.knowledge_schema import ModifyKnowledgeFileMetaDataReq
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository


class KnowledgeFileService:
    """知识文件服务类"""

    def __init__(self, knowledge_file_repository: 'KnowledgeFileRepository',
                 knowledge_repository: 'KnowledgeRepository'):
        self.knowledge_file_repository = knowledge_file_repository
        self.knowledge_repository = knowledge_repository

    @staticmethod
    async def modify_milvus_file_user_metadata(knowledge_model, knowledge_file_id, user_metadata: dict):
        """修改 Milvus 中文件的用户元数据"""
        vector_client = await KnowledgeRag.init_knowledge_milvus_vectorstore(knowledge=knowledge_model,
                                                                             metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)

        # 先查出所有数据
        search_result = await vector_client.aclient.query(collection_name=knowledge_model.collection_name,
                                                          filter=f"document_id == {knowledge_file_id}", limit=10000)

        # 修改用户元数据
        for item in search_result:
            item["user_metadata"] = user_metadata

        # 批量更新数据
        await vector_client.aclient.upsert(collection_name=vector_client.collection_name,
                                           data=search_result)

    @staticmethod
    async def modify_elasticsearch_file_user_metadata(knowledge_model, knowledge_file_id, user_metadata: dict):
        """修改 Elasticsearch 中文件的用户元数据"""
        es_client = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=knowledge_model,
                                                                     metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)

        # 使用 update_by_query 来更新符合条件的文档
        res = await es_client.client.update_by_query(
            index=knowledge_model.index_name,
            body={
                "script": {
                    "source": "ctx._source.metadata.user_metadata = params.user_metadata",
                    "lang": "painless",
                    "params": {"user_metadata": user_metadata}
                },
                "query": {
                    "term": {"metadata.document_id": knowledge_file_id}
                }
            }
        )

        logger.info(f"Elasticsearch update_by_query result: {res}")

    async def modify_file_user_metadata(self, login_user: 'UserPayload',
                                        modify_file_metadata_req: 'ModifyKnowledgeFileMetaDataReq'):
        """添加知识文件元数据"""
        knowledge_file_model = await self.knowledge_file_repository.find_by_id(
            entity_id=modify_file_metadata_req.knowledge_file_id)

        if not knowledge_file_model:
            raise KnowledgeFileNotExistError()

        knowledge_model = await self.knowledge_repository.find_by_id(
            entity_id=knowledge_file_model.knowledge_id)

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_file_model.knowledge_id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        # Initialize metadata if it's None
        if knowledge_file_model.user_metadata is None:
            knowledge_file_model.user_metadata = {}

        # 判断新增的元数据字段是否在知识库的元数据字段列表中
        existing_field_names = {field['field_name'] for field in knowledge_model.metadata_fields or []}

        # 过滤掉不在知识库元数据字段列表中的字段
        valid_user_metadata = {
            item.field_name: item.field_value
            for item in modify_file_metadata_req.user_metadata_list
            if item.field_name in existing_field_names
        }

        # 更新知识文件的用户元数据
        knowledge_file_model.user_metadata.update(valid_user_metadata)

        knowledge_file_model = await self.knowledge_file_repository.update(knowledge_file_model)

        # 修改 Milvus, Elasticsearch 中的对应元数据
        await self.modify_milvus_file_user_metadata(
            knowledge_model=knowledge_model,
            knowledge_file_id=knowledge_file_model.id,
            user_metadata=knowledge_file_model.user_metadata
        )

        await self.modify_elasticsearch_file_user_metadata(
            knowledge_model=knowledge_model,
            knowledge_file_id=knowledge_file_model.id,
            user_metadata=knowledge_file_model.user_metadata
        )

        return knowledge_file_model
