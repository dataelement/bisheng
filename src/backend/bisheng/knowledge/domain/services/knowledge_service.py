import copy
from datetime import datetime

from fastapi import BackgroundTasks

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeNotExistError, KnowledgeMetadataFieldConflictError
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.schemas.knowledge_schema import AddKnowledgeMetadataFieldsReq, \
    UpdateKnowledgeMetadataFieldsReq
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.utils.util import retry_async


class KnowledgeService:
    """Service class for managing knowledge domain operations."""

    def __init__(self, knowledge_repository: 'KnowledgeRepository',
                 knowledge_file_repository: 'KnowledgeFileRepository'):
        self.knowledge_repository = knowledge_repository
        self.knowledge_file_repository = knowledge_file_repository

    async def add_metadata_fields(self, login_user: UserPayload, add_metadata_fields: AddKnowledgeMetadataFieldsReq):
        """Add metadata fields to a knowledge entity."""

        knowledge_model = await self.knowledge_repository.find_by_id(entity_id=add_metadata_fields.knowledge_id)

        if not knowledge_model:
            raise KnowledgeNotExistError()

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        # Initialize metadata_fields if it's None
        if knowledge_model.metadata_fields is None:
            knowledge_model.metadata_fields = []

        # Built field names
        built_field_names = [item.field_name for item in KNOWLEDGE_RAG_METADATA_SCHEMA]

        for field in add_metadata_fields.metadata_fields:
            if field.field_name in built_field_names:
                raise KnowledgeMetadataFieldConflictError(field_name=field.field_name)

        existing_field_names = {field["field_name"] for field in knowledge_model.metadata_fields}

        metadata_fields = copy.deepcopy(knowledge_model.metadata_fields)
        # Add new metadata fields, avoiding duplicates
        for field in add_metadata_fields.metadata_fields:
            if field.field_name not in existing_field_names:
                metadata_fields.append(field.model_dump())

        knowledge_model.metadata_fields = metadata_fields

        knowledge_model = await self.knowledge_repository.update(knowledge_model)

        return knowledge_model

    #  Update Milvus and Elasticsearch metadata field names
    async def update_vectorstore_metadata_field_names(self, knowledge_model, field_name_map):
        """Update metadata field names in Milvus and Elasticsearch vector stores."""
        # Update Milvus metadata field names
        # milvus_vectorstore = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(knowledge=knowledge_model)
        # Implement Milvus metadata field name update logic here

        # Update Elasticsearch metadata field names
        # es_vectorstore = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge_model)
        # Implement Elasticsearch metadata field name update logic here

        knowledge_model_files = await self.knowledge_file_repository.find_all(knowledge_id=knowledge_model.id)

        vector_client = await KnowledgeRag.init_knowledge_milvus_vectorstore(knowledge=knowledge_model,
                                                                             metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)

        es_client = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=knowledge_model,
                                                                     metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)

        # 请求milvus
        @retry_async(delay=3)
        async def request_milvus(new_data):
            # 批量更新数据
            await vector_client.aclient.upsert(collection_name=vector_client.collection_name, data=new_data)

        # 请求es
        @retry_async(delay=3)
        async def request_es(request_body):
            await es_client.client.update_by_query(
                index=knowledge_model.index_name,
                body=request_body
            )

        for knowledge_file in knowledge_model_files:
            # Update Milvus metadata
            # Implement Milvus metadata field name update logic for each knowledge file here

            # Query all vectors in this knowledge file in Milvus.
            search_result = await vector_client.aclient.query(collection_name=knowledge_model.collection_name,
                                                              filter=f"document_id == {knowledge_file.id}", limit=10000)

            # 修改用户元数据字段名
            for item in search_result:
                for old_field_name, new_field_name in field_name_map.items():
                    if old_field_name in item["user_metadata"]:
                        item["user_metadata"][new_field_name] = item["user_metadata"].pop(old_field_name)

            # 批量更新数据
            await request_milvus(search_result)

            # Update Elasticsearch metadata
            # Implement Elasticsearch metadata field name update logic for each knowledge file here

            # 使用 update_by_query 来更新符合条件的文档
            script_lines = []
            for old_field_name, new_field_name in field_name_map.items():
                script_lines.append(
                    f"if (ctx._source.metadata.user_metadata.containsKey('{old_field_name}')) " +
                    "{ ctx._source.metadata.user_metadata['" + new_field_name + "'] = " +
                    "ctx._source.metadata.user_metadata.remove('" + old_field_name + "'); }"
                )
            script_source = " ".join(script_lines)
            body = {
                "script": {
                    "source": script_source,
                    "lang": "painless"
                },
                "query": {
                    "term": {"metadata.document_id": knowledge_file.id}
                }
            }
            # 更新es
            await request_es(body)

            # Update knowledge file's user_metadata field
            user_metadata_dict = copy.deepcopy(knowledge_file.user_metadata)
            for old_field_name, new_field_name in field_name_map.items():
                user_metadata = user_metadata_dict.pop(old_field_name, None)
                if user_metadata is not None:
                    user_metadata["updated_at"] = int(datetime.now().timestamp())
                    user_metadata[new_field_name] = user_metadata

            knowledge_file.user_metadata = user_metadata_dict

            await self.knowledge_file_repository.update(knowledge_file)

    async def update_metadata_fields(self, login_user: UserPayload,
                                     update_metadata_fields: UpdateKnowledgeMetadataFieldsReq,
                                     background_tasks: BackgroundTasks):
        """Update metadata field names in a knowledge entity."""

        knowledge_model = await self.knowledge_repository.find_by_id(entity_id=update_metadata_fields.knowledge_id)

        if not knowledge_model:
            raise KnowledgeNotExistError()

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        if knowledge_model.metadata_fields is None:
            return knowledge_model  # No metadata fields to update

        # Built field names
        built_field_names = [item.field_name for item in KNOWLEDGE_RAG_METADATA_SCHEMA]

        for field in update_metadata_fields.metadata_fields:
            if field.new_field_name in built_field_names:
                raise KnowledgeMetadataFieldConflictError(field_name=field.new_field_name)

        field_name_map = {
            field_update.old_field_name: field_update.new_field_name
            for field_update in update_metadata_fields.metadata_fields
        }

        existing_field_names = {field["field_name"] for field in knowledge_model.metadata_fields}

        # Check if all old field names exist and new field names do not exist
        for old_field_name in field_name_map.keys():
            if old_field_name not in existing_field_names or field_name_map[old_field_name] in existing_field_names:
                return knowledge_model

        metadata_fields = copy.deepcopy(knowledge_model.metadata_fields)

        # Update metadata field names
        for i, field in enumerate(metadata_fields):
            if field["field_name"] in field_name_map:
                metadata_fields[i]["field_name"] = field_name_map[field["field_name"]]
                metadata_fields[i]["updated_at"] = int(datetime.now().timestamp())

        knowledge_model.metadata_fields = metadata_fields

        knowledge_model = await self.knowledge_repository.update(knowledge_model)

        # Milvus and ES metadata field name update logic
        background_tasks.add_task(
            self.update_vectorstore_metadata_field_names,
            knowledge_model,
            field_name_map
        )

        return knowledge_model

    async def delete_vectorstore_metadata_fields(self, knowledge_model, field_names: list[str]):
        """Delete metadata fields in Milvus and Elasticsearch vector stores."""
        # Delete Milvus metadata fields
        # milvus_vectorstore = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(knowledge=knowledge_model)
        # Implement Milvus metadata field deletion logic here

        # Delete Elasticsearch metadata fields
        # es_vectorstore = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge_model)
        # Implement Elasticsearch metadata field deletion logic here

        knowledge_model_files = await self.knowledge_file_repository.find_all(knowledge_id=knowledge_model.id)

        vector_client = await KnowledgeRag.init_knowledge_milvus_vectorstore(knowledge=knowledge_model,
                                                                             metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)

        es_client = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=knowledge_model,
                                                                     metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)

        # 请求milvus
        @retry_async(delay=3)
        async def request_milvus(new_data):
            # 批量更新数据
            await vector_client.aclient.upsert(collection_name=vector_client.collection_name, data=new_data)

        # 请求es
        @retry_async(delay=3)
        async def request_es(request_body):
            await es_client.client.update_by_query(
                index=knowledge_model.index_name,
                body=request_body
            )

        for knowledge_file in knowledge_model_files:
            # Delete Milvus metadata fields
            # Implement Milvus metadata field deletion logic for each knowledge file here

            # Query all vectors in this knowledge file in Milvus.
            search_result = await vector_client.aclient.query(collection_name=knowledge_model.collection_name,
                                                              filter=f"document_id == {knowledge_file.id}", limit=10000)

            # 删除指定的元数据字段
            for item in search_result:
                for field_name in field_names:
                    if field_name in item["user_metadata"]:
                        del item["user_metadata"][field_name]

            # 批量更新数据
            await request_milvus(search_result)

            # Delete Elasticsearch metadata fields
            # Implement Elasticsearch metadata field deletion logic for each knowledge file here

            # 使用 update_by_query 来更新符合条件的文档
            script_lines = []
            for field_name in field_names:
                script_lines.append(
                    f"ctx._source.metadata.user_metadata.remove('{field_name}');"
                )
            script_source = " ".join(script_lines)

            body = {
                "script": {
                    "source": script_source,
                    "lang": "painless"
                },
                "query": {
                    "term": {"metadata.document_id": knowledge_file.id}
                }
            }

            # 更新es
            await request_es(body)

            # Update knowledge file's user_metadata field
            knowledge_file.user_metadata = {
                key: value for key, value in knowledge_file.user_metadata.items()
                if key not in field_names
            }

            await self.knowledge_file_repository.update(knowledge_file)

    async def delete_metadata_fields(self, login_user: UserPayload, knowledge_id: int, field_names: list[str],
                                     background_tasks: BackgroundTasks):
        """Delete metadata fields from a knowledge entity."""

        knowledge_model = await self.knowledge_repository.find_by_id(entity_id=knowledge_id)

        if not knowledge_model:
            raise KnowledgeNotExistError()

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        if knowledge_model.metadata_fields is None:
            return knowledge_model  # No metadata fields to delete

        # Filter out metadata fields to be deleted
        metadata_fields = [
            field for field in knowledge_model.metadata_fields
            if field['field_name'] not in field_names
        ]

        knowledge_model.metadata_fields = metadata_fields

        knowledge_model = await self.knowledge_repository.update(knowledge_model)

        # Milvus and ES metadata field deletion logic
        background_tasks.add_task(
            self.delete_vectorstore_metadata_fields,
            knowledge_model,
            field_names
        )

        return knowledge_model

    async def list_metadata_fields(self, default_user, knowledge_id):
        """
        List metadata fields of a knowledge entity.
        Args:
            default_user:
            knowledge_id:

        Returns:

        """

        knowledge_model = await self.knowledge_repository.find_by_id(entity_id=knowledge_id)

        if not knowledge_model:
            raise KnowledgeNotExistError()

        # Permission check
        if not await default_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE
        ):
            raise UnAuthorizedError()

        return {
            "knowledge_id": knowledge_model.id,
            "metadata_fields": knowledge_model.metadata_fields or []
        }
