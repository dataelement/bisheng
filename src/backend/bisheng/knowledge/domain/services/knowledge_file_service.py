import copy
from typing import List

from loguru import logger
from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeFileNotExistError
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.domain import utils
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.schemas.knowledge_schema import ModifyKnowledgeFileMetaDataReq, MetadataField
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.open_endpoints.domain.schemas.knowledge import DeleteUserMetadataReq


class KnowledgeFileService:
    """知识文件服务类"""

    def __init__(self, knowledge_file_repository: 'KnowledgeFileRepository',
                 knowledge_repository: 'KnowledgeRepository'):
        self.knowledge_file_repository = knowledge_file_repository
        self.knowledge_repository = knowledge_repository

    async def get_knowledge_file_info(self, login_user: 'UserPayload', knowledge_file_id: int):
        """获取知识文件信息"""
        knowledge_file_model = await self.knowledge_file_repository.find_by_id(
            entity_id=knowledge_file_id)

        if not knowledge_file_model:
            raise KnowledgeFileNotExistError()

        knowledge_model = await self.knowledge_repository.find_by_id(
            entity_id=knowledge_file_model.knowledge_id)

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_file_model.knowledge_id), AccessType.KNOWLEDGE
        ):
            raise UnAuthorizedError()

        return knowledge_file_model

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

        metadata_field_dict = {item['field_name']: MetadataField(**item) for item in
                               knowledge_model.metadata_fields or []}

        # Initialize metadata if it's None
        if knowledge_file_model.user_metadata is None:
            knowledge_file_model.user_metadata = []

        # 判断新增的元数据字段是否在知识库的元数据字段列表中
        existing_field_names = {field['field_name'] for field in knowledge_model.metadata_fields or []}

        # 过滤掉不在知识库元数据字段列表中的字段
        valid_user_metadata = []

        for item in modify_file_metadata_req.user_metadata_list:
            if item.field_name in existing_field_names:
                item_dict = item.model_dump()
                # 数据类型转换
                try:
                    field_type = metadata_field_dict[item.field_name].field_type
                    item_dict['field_value'] = utils.metadata_value_type_convert(
                        value=item_dict['field_value'], target_type=field_type)
                except Exception as e:
                    logger.error(f"Metadata value type conversion error: {e}")
                    continue
                valid_user_metadata.append(item_dict)

        # 更新知识文件的用户元数据
        knowledge_file_model.user_metadata = valid_user_metadata
        knowledge_file_model.updater_id = login_user.user_id

        knowledge_file_model = await self.knowledge_file_repository.update(knowledge_file_model)

        user_metadata = {item['field_name']: item.get('field_value') for item in knowledge_file_model.user_metadata}

        # 修改 Milvus, Elasticsearch 中的对应元数据
        await self.modify_milvus_file_user_metadata(
            knowledge_model=knowledge_model,
            knowledge_file_id=knowledge_file_model.id,
            user_metadata=user_metadata
        )

        await self.modify_elasticsearch_file_user_metadata(
            knowledge_model=knowledge_model,
            knowledge_file_id=knowledge_file_model.id,
            user_metadata=user_metadata
        )

        return knowledge_file_model

    async def add_file_user_metadata(self, login_user: 'UserPayload', knowledge_id: int,
                                     add_file_metadata_req: 'List[ModifyKnowledgeFileMetaDataReq]'):
        """添加知识文件元数据"""

        knowledge_model = await self.knowledge_repository.find_by_id(
            entity_id=knowledge_id)

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        metadata_field_dict = {item['field_name']: MetadataField(**item) for item in
                               knowledge_model.metadata_fields or []}

        updated_knowledge_files = []

        for modify_file_metadata_req in add_file_metadata_req:
            knowledge_file_model = await self.knowledge_file_repository.find_by_id(
                entity_id=modify_file_metadata_req.knowledge_file_id)

            if not knowledge_file_model:
                logger.warning(f"Knowledge file ID {modify_file_metadata_req.knowledge_file_id} does not exist.")
                continue

            # Initialize metadata if it's None
            if knowledge_file_model.user_metadata is None:
                knowledge_file_model.user_metadata = []

            # 判断新增的元数据字段是否在知识库的元数据字段列表中
            existing_field_names = {field['field_name'] for field in knowledge_model.metadata_fields or []}

            current_user_metadata = copy.deepcopy(knowledge_file_model.user_metadata)

            # 过滤掉不在知识库元数据字段列表中的字段
            valid_user_metadata = [
                item.model_dump()
                for item in modify_file_metadata_req.user_metadata_list
                if item.field_name in existing_field_names
            ]

            # 已有的元数据字段名集合
            existing_metadata_field_names = {item['field_name'] for item in current_user_metadata}

            # 添加新的元数据字段，避免重复添加相同字段
            for item in valid_user_metadata:
                if item['field_name'] not in existing_metadata_field_names:
                    # 数据类型转换
                    try:
                        field_type = metadata_field_dict[item['field_name']].field_type
                        item['field_value'] = utils.metadata_value_type_convert(
                            value=item['field_value'], target_type=field_type)
                    except Exception as e:
                        logger.error(f"Metadata value type conversion error: {e}")
                        continue
                    current_user_metadata.append(item)

            # 更新知识文件的用户元数据
            knowledge_file_model.user_metadata = current_user_metadata
            knowledge_file_model.updater_id = login_user.user_id

            knowledge_file_model = await self.knowledge_file_repository.update(knowledge_file_model)

            user_metadata = {item['field_name']: item.get('field_value') for item in knowledge_file_model.user_metadata}

            # 修改 Milvus, Elasticsearch 中的对应元数据
            await self.modify_milvus_file_user_metadata(
                knowledge_model=knowledge_model,
                knowledge_file_id=knowledge_file_model.id,
                user_metadata=user_metadata
            )

            await self.modify_elasticsearch_file_user_metadata(
                knowledge_model=knowledge_model,
                knowledge_file_id=knowledge_file_model.id,
                user_metadata=user_metadata
            )

            updated_knowledge_files.append(knowledge_file_model)

        return updated_knowledge_files

    # Batch modify file user metadata
    async def batch_modify_file_user_metadata(self, login_user: 'UserPayload',
                                              knowledge_id: int,
                                              modify_file_metadata_reqs: 'List[ModifyKnowledgeFileMetaDataReq]'):
        """批量修改知识文件元数据"""
        knowledge_model = await self.knowledge_repository.find_by_id(
            entity_id=knowledge_id)

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        metadata_field_dict = {item['field_name']: MetadataField(**item) for item in
                               knowledge_model.metadata_fields or []}

        updated_knowledge_files = []

        for modify_file_metadata_req in modify_file_metadata_reqs:
            knowledge_file_model = await self.knowledge_file_repository.find_by_id(
                entity_id=modify_file_metadata_req.knowledge_file_id)

            if not knowledge_file_model:
                logger.warning(f"Knowledge file ID {modify_file_metadata_req.knowledge_file_id} does not exist.")
                continue

            # Initialize metadata if it's None
            if knowledge_file_model.user_metadata is None:
                knowledge_file_model.user_metadata = []

            current_user_metadata = copy.deepcopy(knowledge_file_model.user_metadata)

            # 更新知识文件的用户元数据
            for item in modify_file_metadata_req.user_metadata_list:
                if item.field_name in metadata_field_dict.keys():
                    # 查找是否已存在该字段
                    existing_item = next(
                        (meta for meta in current_user_metadata if meta['field_name'] == item.field_name), None)
                    if existing_item:
                        try:
                            # 数据类型
                            field_type = metadata_field_dict[item.field_name].field_type
                            # 更新已有字段的值和更新时间
                            existing_item['field_value'] = utils.metadata_value_type_convert(
                                value=existing_item['field_value'], target_type=field_type)
                            existing_item['updated_at'] = item.updated_at
                        except Exception as e:
                            logger.error(f"Metadata value type conversion error: {e}")

            knowledge_file_model.user_metadata = current_user_metadata
            knowledge_file_model.updater_id = login_user.user_id

            knowledge_file_model = await self.knowledge_file_repository.update(knowledge_file_model)

            user_metadata = {item['field_name']: item.get('field_value') for item in knowledge_file_model.user_metadata}
            # 修改 Milvus, Elasticsearch 中的对应元数据
            await self.modify_milvus_file_user_metadata(
                knowledge_model=knowledge_model,
                knowledge_file_id=knowledge_file_model.id,
                user_metadata=user_metadata
            )

            await self.modify_elasticsearch_file_user_metadata(
                knowledge_model=knowledge_model,
                knowledge_file_id=knowledge_file_model.id,
                user_metadata=user_metadata
            )

            updated_knowledge_files.append(knowledge_file_model)

        return updated_knowledge_files

    async def batch_delete_file_user_metadata(self, login_user: 'UserPayload',
                                              knowledge_id: int,
                                              delete_user_metadata_req: 'List[DeleteUserMetadataReq]'):
        """
        批量删除知识文件元数据
        Args:
            login_user:
            knowledge_id:
            delete_user_metadata_req:

        Returns:

        """

        knowledge_model = await self.knowledge_repository.find_by_id(
            entity_id=knowledge_id)
        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        updated_knowledge_files = []
        for delete_metadata_req in delete_user_metadata_req:
            knowledge_file_model = await self.knowledge_file_repository.find_by_id(
                entity_id=delete_metadata_req.knowledge_file_id)

            if not knowledge_file_model:
                logger.warning(f"Knowledge file ID {delete_metadata_req.knowledge_file_id} does not exist.")
                continue

            if knowledge_file_model.user_metadata is None:
                knowledge_file_model.user_metadata = []

            current_user_metadata = copy.deepcopy(knowledge_file_model.user_metadata)

            # 删除指定的元数据字段
            current_user_metadata = [
                item for item in current_user_metadata
                if item['field_name'] not in delete_metadata_req.field_names
            ]

            knowledge_file_model.user_metadata = current_user_metadata
            knowledge_file_model.updater_id = login_user.user_id

            knowledge_file_model = await self.knowledge_file_repository.update(knowledge_file_model)

            user_metadata = {item['field_name']: item.get('field_value') for item in knowledge_file_model.user_metadata}

            # 修改 Milvus, Elasticsearch 中的对应元数据
            await self.modify_milvus_file_user_metadata(
                knowledge_model=knowledge_model,
                knowledge_file_id=knowledge_file_model.id,
                user_metadata=user_metadata
            )

            await self.modify_elasticsearch_file_user_metadata(
                knowledge_model=knowledge_model,
                knowledge_file_id=knowledge_file_model.id,
                user_metadata=user_metadata
            )

            updated_knowledge_files.append(knowledge_file_model)

        return updated_knowledge_files

    async def list_knowledge_file_user_metadata(self, login_user: 'UserPayload',
                                                knowledge_id: int,
                                                knowledge_file_ids: List[int]):
        """
        列出知识文件的用户元数据
        Args:
            login_user:
            knowledge_id:
            knowledge_file_ids:

        Returns:

        """

        knowledge_model = await self.knowledge_repository.find_by_id(
            entity_id=knowledge_id)

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE
        ):
            raise UnAuthorizedError()

        user_metadata_dict = await self.knowledge_file_repository.get_user_metadata_by_knowledge_file_ids(
            knowledge_id=knowledge_id,
            knowledge_file_ids=knowledge_file_ids)

        return user_metadata_dict

