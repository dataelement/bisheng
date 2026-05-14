import copy
from datetime import datetime
from typing import Any

from fastapi import BackgroundTasks

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeMetadataFieldConflictError,
    KnowledgeMetadataFieldExistError,
    KnowledgeMetadataFieldImmutableError,
    KnowledgeMetadataFieldNotExistError,
    KnowledgeNotExistError,
)
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.schemas.knowledge_schema import AddKnowledgeMetadataFieldsReq, UpdateKnowledgeMetadataFieldsReq
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.utils.util import retry_async


class KnowledgeMetadataService:
    """Encapsulates metadata field operations for knowledge domain."""

    def __init__(
            self,
            knowledge_repository: KnowledgeRepository,
            knowledge_file_repository: KnowledgeFileRepository,
            permission_service: KnowledgePermissionService,
    ):
        self.knowledge_repository = knowledge_repository
        self.knowledge_file_repository = knowledge_file_repository
        self.permission_service = permission_service

    async def add_metadata_fields(
            self,
            login_user: UserPayload,
            add_metadata_fields: AddKnowledgeMetadataFieldsReq,
    ):
        knowledge_model = await self.knowledge_repository.find_by_id(entity_id=add_metadata_fields.knowledge_id)
        if not knowledge_model:
            raise KnowledgeNotExistError()

        await self.permission_service.ensure_knowledge_write_async(
            login_user=login_user,
            owner_user_id=knowledge_model.user_id,
            knowledge_id=knowledge_model.id,
        )

        if knowledge_model.metadata_fields is None:
            knowledge_model.metadata_fields = []

        existing_field_names = {field["field_name"] for field in knowledge_model.metadata_fields}
        built_field_names = [item.field_name for item in KNOWLEDGE_RAG_METADATA_SCHEMA]

        for field in add_metadata_fields.metadata_fields:
            if field.field_name in existing_field_names:
                raise KnowledgeMetadataFieldExistError(field_name=field.field_name)
            if field.field_name in built_field_names:
                raise KnowledgeMetadataFieldConflictError(field_name=field.field_name)

        metadata_fields = copy.deepcopy(knowledge_model.metadata_fields)
        for field in add_metadata_fields.metadata_fields:
            if field.field_name not in existing_field_names:
                metadata_fields.append(field.model_dump())

        knowledge_model.metadata_fields = metadata_fields
        return await self.knowledge_repository.update(knowledge_model)

    async def update_metadata_fields(
            self,
            login_user: UserPayload,
            update_metadata_fields: UpdateKnowledgeMetadataFieldsReq,
            background_tasks: BackgroundTasks,
    ):
        knowledge_model = await self.knowledge_repository.find_by_id(entity_id=update_metadata_fields.knowledge_id)
        if not knowledge_model:
            raise KnowledgeNotExistError()

        await self.permission_service.ensure_knowledge_write_async(
            login_user=login_user,
            owner_user_id=knowledge_model.user_id,
            knowledge_id=knowledge_model.id,
        )

        if knowledge_model.metadata_fields is None:
            return knowledge_model

        built_field_names = [item.field_name for item in KNOWLEDGE_RAG_METADATA_SCHEMA]
        existing_field_names = {field["field_name"] for field in knowledge_model.metadata_fields}

        for field in update_metadata_fields.metadata_fields:
            if field.old_field_name in built_field_names:
                raise KnowledgeMetadataFieldImmutableError(field_name=field.old_field_name)
            if field.new_field_name in built_field_names:
                raise KnowledgeMetadataFieldConflictError(field_name=field.new_field_name)
            if field.new_field_name in existing_field_names:
                raise KnowledgeMetadataFieldExistError(field_name=field.new_field_name)
            if field.old_field_name not in existing_field_names:
                raise KnowledgeMetadataFieldNotExistError(field_name=field.old_field_name)

        field_name_map = {
            field_update.old_field_name: field_update.new_field_name
            for field_update in update_metadata_fields.metadata_fields
        }

        for old_field_name in field_name_map.keys():
            if old_field_name not in existing_field_names or field_name_map[old_field_name] in existing_field_names:
                return knowledge_model

        metadata_fields = copy.deepcopy(knowledge_model.metadata_fields)
        for idx, field in enumerate(metadata_fields):
            if field["field_name"] in field_name_map:
                metadata_fields[idx]["field_name"] = field_name_map[field["field_name"]]
                metadata_fields[idx]["updated_at"] = int(datetime.now().timestamp())

        knowledge_model.metadata_fields = metadata_fields
        knowledge_model = await self.knowledge_repository.update(knowledge_model)

        background_tasks.add_task(
            self.update_vectorstore_metadata_field_names,
            login_user.user_id,
            knowledge_model,
            field_name_map,
        )

        return knowledge_model

    async def delete_metadata_fields(
            self,
            login_user: UserPayload,
            knowledge_id: int,
            field_names: list[str],
            background_tasks: BackgroundTasks,
    ):
        knowledge_model = await self.knowledge_repository.find_by_id(entity_id=knowledge_id)
        if not knowledge_model:
            raise KnowledgeNotExistError()

        await self.permission_service.ensure_knowledge_write_async(
            login_user=login_user,
            owner_user_id=knowledge_model.user_id,
            knowledge_id=knowledge_model.id,
        )

        if knowledge_model.metadata_fields is None:
            knowledge_model.metadata_fields = []

        existing_field_names = [field["field_name"] for field in knowledge_model.metadata_fields]
        for field_name in field_names:
            if field_name not in existing_field_names:
                raise KnowledgeMetadataFieldNotExistError(field_name=field_name)

        knowledge_model.metadata_fields = [
            field for field in knowledge_model.metadata_fields if field["field_name"] not in field_names
        ]
        knowledge_model = await self.knowledge_repository.update(knowledge_model)

        background_tasks.add_task(
            self.delete_vectorstore_metadata_fields,
            login_user.user_id,
            knowledge_model,
            field_names,
        )

        return knowledge_model

    async def list_metadata_fields(self, default_user: UserPayload, knowledge_id: int):
        knowledge_model = await self.knowledge_repository.find_by_id(entity_id=knowledge_id)
        if not knowledge_model:
            raise KnowledgeNotExistError()

        await self.permission_service.ensure_knowledge_read_async(
            login_user=default_user,
            owner_user_id=knowledge_model.user_id,
            knowledge_id=knowledge_model.id,
        )

        if knowledge_model.metadata_fields is None:
            knowledge_model.metadata_fields = []

        knowledge_model.metadata_fields.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return {"knowledge_id": knowledge_model.id, "metadata_fields": knowledge_model.metadata_fields or []}

    async def update_vectorstore_metadata_field_names(
            self,
            invoke_user_id: int,
            knowledge_model: Any,
            field_name_map: dict[str, str],
    ) -> None:
        knowledge_model_files = await self.knowledge_file_repository.find_all(knowledge_id=knowledge_model.id)

        vector_client = await KnowledgeRag.init_knowledge_milvus_vectorstore(
            invoke_user_id,
            knowledge=knowledge_model,
            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
        )
        es_client = await KnowledgeRag.init_knowledge_es_vectorstore(
            knowledge=knowledge_model,
            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
        )

        @retry_async(delay=3)
        async def request_milvus(new_data):
            await vector_client.aclient.upsert(collection_name=vector_client.collection_name, data=new_data)

        @retry_async(delay=3)
        async def request_es(request_body):
            await es_client.client.update_by_query(index=knowledge_model.index_name, body=request_body)

        for knowledge_file in knowledge_model_files:
            search_result = await vector_client.aclient.query(
                collection_name=knowledge_model.collection_name,
                filter=f"document_id == {knowledge_file.id}",
                limit=10000,
            )
            for item in search_result:
                for old_field_name, new_field_name in field_name_map.items():
                    if old_field_name in item["user_metadata"]:
                        item["user_metadata"][new_field_name] = item["user_metadata"].pop(old_field_name)
            await request_milvus(search_result)

            script_lines = []
            for old_field_name, new_field_name in field_name_map.items():
                script_lines.append(
                    f"if (ctx._source.metadata.user_metadata.containsKey('{old_field_name}')) "
                    + "{ ctx._source.metadata.user_metadata['"
                    + new_field_name
                    + "'] = ctx._source.metadata.user_metadata.remove('"
                    + old_field_name
                    + "'); }"
                )
            body = {
                "script": {"source": " ".join(script_lines), "lang": "painless"},
                "query": {"term": {"metadata.document_id": knowledge_file.id}},
            }
            await request_es(body)

            user_metadata_dict = copy.deepcopy(knowledge_file.user_metadata)
            for old_field_name, new_field_name in field_name_map.items():
                user_metadata = user_metadata_dict.pop(old_field_name, None)
                if user_metadata is not None:
                    user_metadata["updated_at"] = int(datetime.now().timestamp())
                    user_metadata[new_field_name] = user_metadata
            knowledge_file.user_metadata = user_metadata_dict
            await self.knowledge_file_repository.update(knowledge_file)

    async def delete_vectorstore_metadata_fields(
            self,
            invoke_user_id: int,
            knowledge_model: Any,
            field_names: list[str],
    ) -> None:
        knowledge_model_files = await self.knowledge_file_repository.find_all(knowledge_id=knowledge_model.id)

        vector_client = await KnowledgeRag.init_knowledge_milvus_vectorstore(
            invoke_user_id,
            knowledge=knowledge_model,
            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
        )
        es_client = await KnowledgeRag.init_knowledge_es_vectorstore(
            knowledge=knowledge_model,
            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
        )

        @retry_async(delay=3)
        async def request_milvus(new_data):
            await vector_client.aclient.upsert(collection_name=vector_client.collection_name, data=new_data)

        @retry_async(delay=3)
        async def request_es(request_body):
            await es_client.client.update_by_query(index=knowledge_model.index_name, body=request_body)

        for knowledge_file in knowledge_model_files:
            search_result = await vector_client.aclient.query(
                collection_name=knowledge_model.collection_name,
                filter=f"document_id == {knowledge_file.id}",
                limit=10000,
            )
            for item in search_result:
                for field_name in field_names:
                    if field_name in item["user_metadata"]:
                        del item["user_metadata"][field_name]
            await request_milvus(search_result)

            script_lines = []
            for field_name in field_names:
                script_lines.append(f"ctx._source.metadata.user_metadata.remove('{field_name}');")
            body = {
                "script": {"source": " ".join(script_lines), "lang": "painless"},
                "query": {"term": {"metadata.document_id": knowledge_file.id}},
            }
            await request_es(body)

            knowledge_file.user_metadata = {
                key: value for key, value in knowledge_file.user_metadata.items() if key not in field_names
            }
            await self.knowledge_file_repository.update(knowledge_file)
