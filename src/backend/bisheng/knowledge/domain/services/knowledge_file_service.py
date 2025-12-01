import copy
from typing import List

from loguru import logger

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeFileNotExistError, KnowledgeMetadataFieldNotExistError, \
    KnowledgeMetadataFieldExistError, KnowledgeMetadataValueTypeConvertError
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.domain import utils
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.schemas.knowledge_file_schema import KnowledgeFileInfoRes
from bisheng.knowledge.domain.schemas.knowledge_schema import ModifyKnowledgeFileMetaDataReq, MetadataField
from bisheng.open_endpoints.domain.schemas.knowledge import DeleteUserMetadataReq
from bisheng.user.domain.models.user import UserDao


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

        create_user = await UserDao.aget_user(user_id=knowledge_file_model.user_id)
        update_user = await UserDao.aget_user(user_id=knowledge_file_model.updater_id)

        knowledge_file_info_res = KnowledgeFileInfoRes.from_orm_extra(model=knowledge_file_model,
                                                                      extra={
                                                                          'creat_user': create_user.user_name if create_user else '',
                                                                          'update_user': update_user.user_name if update_user else create_user.user_name
                                                                      })

        if not knowledge_file_info_res.user_metadata:
            metadata_field_dict = {item['field_name']: MetadataField(**item) for item in
                                   knowledge_model.metadata_fields or []}

            for key, item in knowledge_file_info_res.user_metadata.items():
                if key in metadata_field_dict:
                    item['field_type'] = metadata_field_dict[key].field_type
        return knowledge_file_info_res

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
            knowledge_file_model.user_metadata = {}

        # 新建一个字典来存储更新后的元数据
        new_current_user_metadata = {}

        for item in modify_file_metadata_req.user_metadata_list:
            if item.field_name in metadata_field_dict.keys():
                item_dict = item.model_dump()
                # 数据类型转换
                try:
                    field_type = metadata_field_dict[item.field_name].field_type
                    field_value = utils.metadata_value_type_convert(
                        value=item_dict['field_value'], target_type=field_type)
                    item_dict['field_value'] = field_value
                except Exception as e:
                    logger.error(f"Metadata value type conversion error: {e}")
                    continue
                item_dict['field_type'] = metadata_field_dict[item.field_name].field_type
                item_dict.pop('field_name')
                new_current_user_metadata[item.field_name] = item_dict

        # 更新知识文件的用户元数据
        knowledge_file_model.user_metadata = new_current_user_metadata
        knowledge_file_model.updater_id = login_user.user_id

        knowledge_file_model = await self.knowledge_file_repository.update(knowledge_file_model)

        user_metadata = {key: value.get('field_value') for key, value in knowledge_file_model.user_metadata.items()}

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

        if not knowledge_model:
            raise KnowledgeFileNotExistError()

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        metadata_field_dict = {item['field_name']: MetadataField(**item) for item in
                               knowledge_model.metadata_fields or []}

        existing_files = await self.knowledge_file_repository.find_by_ids(
            [req.knowledge_file_id for req in add_file_metadata_req])

        existing_files_dict = {file.id: file for file in existing_files}

        updated_knowledge_files = []

        for modify_file_metadata_req in add_file_metadata_req:
            knowledge_file_model = existing_files_dict.get(modify_file_metadata_req.knowledge_file_id)

            # Check if knowledge file exists
            if not knowledge_file_model:
                raise KnowledgeFileNotExistError(
                    msg=f"知识库文件ID:{modify_file_metadata_req.knowledge_file_id} 不存在")

            # Initialize metadata if it's None
            if knowledge_file_model.user_metadata is None:
                knowledge_file_model.user_metadata = {}

            current_user_metadata = copy.deepcopy(knowledge_file_model.user_metadata)

            for item in modify_file_metadata_req.user_metadata_list:
                if item.field_name not in metadata_field_dict.keys():
                    raise KnowledgeMetadataFieldNotExistError(field_name=item.field_name)

                elif item.field_name in current_user_metadata.keys():
                    raise KnowledgeMetadataFieldExistError(
                        field_name=item.field_name,
                        msg=f"知识库文件ID:{modify_file_metadata_req.knowledge_file_id} 已存在元数据字段:{item.field_name}"
                    )

                item_dict = item.model_dump()
                # 数据类型转换
                try:
                    field_type = metadata_field_dict[item.field_name].field_type
                    field_value = utils.metadata_value_type_convert(
                        value=item_dict['field_value'], target_type=field_type)
                    item_dict['field_value'] = field_value
                except Exception as e:
                    raise KnowledgeMetadataValueTypeConvertError(
                        msg=f"元数据字段 {item.field_name} 值类型转换错误: {e}")

                item_dict['field_type'] = metadata_field_dict[item.field_name].field_type
                item_dict.pop('field_name')
                current_user_metadata[item.field_name] = item_dict

            # 更新知识文件的用户元数据
            knowledge_file_model.user_metadata = current_user_metadata
            knowledge_file_model.updater_id = login_user.user_id

            updated_knowledge_files.append(knowledge_file_model)

        # 批量更新知识文件
        for knowledge_file_model in updated_knowledge_files:
            knowledge_file_model = await self.knowledge_file_repository.update(knowledge_file_model)

            user_metadata = {key: value.get('field_value') for key, value in knowledge_file_model.user_metadata.items()}

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

        return updated_knowledge_files

    # Batch modify file user metadata
    async def batch_modify_file_user_metadata(self, login_user: 'UserPayload',
                                              knowledge_id: int,
                                              modify_file_metadata_reqs: 'List[ModifyKnowledgeFileMetaDataReq]'):
        """批量修改知识文件元数据"""
        knowledge_model = await self.knowledge_repository.find_by_id(
            entity_id=knowledge_id)

        if not knowledge_model:
            raise KnowledgeFileNotExistError()

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        metadata_field_dict = {item['field_name']: MetadataField(**item) for item in
                               knowledge_model.metadata_fields or []}

        existing_files = await self.knowledge_file_repository.find_by_ids(
            [req.knowledge_file_id for req in modify_file_metadata_reqs])

        existing_files_dict = {file.id: file for file in existing_files}

        updated_knowledge_files = []

        for modify_file_metadata_req in modify_file_metadata_reqs:
            knowledge_file_model = existing_files_dict.get(modify_file_metadata_req.knowledge_file_id)

            if not knowledge_file_model:
                raise KnowledgeFileNotExistError(
                    msg=f"知识库文件ID:{modify_file_metadata_req.knowledge_file_id} 不存在")

            # Initialize metadata if it's None
            if knowledge_file_model.user_metadata is None:
                knowledge_file_model.user_metadata = {}

            current_user_metadata = copy.deepcopy(knowledge_file_model.user_metadata)

            # 更新知识文件的用户元数据
            for item in modify_file_metadata_req.user_metadata_list:

                if item.field_name not in metadata_field_dict.keys():
                    raise KnowledgeMetadataFieldNotExistError(field_name=item.field_name)

                if item.field_name not in current_user_metadata.keys():
                    raise KnowledgeMetadataFieldNotExistError(
                        field_name=item.field_name,
                        msg=f"知识库文件ID:{modify_file_metadata_req.knowledge_file_id} 不存在元数据字段:{item.field_name}"
                    )

                existing_item = current_user_metadata.get(item.field_name)
                try:
                    # 数据类型
                    field_type = metadata_field_dict[item.field_name].field_type
                    # 更新已有字段的值和更新时间
                    field_value = utils.metadata_value_type_convert(
                        value=item.field_value, target_type=field_type)
                    existing_item['field_value'] = field_value
                    current_user_metadata[item.field_name] = existing_item
                except Exception as e:
                    raise KnowledgeMetadataValueTypeConvertError(
                        msg=f"元数据字段 {item.field_name} 值类型转换错误: {e}")

            knowledge_file_model.user_metadata = current_user_metadata
            knowledge_file_model.updater_id = login_user.user_id

            updated_knowledge_files.append(knowledge_file_model)

        # 批量更新知识文件
        for knowledge_file_model in updated_knowledge_files:
            knowledge_file_model = await self.knowledge_file_repository.update(knowledge_file_model)

            user_metadata = {key: value.get('field_value') for key, value in knowledge_file_model.user_metadata.items()}
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

        if not knowledge_model:
            raise KnowledgeFileNotExistError()

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        existing_files = await self.knowledge_file_repository.find_by_ids(
            [req.knowledge_file_id for req in delete_user_metadata_req])

        existing_files_dict = {file.id: file for file in existing_files}

        updated_knowledge_files = []
        for delete_metadata_req in delete_user_metadata_req:
            knowledge_file_model = existing_files_dict.get(delete_metadata_req.knowledge_file_id)

            if not knowledge_file_model:
                raise KnowledgeFileNotExistError(
                    msg=f"知识库文件ID:{delete_metadata_req.knowledge_file_id} 不存在")

            current_user_metadata = copy.deepcopy(knowledge_file_model.user_metadata) or {}

            # 删除指定的元数据字段
            for field_name in delete_metadata_req.field_names:

                if field_name not in current_user_metadata.keys():
                    raise KnowledgeMetadataFieldNotExistError(
                        field_name=field_name,
                        msg=f"知识库文件ID:{delete_metadata_req.knowledge_file_id} 不存在元数据字段:{field_name}"
                    )

                current_user_metadata.pop(field_name)

            knowledge_file_model.user_metadata = current_user_metadata
            knowledge_file_model.updater_id = login_user.user_id

            updated_knowledge_files.append(knowledge_file_model)

        # 批量更新知识文件
        for knowledge_file_model in updated_knowledge_files:
            knowledge_file_model = await self.knowledge_file_repository.update(knowledge_file_model)

            user_metadata = {key: value.get('field_value') for key, value in knowledge_file_model.user_metadata.items()}

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

        if not knowledge_model:
            raise KnowledgeFileNotExistError()

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE
        ):
            raise UnAuthorizedError()

        user_metadata_dict = await self.knowledge_file_repository.get_user_metadata_by_knowledge_file_ids(
            knowledge_id=knowledge_id,
            knowledge_file_ids=knowledge_file_ids)

        return user_metadata_dict
