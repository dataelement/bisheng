import asyncio
import json
import math
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional
from urllib.parse import urlparse

from fastapi import BackgroundTasks, Request
from loguru import logger
from pymilvus import Collection

from bisheng.api.services.knowledge_imp import (
    KnowledgeUtils,
    delete_knowledge_file_vectors,
    process_file_task,
)
from bisheng.api.v1.schema.knowledge import KnowledgeFileResp
from bisheng.api.v1.schemas import (
    FileChunk,
    FileProcessBase,
    KnowledgeFileOne,
    KnowledgeFileProcess,
    UpdatePreviewFileChunk, ExcelRule, KnowledgeFileReProcess,
)
from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError, ServerError
from bisheng.common.errcode.knowledge import (
    KnowledgeChunkError,
    KnowledgeExistError,
    KnowledgeNoEmbeddingError, KnowledgeNotQAError, KnowledgeFileFailedError,
    KnowledgeTagExistError, KnowledgeTagNotExistError, KnowledgeFileTagLimitError
)
from bisheng.core.ai import FakeEmbeddings
from bisheng.core.cache.redis_manager import get_redis_client_sync, get_redis_client
from bisheng.core.cache.utils import file_download, async_file_download
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync, get_minio_storage
from bisheng.database.models.group_resource import (
    GroupResource,
    GroupResourceDao,
    ResourceTypeEnum,
)
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.tag import TagDao, TagBusinessTypeEnum, Tag
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeCreate,
    KnowledgeDao,
    KnowledgeRead,
    KnowledgeTypeEnum,
    KnowledgeUpdate, KnowledgeState,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus, ParseType,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.knowledge.domain.schemas.knowledge_schema import AddKnowledgeMetadataFieldsReq, \
    UpdateKnowledgeMetadataFieldsReq
from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import KnowledgeAuditTelemetryService
from bisheng.knowledge.domain.services.knowledge_metadata_service import KnowledgeMetadataService
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models import LLMDao
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.utils import generate_uuid, generate_knowledge_index_name


class KnowledgeService(KnowledgeUtils):
    """Service class for managing knowledge domain operations."""

    permission_service = KnowledgePermissionService()
    audit_telemetry_service = KnowledgeAuditTelemetryService()

    def __init__(self, knowledge_repository: 'KnowledgeRepository',
                 knowledge_file_repository: 'KnowledgeFileRepository',
                 permission_service: KnowledgePermissionService = None,
                 audit_telemetry_service: KnowledgeAuditTelemetryService = None,
                 metadata_service: KnowledgeMetadataService = None):
        self.knowledge_repository = knowledge_repository
        self.knowledge_file_repository = knowledge_file_repository
        self.permission_service = permission_service or self.__class__.permission_service
        self.audit_telemetry_service = audit_telemetry_service or self.__class__.audit_telemetry_service
        self.metadata_service = metadata_service or KnowledgeMetadataService(
            knowledge_repository=self.knowledge_repository,
            knowledge_file_repository=self.knowledge_file_repository,
            permission_service=self.permission_service,
        )

    async def add_metadata_fields(self, login_user: UserPayload, add_metadata_fields: AddKnowledgeMetadataFieldsReq):
        return await self.metadata_service.add_metadata_fields(login_user, add_metadata_fields)

    async def update_metadata_fields(self, login_user: UserPayload,
                                     update_metadata_fields: UpdateKnowledgeMetadataFieldsReq,
                                     background_tasks: BackgroundTasks):
        return await self.metadata_service.update_metadata_fields(
            login_user=login_user,
            update_metadata_fields=update_metadata_fields,
            background_tasks=background_tasks,
        )

    async def delete_metadata_fields(self, login_user: UserPayload, knowledge_id: int, field_names: list[str],
                                     background_tasks: BackgroundTasks):
        return await self.metadata_service.delete_metadata_fields(
            login_user=login_user,
            knowledge_id=knowledge_id,
            field_names=field_names,
            background_tasks=background_tasks,
        )

    async def list_metadata_fields(self, default_user, knowledge_id):
        return await self.metadata_service.list_metadata_fields(default_user, knowledge_id)

    @classmethod
    async def _get_writable_knowledge(cls, login_user: UserPayload, knowledge_id: int) -> Knowledge:
        knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if not knowledge:
            raise NotFoundError(msg="knowledge not found")
        if not await login_user.async_access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()
        return knowledge

    @classmethod
    async def _get_readable_knowledge(cls, login_user: UserPayload, knowledge_id: int) -> Knowledge:
        knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if not knowledge:
            raise NotFoundError(msg="knowledge not found")
        if not await login_user.async_access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE
        ):
            raise UnAuthorizedError()
        return knowledge

    @staticmethod
    def _deduplicate_tag_ids(tag_ids: List[int]) -> List[int]:
        return list(dict.fromkeys(tag_ids))

    @classmethod
    async def _validate_knowledge_tag_ids(cls, knowledge_id: int, tag_ids: List[int]) -> None:
        if not tag_ids:
            return

        tags = await TagDao.aget_tags_by_ids(tag_ids)
        if len(tags) != len(tag_ids):
            raise KnowledgeTagNotExistError()

        for tag in tags:
            if tag.business_type != TagBusinessTypeEnum.KNOWLEDGE or tag.business_id != str(knowledge_id):
                raise KnowledgeTagNotExistError()

    @classmethod
    def get_all_knowledge_by_time_range(cls, start_data: datetime, end_data: datetime, page: int = 1,
                                        page_size: int = 10):
        """Get all the knowledge bases created in a certain timeframe"""

        return KnowledgeDao.get_knowledge_by_time_range(start_data, end_data, page, page_size)

    @classmethod
    def get_first_knowledge(cls) -> Knowledge | None:
        return KnowledgeDao.get_first_knowledge()

    @classmethod
    async def get_knowledge(
            cls,
            request: Request,
            login_user: UserPayload,
            knowledge_type: KnowledgeTypeEnum,
            name: str = None,
            sort_by: str = "update_time",
            page: int = 1,
            limit: int = 10,
    ) -> Tuple[List[KnowledgeRead], int]:
        # F008: 列表可见性 = OpenFGA `can_read`（与 PRD「使用知识库」/关系模型 can_read 一致）。
        # 与「当前用户创建」的知识库 ID 取并集：避免 list_objects 滞后、缓存或计算差异导致创建者看不到自己的库。
        accessible_ids = await login_user.rebac_list_accessible('can_read', 'knowledge_space')
        if accessible_ids is not None:
            creator_ids = await KnowledgeDao.aget_knowledge_ids_created_by(
                login_user.user_id, knowledge_type,
            )
            merged = set(int(k) for k in accessible_ids) | set(creator_ids)
            knowledge_id_extra = list(merged)
            res = await KnowledgeDao.aget_user_knowledge(
                login_user.user_id,
                knowledge_id_extra,
                knowledge_type,
                name,
                sort_by,
                page,
                limit,
            )
            total = await KnowledgeDao.acount_user_knowledge(
                login_user.user_id, knowledge_id_extra, knowledge_type, name
            )
        else:
            res = await KnowledgeDao.aget_all_knowledge(
                name, knowledge_type, sort_by, page=page, limit=limit
            )
            total = await KnowledgeDao.acount_all_knowledge(name, knowledge_type)

        result = await cls.aconvert_knowledge_read(login_user, res)
        return result, total

    @classmethod
    async def aconvert_knowledge_read(
            cls, login_user: UserPayload, knowledge_list: List[Knowledge]
    ) -> List[KnowledgeRead]:
        """异步组装列表项；避免在 async 路由里调用 sync access_check（_run_async_safe 易死锁/10s 超时）。"""
        if not knowledge_list:
            return []
        db_user_ids = {one.user_id for one in knowledge_list}
        db_user_info = UserDao.get_user_by_ids(list(db_user_ids))
        db_user_dict = {one.user_id: one.user_name for one in db_user_info}

        async def _row(one: Knowledge) -> KnowledgeRead:
            if login_user.user_id == one.user_id:
                copiable = True
            else:
                copiable = await login_user.async_access_check(
                    one.user_id, str(one.id), AccessType.KNOWLEDGE_WRITE
                )
            return KnowledgeRead(
                **one.model_dump(),
                user_name=db_user_dict.get(one.user_id, str(one.user_id)),
                copiable=copiable,
            )

        return list(await asyncio.gather(*[_row(one) for one in knowledge_list]))

    @classmethod
    def convert_knowledge_read(
            cls, login_user: UserPayload, knowledge_list: List[Knowledge]
    ) -> List[KnowledgeRead]:
        db_user_ids = {one.user_id for one in knowledge_list}
        db_user_info = UserDao.get_user_by_ids(list(db_user_ids))
        db_user_dict = {one.user_id: one.user_name for one in db_user_info}
        res = []

        for one in knowledge_list:
            if login_user.user_id == one.user_id:
                copiable = True
            else:
                copiable = login_user.access_check(
                    one.user_id, str(one.id), AccessType.KNOWLEDGE_WRITE
                )
            res.append(
                KnowledgeRead(
                    **one.model_dump(),
                    user_name=db_user_dict.get(one.user_id, str(one.user_id)),
                    copiable=copiable,
                )
            )
        return res

    @classmethod
    def get_knowledge_info(
            cls, request: Request, login_user: UserPayload, knowledge_id: List[int]
    ) -> List[KnowledgeRead]:
        db_knowledge = KnowledgeDao.get_list_by_ids(knowledge_id)
        filter_knowledge = db_knowledge
        if not login_user.is_admin():
            filter_knowledge = []
            for one in db_knowledge:
                # Determine if the user has permission
                if login_user.access_check(
                        one.user_id, str(one.id), AccessType.KNOWLEDGE
                ):
                    filter_knowledge.append(one)
        if not filter_knowledge:
            return []

        return cls.convert_knowledge_read(login_user, filter_knowledge)

    @classmethod
    def create_knowledge(
            cls, request: Request, login_user: UserPayload, knowledge: KnowledgeCreate
    ) -> Knowledge:

        # Determine if the Knowledge Base is Renamed
        repeat_knowledge = KnowledgeDao.get_knowledge_by_name(
            knowledge.name, login_user.user_id
        )
        if repeat_knowledge:
            raise KnowledgeExistError.http_exception()

        db_knowledge = Knowledge.model_validate(knowledge)

        # CorrectionembeddingModels
        if not db_knowledge.model:
            raise KnowledgeNoEmbeddingError.http_exception()
        try:
            embedding_model_id = int(str(db_knowledge.model).strip())
        except (TypeError, ValueError):
            raise KnowledgeNoEmbeddingError.http_exception()
        embed_info = LLMDao.get_model_by_id(embedding_model_id)
        if not embed_info:
            raise KnowledgeNoEmbeddingError.http_exception()
        if embed_info.model_type != LLMModelType.EMBEDDING.value:
            raise KnowledgeNoEmbeddingError.http_exception()

        return cls.create_knowledge_base(request, login_user, db_knowledge)

    @classmethod
    def create_knowledge_base(cls, request, login_user: UserPayload, db_knowledge: Knowledge,
                              skip_hook: bool = False) -> Knowledge:
        # generate index_name and collection_name
        db_knowledge.index_name = generate_knowledge_index_name()
        db_knowledge.collection_name = db_knowledge.index_name

        # Insert into Database
        db_knowledge.user_id = login_user.user_id
        db_knowledge = KnowledgeDao.insert_one(db_knowledge)

        # qa knowledge will be init index when add question
        # todo change qa and other knowledge one metadata_schema
        if db_knowledge.type != KnowledgeTypeEnum.QA.value:
            try:
                vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(login_user.user_id,
                                                                                    knowledge=db_knowledge,
                                                                                    metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
                # Init Milvus schema avoiding SchemaNotReady concurrently
                # Need to provide non-nullable fields to satisfy Milvus schema constraints
                init_ids = vector_client.add_texts(
                    texts=["init_schema"],
                    metadatas=[Metadata(document_id=0,
                                        knowledge_id=db_knowledge.id,
                                        abstract="",
                                        chunk_index=1,
                                        bbox="{}",
                                        page=1,
                                        upload_time=int(time.time()),
                                        update_time=int(time.time()),
                                        uploader="",
                                        updater="",
                                        user_metadata={}).model_dump()]
                )
                if init_ids:
                    vector_client.delete(ids=init_ids)

                es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=db_knowledge,
                                                                            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
                es_client._store._create_index_if_not_exists()
            except Exception as e:
                logger.exception("create knowledge index name error")

        # Handling the next steps in creating a Knowledge Base
        if not skip_hook:
            cls.create_knowledge_hook(request, login_user, db_knowledge)
        return db_knowledge

    @classmethod
    def create_knowledge_hook(
            cls, request: Request, login_user: UserPayload, knowledge: Knowledge
    ):
        # F008: Write owner tuple to OpenFGA (INV-2)
        from bisheng.permission.domain.services.owner_service import OwnerService
        OwnerService.write_owner_tuple_sync(login_user.user_id, 'knowledge_space', str(knowledge.id))

        cls.audit_telemetry_service.audit_create_knowledge(login_user, request, knowledge)
        cls.audit_telemetry_service.telemetry_new_knowledge(login_user, knowledge)

        return True

    @classmethod
    def update_knowledge(
            cls, request: Request, login_user: UserPayload, knowledge: KnowledgeUpdate
    ) -> KnowledgeRead:
        db_knowledge = KnowledgeDao.query_by_id(knowledge.knowledge_id)
        if not db_knowledge:
            raise NotFoundError.http_exception()

        # judge access
        if not login_user.access_check(
                db_knowledge.user_id, str(db_knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()

        if knowledge.name and knowledge.name != db_knowledge.name:
            repeat_knowledge = KnowledgeDao.get_knowledge_by_name(
                knowledge.name, db_knowledge.user_id
            )
            if repeat_knowledge and repeat_knowledge.id != db_knowledge.id:
                raise KnowledgeExistError.http_exception()
            db_knowledge.name = knowledge.name
        db_knowledge.description = knowledge.description
        db_knowledge = KnowledgeDao.update_one(db_knowledge)
        user = UserDao.get_user(db_knowledge.user_id)
        res = KnowledgeRead(
            **db_knowledge.model_dump(),
            user_name=user.user_name if user else db_knowledge.user_id,
        )
        return res

    @classmethod
    def delete_knowledge(
            cls,
            request: Request,
            login_user: UserPayload,
            knowledge_id: int,
            only_clear: bool = False,
    ):
        knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()

        if not login_user.access_check(
                knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()

        # Cleaned vectorData in
        cls.delete_knowledge_file_in_vector(knowledge)

        # CleanedminioData
        cls.delete_knowledge_file_in_minio(knowledge_id)

        # DeletemysqlDATA
        KnowledgeDao.delete_knowledge(knowledge_id, only_clear)

        cls.audit_telemetry_service.telemetry_delete_knowledge(login_user)

        if not only_clear:
            cls.delete_knowledge_hook(request, login_user, knowledge)
        return True

    @classmethod
    def delete_knowledge_file_in_vector(cls, knowledge: Knowledge, del_es: bool = True):
        embeddings = FakeEmbeddings()
        vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(invoke_user_id=0, knowledge=knowledge,
                                                                            embeddings=embeddings)
        if isinstance(vector_client.col, Collection):
            logger.info(
                f"delete_vector col={knowledge.collection_name} knowledge_id={knowledge.id}"
            )
            if knowledge.collection_name.startswith("col"):
                # Singularcollection, simply delete it
                vector_client.col.drop()
            else:
                raise ValueError("knowledge.collection_name must start with 'col' not support partition mode")
        if del_es:
            index_name = knowledge.index_name or knowledge.collection_name  # Compatible with older versions
            es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge)
            res = es_client.client.indices.delete(index=index_name, ignore=[400, 404])
            logger.info(f"act=delete_es index={index_name} res={res}")

    @classmethod
    def delete_knowledge_hook(
            cls, request: Request, login_user: UserPayload, knowledge: Knowledge
    ):
        logger.info(
            f"delete_knowledge_hook id={knowledge.id}, user: {login_user.user_id}"
        )

        cls.audit_telemetry_service.audit_delete_knowledge(login_user, request, knowledge)

        # F008: Clean up all FGA tuples for this resource (AC-03)
        from bisheng.permission.domain.services.owner_service import OwnerService
        OwnerService.delete_resource_tuples_sync('knowledge_space', str(knowledge.id))

    @classmethod
    def delete_knowledge_file_in_minio(cls, knowledge_id: int):
        # <g id="Bold">Qn,</g>1000records to deleteminioDoc.
        count = KnowledgeFileDao.count_file_by_knowledge_id(knowledge_id)
        if count == 0:
            return
        page_size = 1000
        page_num = math.ceil(count / page_size)

        minio_client = get_minio_storage_sync()

        for i in range(page_num):
            file_list = KnowledgeFileDao.get_file_simple_by_knowledge_id(
                knowledge_id, i + 1, page_size
            )
            for file in file_list:
                minio_client.remove_object_sync(object_name=str(file[0]))
                for object_name in file[1:]:
                    if not object_name:
                        continue
                    minio_client.remove_object_sync(object_name=object_name)

    @classmethod
    def get_upload_file_original_name(cls, file_name: str) -> str:
        """
        SetujuuuidFile name, get the original name of the uploaded file
        """
        if not file_name:
            raise ServerError.http_exception("file_name is empty")
        # FROMredisGet within
        uuid_file_name = file_name.split(".")[0]
        original_file_name = get_redis_client_sync().get(f"file_name:{uuid_file_name}") or file_name
        return original_file_name

    @classmethod
    async def save_upload_file_original_name(cls, original_file_name: str) -> str:
        """
        Save the original name of the uploaded file toredisGenerate oneuuidFile name
        """
        if not original_file_name:
            raise ServerError.http_exception("original_file_name is empty")
        file_ext = original_file_name.split(".")[-1]
        # Generate a uniqueuuidas akey
        uuid_file_name = generate_uuid()
        redis_client = await get_redis_client()
        await redis_client.aset(f"file_name:{uuid_file_name}", original_file_name, expiration=86400)
        return f"{uuid_file_name}.{file_ext}"

    @classmethod
    async def get_preview_file_chunk(
            cls, request: Request, login_user: UserPayload, req_data: KnowledgeFileProcess
    ) -> (str, str, List[FileChunk], Any):
        """
        0Parse Mode: uns or local
        1: Converted file path
        2: After dicingchunkVertical
        3: ocrIdentifiedbbox
        """
        knowledge = await KnowledgeDao.aquery_by_id(req_data.knowledge_id)
        await cls.permission_service.ensure_knowledge_write_async(
            login_user=login_user,
            owner_user_id=knowledge.user_id,
            knowledge_id=knowledge.id,
        )

        file_path = req_data.file_list[0].file_path
        excel_rule = req_data.file_list[0].excel_rule
        cache_key = cls.get_preview_cache_key(req_data.knowledge_id, file_path)

        redis_client = await get_redis_client()

        # Attempt to fetch from cache
        if req_data.cache:
            if cache_value := await cls.async_get_preview_cache(cache_key):
                parse_type = await redis_client.aget(f"{cache_key}_parse_type")
                file_share_url = await redis_client.aget(f"{cache_key}_file_path")
                partitions = await redis_client.aget(f"{cache_key}_partitions")
                res = []

                # Sort by segment order
                cache_value = dict(sorted(cache_value.items(), key=lambda x: int(x[0])))

                for key, val in cache_value.items():
                    res.append(FileChunk(text=val["text"], metadata=val["metadata"]))
                return parse_type, file_share_url, res, partitions

        filepath, file_name = await async_file_download(file_path)
        file_ext = file_name.split(".")[-1].lower()
        file_name = cls.get_upload_file_original_name(file_name)

        # Split text using PreviewFilePipeline
        from bisheng.knowledge.rag.preview_file_pipeline import PreviewFilePipeline
        from bisheng.api.v1.schemas import FileProcessBase

        file_rule = FileProcessBase(
            knowledge_id=req_data.knowledge_id,
            split_mode=req_data.split_mode,
            separator=req_data.separator,
            separator_rule=req_data.separator_rule,
            chunk_size=req_data.chunk_size,
            chunk_overlap=req_data.chunk_overlap,
            hierarchy_level=req_data.hierarchy_level,
            append_title=req_data.append_title,
            max_chunk_size=req_data.max_chunk_size,
            force_ocr=req_data.force_ocr,
            enable_formula=req_data.enable_formula,
            filter_page_header_footer=req_data.filter_page_header_footer,
            retain_images=req_data.retain_images,
            excel_rule=excel_rule,
        )
        pipeline = PreviewFilePipeline(
            invoke_user_id=login_user.user_id,
            local_file_path=filepath,
            knowledge_id=req_data.knowledge_id,
            file_name=file_name,
            file_rule=file_rule,
        )
        result = await pipeline.arun()
        if not result.documents:
            raise ValueError("File resolution is empty")

        parse_type = type(pipeline.loader).__name__ if pipeline.loader else "local"
        partitions = {}
        if hasattr(pipeline.loader, "bbox_list") and pipeline.loader.bbox_list:
            for text_bbox in pipeline.loader.bbox_list:
                bbox_key = "-".join([str(int(one)) for one in text_bbox.bbox])
                partitions[f"{text_bbox.page}-{bbox_key}"] = text_bbox.model_dump()

        texts = [doc.page_content for doc in result.documents]
        metadatas = [doc.metadata for doc in result.documents]

        if len(texts) == 0:
            raise ValueError("File resolution is empty")
        res = []
        cache_map = {}
        for index, val in enumerate(texts):
            metadata_dict = metadatas[index] if isinstance(metadatas[index], dict) else metadatas[index].model_dump()
            cache_map[index] = {"text": val, "metadata": metadata_dict}
            res.append(FileChunk(text=val, metadata=metadata_dict))

        # Default is the address of the source file
        minio_client = await get_minio_storage()

        file_share_url = minio_client.clear_minio_share_host(file_path)
        if file_ext in ['doc', 'docx', 'wps', 'xls', 'xlsx', 'et', 'ppt', 'pptx', 'dps']:
            new_file_name = KnowledgeUtils.get_tmp_preview_file_object_name(filepath)
            if await minio_client.object_exists(minio_client.tmp_bucket, new_file_name):
                file_share_url = await minio_client.get_share_link(
                    new_file_name, minio_client.tmp_bucket
                )

        # Deposit Cache
        await cls.async_save_preview_cache(cache_key, mapping=cache_map)
        await redis_client.aset(f"{cache_key}_parse_type", parse_type)
        await redis_client.aset(f"{cache_key}_file_path", file_share_url)
        await redis_client.aset(f"{cache_key}_partitions", partitions)
        return parse_type, file_share_url, res, partitions

    @classmethod
    async def update_preview_file_chunk(
            cls, request: Request, login_user: UserPayload, req_data: UpdatePreviewFileChunk
    ):
        knowledge = await KnowledgeDao.aquery_by_id(req_data.knowledge_id)
        await cls.permission_service.ensure_knowledge_write_async(
            login_user=login_user,
            owner_user_id=knowledge.user_id,
            knowledge_id=knowledge.id,
        )

        cache_key = cls.get_preview_cache_key(req_data.knowledge_id, req_data.file_path)
        chunk_info = await cls.async_get_preview_cache(cache_key, req_data.chunk_index)
        if not chunk_info:
            raise NotFoundError.http_exception()
        chunk_info["text"] = req_data.text
        chunk_info["metadata"]["bbox"] = req_data.bbox
        await cls.async_save_preview_cache(
            cache_key, chunk_index=req_data.chunk_index, value=chunk_info
        )

    @classmethod
    def delete_preview_file_chunk(
            cls, request: Request, login_user: UserPayload, req_data: UpdatePreviewFileChunk
    ):
        knowledge = KnowledgeDao.query_by_id(req_data.knowledge_id)
        if not login_user.access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()

        cache_key = cls.get_preview_cache_key(req_data.knowledge_id, req_data.file_path)
        cls.delete_preview_cache(cache_key, chunk_index=req_data.chunk_index)

    @classmethod
    def save_knowledge_file(
            cls, login_user: UserPayload, req_data: KnowledgeFileProcess
    ):
        """Process uploaded files, Uploaded to onlyminioAndmysql"""
        knowledge = KnowledgeDao.query_by_id(req_data.knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()
        if not login_user.access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()
        failed_files = []
        # Process each file
        process_files = []
        preview_cache_keys = []
        split_rule_dict = req_data.model_dump(include=set(list(FileProcessBase.model_fields.keys())))
        for one in req_data.file_list:
            # Upload source files, create data records
            db_file = cls.process_one_file(login_user, knowledge, one, split_rule_dict)
            # Duplicate file data using asynchronous tasks to execute
            if db_file.status != KnowledgeFileStatus.FAILED.value:
                # Get a preview cache of this filekey
                cache_key = cls.get_preview_cache_key(
                    req_data.knowledge_id, one.file_path
                )
                preview_cache_keys.append(cache_key)
                process_files.append(db_file)
            else:
                failed_file_info = db_file.model_dump()
                failed_file_info["file_path"] = one.file_path
                failed_files.append(failed_file_info)
        return knowledge, failed_files, process_files, preview_cache_keys

    @classmethod
    def process_knowledge_file(
            cls,
            request: Request,
            login_user: UserPayload,
            background_tasks: BackgroundTasks,
            req_data: KnowledgeFileProcess,
    ) -> List[KnowledgeFile]:
        from bisheng.worker.knowledge import file_worker

        """Process uploaded files"""
        knowledge, failed_files, process_files, preview_cache_keys = (
            cls.save_knowledge_file(login_user, req_data)
        )

        # Asynchronous processing of file parsing and warehousing, To voters if approvedcache_keyIf data can be obtained, use thecachefor inbound operations
        for index, one in enumerate(process_files):
            file_worker.parse_knowledge_file_celery.delay(one.id, preview_cache_keys[index], req_data.callback_url)

        cls.upload_knowledge_file_hook(request, login_user, knowledge, process_files)
        return failed_files + process_files

    @classmethod
    def sync_process_knowledge_file(
            cls, request: Request, login_user: UserPayload, req_data: KnowledgeFileProcess
    ) -> List[KnowledgeFile]:
        """Sync uploaded files"""
        knowledge, failed_files, process_files, preview_cache_keys = (
            cls.save_knowledge_file(login_user, req_data)
        )

        if process_files:
            process_file_task(
                knowledge=knowledge,
                db_files=process_files,
                preview_cache_keys=preview_cache_keys,
                callback_url=req_data.callback_url,
            )

            process_files = KnowledgeFileDao.select_list([f.id for f in process_files])

        cls.upload_knowledge_file_hook(request, login_user, knowledge, process_files)
        return failed_files + process_files

    @classmethod
    async def rebuild_knowledge_file(cls, request: Request,
                                     login_user: UserPayload,
                                     req_data: KnowledgeFileReProcess):
        """
        Rebuild Knowledge Base Files
        :param request:
        :param login_user:
        :param req_data:
        :return:
        """
        knowledge = await KnowledgeDao.async_query_by_id(req_data.knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()
        if not login_user.access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()

        db_file = await KnowledgeFileDao.query_by_id(req_data.kb_file_id)

        if not db_file:
            raise NotFoundError.http_exception()

        db_file = await cls.process_rebuild_file(db_file, req_data, login_user.user_id, login_user.user_name)

        return db_file.model_dump()

    @classmethod
    async def retry_files(
            cls,
            request: Request,
            login_user: UserPayload,
            req_data: dict,
    ):

        db_file_retry = req_data.get("file_objs")
        if not db_file_retry:
            return []
        id2input = {file.get("id"): file for file in db_file_retry}
        file_ids = list(id2input.keys())
        db_files: List[KnowledgeFile] = await KnowledgeFileDao.aget_file_by_ids(file_ids=file_ids)
        if not db_files:
            return []
        knowledge = await KnowledgeDao.aquery_by_id(db_files[0].knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()
        if not await login_user.async_access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()

        req_data["knowledge_id"] = knowledge.id

        tmp, file_level_path = await cls.process_retry_files(db_files, id2input, login_user)

        cls.upload_knowledge_file_hook(request, login_user, knowledge, tmp)
        for one in file_level_path:
            await cls.update_folder_update_time(one)
        return []

    @classmethod
    def upload_knowledge_file_hook(
            cls,
            request: Request,
            login_user: UserPayload,
            knowledge: Knowledge,
            file_list: List[KnowledgeFile],
    ):
        logger.info(
            f"act=upload_knowledge_file_hook user={login_user.user_name} knowledge_id={knowledge.id}"
        )
        if file_list:
            KnowledgeDao.update_knowledge_update_time(knowledge)
        # Log Audit Logs
        file_name = ""
        for one in file_list:
            file_name += "\n\n" + one.file_name
        cls.audit_telemetry_service.audit_upload_knowledge_file(login_user, request, knowledge, file_list)

    @classmethod
    def process_one_file(
            cls,
            login_user: UserPayload,
            knowledge: Knowledge,
            file_info: KnowledgeFileOne,
            split_rule: Dict,
            file_kwargs: Dict = None,
    ) -> KnowledgeFile:
        """Process uploaded files"""
        # download original file
        filepath, file_name = file_download(file_info.file_path)
        md5_ = os.path.splitext(os.path.basename(filepath))[0].split("_")[0]

        # Get file size inbytes）
        file_size = os.path.getsize(filepath)

        file_extension_name = file_name.split(".")[-1]
        original_file_name = cls.get_upload_file_original_name(file_name)
        # Does it contain duplicate files?
        content_repeat = KnowledgeFileDao.get_file_by_condition(
            md5_=md5_, knowledge_id=knowledge.id
        )
        name_repeat = KnowledgeFileDao.get_file_by_condition(
            file_name=original_file_name, knowledge_id=knowledge.id
        )

        if not file_info.excel_rule:
            file_info.excel_rule = ExcelRule()
        split_rule["excel_rule"] = file_info.excel_rule.model_dump()
        str_split_rule = json.dumps(split_rule)
        minio_client = get_minio_storage_sync()

        if content_repeat or name_repeat:
            db_file = content_repeat[0] if content_repeat else name_repeat[0]
            old_name = db_file.file_name
            file_type = file_name.rsplit(".", 1)[-1]
            obj_name = f"tmp/{db_file.id}.{file_type}"
            db_file.object_name = obj_name
            db_file.remark = json.dumps({
                "new_name": original_file_name,
                "old_name": old_name}, ensure_ascii=False)
            # Uploaded to minio, do not modify the database, it is up to the front-end to decide whether to overwrite or not. If it is overwritten, the retry interface
            minio_client.put_object_tmp_sync(db_file.object_name, filepath)
            cls.remove_unused_file(file_info.file_path)
            db_file.status = KnowledgeFileStatus.FAILED.value
            db_file.split_rule = str_split_rule
            # Update file size information
            db_file.file_size = file_size
            return db_file

        # Insert new data, upload the original file tominio
        db_file = KnowledgeFile(
            knowledge_id=knowledge.id,
            file_name=original_file_name,
            file_size=file_size,
            md5=md5_,
            split_rule=str_split_rule,
            user_id=login_user.user_id,
            user_name=login_user.user_name,
            updater_id=login_user.user_id,
            updater_name=login_user.user_name,
            **file_kwargs if file_kwargs else {},
        )
        db_file = KnowledgeFileDao.add_file(db_file)
        cls.audit_telemetry_service.telemetry_new_knowledge_file(login_user)
        # Saving original files
        db_file.object_name = KnowledgeUtils.get_knowledge_file_object_name(db_file.id, db_file.file_name)
        minio_client.put_object_sync(bucket_name=minio_client.bucket, object_name=db_file.object_name,
                                     file=filepath)
        cls.remove_unused_file(file_info.file_path)

        logger.info("upload_original_file path={}", db_file.object_name)
        KnowledgeFileDao.update(db_file)
        return db_file

    @classmethod
    def remove_unused_file(cls, file_path: str):
        """Remove unused files in minio"""
        minio_client = get_minio_storage_sync()
        minio_share_host = minio_client.get_minio_share_host()
        if file_path.startswith(minio_share_host):
            url_obj = urlparse(file_path)
            bucket_name, object_name = url_obj.path.replace(minio_share_host, "", 1).lstrip("/").split('/', 1)
            minio_client.remove_object_sync(bucket_name=bucket_name, object_name=object_name)

    @classmethod
    def get_knowledge_files_title(cls, db_knowledge: Knowledge, files: List[KnowledgeFile]) -> Dict[str, str]:
        """Adoption of documentsidGet file title"""
        if not files:
            return {}
        files = [one for one in files if one.status == KnowledgeFileStatus.SUCCESS.value]
        if not files:
            return {}
        file_title_map: Dict[str, str] = {}
        try:
            es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=db_knowledge)
            search_data = {
                "size": len(files),
                "sort": [
                    {
                        "metadata.chunk_index": {
                            "order": "asc",
                            "missing": 0,
                            "unmapped_type": "long",
                        }
                    }
                ],
                "post_filter": {
                    "terms": {"metadata.document_id": [one.id for one in files]}
                },
                "collapse": {"field": "metadata.document_id"},
            }
            es_res = es_client.client.search(
                index=db_knowledge.index_name, body=search_data
            )
            for one in es_res["hits"]["hits"]:
                file_title_map[str(one["_source"]["metadata"]["document_id"])] = one["_source"]["metadata"]["abstract"]
        except Exception as e:
            # maybe es index not exist so ignore this error
            logger.warning(f"act=get_knowledge_files error={str(e)}")
            pass
        return file_title_map

    @classmethod
    def get_knowledge_files(
            cls,
            request: Request,
            login_user: UserPayload,
            knowledge_id: int,
            file_name: str = None,
            status: List[int] = None,
            page: int = 1,
            page_size: int = 10,
            file_ids: List[int] = None,
    ) -> (List[KnowledgeFileResp], int, bool):
        db_knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not db_knowledge:
            raise NotFoundError.http_exception()

        if not login_user.access_check(
                db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE
        ):
            raise UnAuthorizedError.http_exception()

        res = KnowledgeFileDao.get_file_by_filters(
            knowledge_id, file_name, status, page, page_size, file_ids
        )
        total = KnowledgeFileDao.count_file_by_filters(knowledge_id, file_name, status)

        # get file title from es
        finally_res = []
        file_title_map = cls.get_knowledge_files_title(db_knowledge, res)
        file_tags_map = TagDao.get_tags_by_resource(
            ResourceTypeEnum.KNOWLEDGE_FILE,
            [str(one.id) for one in res],
        ) if res else {}
        timeout_files = []
        for index, one in enumerate(res):
            finally_res.append(KnowledgeFileResp(**one.model_dump()))
            # Parsing more than one day, setting status to failed
            if one.status in [KnowledgeFileStatus.PROCESSING.value, KnowledgeFileStatus.WAITING.value] and (
                    datetime.now() - one.update_time).total_seconds() > 86400:
                timeout_files.append(one.id)
                continue
            finally_res[index].title = file_title_map.get(str(one.id), "")
            finally_res[index].tags = file_tags_map.get(str(one.id), [])
        if timeout_files:
            KnowledgeFileDao.update_file_status(timeout_files, KnowledgeFileStatus.TIMEOUT,
                                                KnowledgeFileFailedError(
                                                    data={"exception": 'Parsing time exceeds 24 hours'}).to_json_str())

        return (
            finally_res,
            total,
            login_user.access_check(
                db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE_WRITE
            ),
        )

    @classmethod
    def delete_knowledge_file(
            cls, request: Request, login_user: UserPayload, file_ids: List[int]
    ):
        from bisheng.worker.knowledge import file_worker

        knowledge_file = KnowledgeFileDao.select_list(file_ids)
        if not knowledge_file:
            raise NotFoundError.http_exception()
        db_knowledge = KnowledgeDao.query_by_id(knowledge_file[0].knowledge_id)
        if not login_user.access_check(
                db_knowledge.user_id, str(db_knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()

        # <g id="Bold">Medical Treatment:</g>vectordb
        delete_knowledge_file_vectors(file_ids)
        KnowledgeFileDao.delete_batch(file_ids)
        cls.audit_telemetry_service.telemetry_delete_knowledge_file(login_user)

        # Delete Audit Log for Knowledge Base Files
        cls.delete_knowledge_file_hook(
            request, login_user, db_knowledge.id, knowledge_file
        )

        # 5Minutes to check if the file was actually deleted
        file_worker.delete_knowledge_file_celery.apply_async(args=(file_ids, knowledge_file[0].knowledge_id, True),
                                                             countdown=300)

        return True

    @classmethod
    def delete_knowledge_file_hook(
            cls,
            request: Request,
            login_user: UserPayload,
            knowledge_id: int,
            file_list: List[KnowledgeFile],
    ):
        logger.info(
            f"act=delete_knowledge_file_hook user={login_user.user_name} knowledge_id={knowledge_id}"
        )
        cls.audit_telemetry_service.audit_delete_knowledge_file(login_user, request, knowledge_id, file_list)

    @classmethod
    def judge_knowledge_access(cls, login_user: UserPayload, knowledge_id: int, access_type: AccessType) -> Knowledge:
        db_knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not db_knowledge:
            raise NotFoundError.http_exception()

        if not login_user.access_check(
                db_knowledge.user_id, str(knowledge_id), access_type
        ):
            raise UnAuthorizedError.http_exception()
        return db_knowledge

    @classmethod
    def get_knowledge_chunks(
            cls,
            request: Request,
            login_user: UserPayload,
            knowledge_id: int,
            file_ids: List[int] = None,
            keyword: str = None,
            page: int = None,
            limit: int = None,
    ) -> (List[FileChunk], int):
        db_knowledge = cls.judge_knowledge_access(login_user, knowledge_id, AccessType.KNOWLEDGE)

        es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(db_knowledge)

        search_data = {
            "from": (page - 1) * limit,
            "size": limit,
            "sort": [
                {
                    "metadata.document_id": {
                        "order": "desc",
                        "missing": 0,
                        "unmapped_type": "long",
                    }
                },
                {
                    "metadata.chunk_index": {
                        "order": "asc",
                        "missing": 0,
                        "unmapped_type": "long",
                    }
                },
            ],
        }
        if file_ids:
            search_data["post_filter"] = {"terms": {"metadata.document_id": file_ids}}
        if keyword:
            search_data["query"] = {"match_phrase": {"text": keyword}}
        try:
            res = es_client.client.search(index=db_knowledge.index_name, body=search_data)
        except Exception as e:
            logger.warning(f"act=get_knowledge_chunks error={str(e)}")
            raise KnowledgeChunkError.http_exception()

        # Query the file information corresponding to the next block
        file_ids = set()
        result = []
        for one in res["hits"]["hits"]:
            file_ids.add(one["_source"]["metadata"]["document_id"])
        file_map = {}
        if file_ids:
            file_list = KnowledgeFileDao.get_file_by_ids(list(file_ids))
            file_map = {one.id: one for one in file_list}
        for one in res["hits"]["hits"]:
            file_id = one["_source"]["metadata"]["document_id"]
            file_info = file_map.get(file_id, None)
            # Filter document summary contents of file names and summaries
            result.append(
                FileChunk(
                    text=KnowledgeUtils.split_chunk_metadata(one["_source"]["text"]),
                    metadata=one["_source"]["metadata"],
                    parse_type=file_info.parse_type if file_info else None,
                )
            )
        return result, res["hits"]["total"]["value"]

    @classmethod
    def update_chunk_updater_info(cls, vector_client, es_client, db_knowledge, file_id, login_user):
        # Product Requirements！！！！！！！
        logger.debug(f"start update_milvus_chunk_updater_info user={login_user.user_name}")
        output_fields = [s.name for s in vector_client.col.schema.fields]
        iterator = vector_client.col.query_iterator(
            expr=f"document_id == {file_id}",
            output_fields=output_fields,
            timeout=10,
        )
        update_time = int(datetime.now().timestamp())
        while True:
            result = iterator.next()
            if not result:
                iterator.close()
                break
            for record in result:
                if not record.get("pk") or not record.get("vector"):
                    raise ValueError("milvus chunk pk field or vector field is None")
                record["updater"] = login_user.user_name
                record["update_time"] = update_time
                vector_client.col.upsert(record)
        logger.debug(f"update_milvus_chunk_updater_info over")

        res = es_client.client.update_by_query(
            index=db_knowledge.index_name,
            body={
                "query": {
                    "bool": {
                        "must": {"match": {"metadata.document_id": file_id}},
                    }
                },
                "script": {
                    "source": "ctx._source.metadata.updater=params.updater;ctx._source.metadata.update_time=params.update_time;",
                    "params": {"updater": login_user.user_name, "update_time": update_time},
                },
            },
            conflicts="proceed",
        )
        logger.debug(f"update_es_chunk_updater_info: {res}")

    @classmethod
    def update_knowledge_chunk(
            cls,
            request: Request,
            login_user: UserPayload,
            knowledge_id: int,
            file_id: int,
            chunk_index: int,
            text: str,
            bbox: str,
    ):
        db_knowledge = cls.judge_knowledge_access(login_user, knowledge_id, AccessType.KNOWLEDGE_WRITE)

        logger.info(
            f"act=update_vector knowledge_id={knowledge_id} document_id={file_id} chunk_index={chunk_index}"
        )
        vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(login_user.user_id, db_knowledge)
        # search metadata
        output_fields = [s.name for s in vector_client.col.schema.fields if s.name != "vector"]
        res = vector_client.col.query(
            expr=f"document_id == {file_id} && chunk_index == {chunk_index}",
            output_fields=output_fields,
            timeout=10,
        )
        metadata = []
        pk = []
        for one in res:
            pk.append(one.pop("pk"))
            metadata.append(one)
        if not metadata:
            raise ValueError("chunk not found in vector db")
        # insert data
        logger.info(f"act=add_vector {knowledge_id}")
        new_metadata = metadata[0]
        new_metadata["bbox"] = bbox
        new_text = KnowledgeUtils.aggregate_chunk_metadata(text, new_metadata)
        res = vector_client.add_texts([new_text], [new_metadata], timeout=10)
        # delete data
        logger.info(f"act=delete_vector pk={pk}")
        res = vector_client.col.delete(f"pk in {pk}", timeout=10)
        logger.info(f"act=update_vector_over {res}")

        logger.info(
            f"act=update_es knowledge_id={knowledge_id} document_id={file_id} chunk_index={chunk_index}"
        )
        es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(db_knowledge)
        res = es_client.client.update_by_query(
            index=db_knowledge.index_name,
            body={
                "query": {
                    "bool": {
                        "must": {"match": {"metadata.document_id": file_id}},
                        "filter": {"match": {"metadata.chunk_index": chunk_index}},
                    }
                },
                "script": {
                    "source": "ctx._source.text=params.text;ctx._source.metadata.bbox=params.bbox;",
                    "params": {"text": new_text, "bbox": bbox},
                },
            },
        )
        logger.info(f"act=update_es_chunk_over {res}")

        # update metadata updater and update_time
        cls.update_chunk_updater_info(vector_client, es_client, db_knowledge, file_id, login_user)

        KnowledgeFileDao.update_file_updater(file_id, login_user.user_id, login_user.user_name)

        return True

    @classmethod
    def delete_knowledge_chunk(
            cls,
            request: Request,
            login_user: UserPayload,
            knowledge_id: int,
            file_id: int,
            chunk_index: int,
    ):
        db_knowledge = cls.judge_knowledge_access(login_user, knowledge_id, AccessType.KNOWLEDGE_WRITE)

        logger.info(
            f"act=delete_vector knowledge_id={knowledge_id} document_id={file_id} chunk_index={chunk_index}"
        )
        vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(login_user.user_id, db_knowledge)
        res = vector_client.col.delete(
            expr=f"document_id == {file_id} && chunk_index == {chunk_index}",
            timeout=10,
        )
        logger.info(f"act=delete_vector_over {res}")

        logger.info(
            f"act=delete_es knowledge_id={knowledge_id} document_id={file_id} chunk_index={chunk_index} res={res}"
        )
        es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(db_knowledge)
        res = es_client.client.delete_by_query(
            index=db_knowledge.index_name,
            query={
                "bool": {
                    "must": {"match": {"metadata.document_id": file_id}},
                    "filter": {"match": {"metadata.chunk_index": chunk_index}},
                }
            },
            conflicts="proceed",
        )
        logger.info(f"act=delete_es_over {res}")

        cls.update_chunk_updater_info(vector_client, es_client, db_knowledge, file_id, login_user)

        KnowledgeFileDao.update_file_updater(file_id, login_user.user_id, login_user.user_name)

        return True

    @classmethod
    def get_file_share_with_auth(cls, login_user: UserPayload, file_id: int) -> Tuple[str, str]:
        """ Get the original download address of the file with authentication """
        file = KnowledgeFileDao.query_by_id_sync(file_id)
        if not file:
            raise NotFoundError(msg="file not found")
        knowledge_info = KnowledgeDao.query_by_id(file.knowledge_id)
        if not knowledge_info:
            raise NotFoundError(msg="knowledge not found")
        if not login_user.access_check(knowledge_info.user_id, str(knowledge_info.id), AccessType.KNOWLEDGE):
            raise UnAuthorizedError()
        return cls.get_file_share_url(file=file)

    @classmethod
    def get_file_share_url(cls, file_id: int = None, file: KnowledgeFile = None) -> Tuple[str, str]:
        """ Get the original download address of the file And Corresponding preview file download address """
        if file is None:
            file = KnowledgeFileDao.query_by_id_sync(file_id)
        if not file:
            raise NotFoundError(msg="file not found")
        minio_client = get_minio_storage_sync()
        original_object_name = cls.resolve_source_object_name(file.id, file.file_name, file.object_name)
        preview_object_name = cls.resolve_preview_object_name(
            file.id, file.file_name, file.preview_file_object_name
        )
        if file.preview_file_object_name:
            original_url = cls.get_file_share_url_with_empty(original_object_name)
            preview_url = cls.get_file_share_url_with_empty(preview_object_name)
        # 130File parsing prior to version
        elif file.parse_type in [ParseType.LOCAL.value, ParseType.UNS.value]:
            original_url = cls.get_file_share_url_with_empty(original_object_name)
            preview_url = ""
            if minio_client.object_exists_sync(object_name=str(file.id)):
                preview_url = minio_client.get_share_link_sync(str(file.id))
        else:
            original_url = cls.get_file_share_url_with_empty(original_object_name)
            preview_url = ""
            if preview_object_name:
                preview_url = cls.get_file_share_url_with_empty(preview_object_name)
        return original_url, preview_url

    @classmethod
    def get_file_share_url_with_empty(cls, object_name: str) -> str:
        """
        Get a shared link to a file
        :param object_name: Files inminioObject name in
        :return: File sharing link
        """

        minio_client = get_minio_storage_sync()
        if minio_client.object_exists_sync(minio_client.bucket, object_name):
            return minio_client.get_share_link_sync(object_name)
        return ""

    @classmethod
    def get_file_bbox(
            cls, request: Request, login_user: UserPayload, file_id: int
    ) -> Any:
        file_info = KnowledgeFileDao.select_list([file_id])
        file_info = file_info[0]
        if not file_info.bbox_object_name:
            return None

        minio_client = get_minio_storage_sync()

        # download bbox file
        resp = minio_client.get_object_sync(bucket_name=minio_client.bucket, object_name=file_info.bbox_object_name)
        return json.loads(resp.decode("utf-8"))

    @classmethod
    async def copy_knowledge(
            cls,
            request,
            background_tasks: BackgroundTasks,
            login_user: UserPayload,
            knowledge: Knowledge,
            knowledge_name: str = None,
    ) -> Any:
        from bisheng.worker.knowledge import file_worker

        await KnowledgeDao.async_update_state(knowledge.id, KnowledgeState.COPYING, update_time=knowledge.update_time)
        knowldge_dict = knowledge.model_dump()
        knowldge_dict.pop("id")
        knowldge_dict.pop("create_time")
        knowldge_dict.pop("update_time", None)
        knowldge_dict.pop("collection_name", None)
        knowldge_dict.pop("index_name", None)
        knowldge_dict["name"] = f"{knowledge.name} Copy"[:200] if not knowledge_name else knowledge_name[:200]

        knowldge_dict["state"] = KnowledgeState.UNPUBLISHED.value
        knowledge_new = Knowledge(**knowldge_dict)

        target_knowlege = cls.create_knowledge_base(request, login_user, knowledge_new)

        params = {
            "source_knowledge_id": knowledge.id,
            "target_id": target_knowlege.id,
            "login_user_id": login_user.user_id,
        }
        file_worker.file_copy_celery.delay(params)
        return target_knowlege

    @classmethod
    async def copy_qa_knowledge(
            cls,
            request,
            login_user: UserPayload,
            qa_knowledge: Knowledge,
            knowledge_name: str = None,
    ) -> Any:
        await KnowledgeDao.async_update_state(qa_knowledge.id, KnowledgeState.COPYING,
                                              update_time=qa_knowledge.update_time)
        qa_knowldge_dict = qa_knowledge.model_dump()
        qa_knowldge_dict.pop("id")
        qa_knowldge_dict.pop("create_time")
        qa_knowldge_dict.pop("update_time", None)
        qa_knowldge_dict["user_id"] = login_user.user_id
        qa_knowldge_dict["index_name"] = generate_knowledge_index_name()
        qa_knowldge_dict["collection_name"] = qa_knowldge_dict["index_name"]
        qa_knowldge_dict["name"] = f"{qa_knowledge.name} Copy"[:200] if not knowledge_name else knowledge_name[:200]
        qa_knowldge_dict["state"] = KnowledgeState.UNPUBLISHED.value
        qa_knowledge_new = Knowledge(**qa_knowldge_dict)
        target_qa_knowlege = await KnowledgeDao.async_insert_one(qa_knowledge_new)

        cls.create_knowledge_hook(request, login_user, target_qa_knowlege)

        from bisheng.worker.knowledge.qa import copy_qa_knowledge_celery
        copy_qa_knowledge_celery.delay(source_knowledge_id=qa_knowledge.id, target_knowledge_id=target_qa_knowlege.id,
                                       login_user_id=login_user.user_id)

        return target_qa_knowlege

    @classmethod
    def judge_qa_knowledge_write(
            cls, login_user: UserPayload, qa_knowledge_id: int
    ) -> Knowledge:
        db_knowledge = KnowledgeDao.query_by_id(qa_knowledge_id)
        # Query the current knowledge base, whether there are write permissions
        if not db_knowledge:
            raise NotFoundError()
        if not login_user.access_check(
                db_knowledge.user_id, str(qa_knowledge_id), AccessType.KNOWLEDGE
        ):
            raise UnAuthorizedError.http_exception()

        if db_knowledge.type != KnowledgeTypeEnum.QA.value:
            raise KnowledgeNotQAError()
        return db_knowledge

    @classmethod
    async def batch_download_files(
            cls,
            login_user: UserPayload,
            knowledge_id: int,
            file_ids: List[int],
    ) -> str:
        """Batch download knowledge-base files.

        Business rules (from M2 spec):
        - 1 file  → return a MinIO presigned URL directly pointing to the original object.
        - ≥2 files → pack into a ZIP archive named ``{knowledge_name}{YYYYMMDD_HHMM}.zip``,
          upload to the MinIO *tmp* bucket, and return a presigned URL valid for 7 days.

        Permission: the caller must have at least ``AccessType.KNOWLEDGE`` (read) access.
        """
        import os
        import tempfile
        import zipfile
        from pathlib import Path

        # ── 1. Permission check ──────────────────────────────────────────────────
        knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge:
            raise NotFoundError(msg="knowledge not found")
        if not login_user.access_check(knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE):
            raise UnAuthorizedError()

        if not file_ids:
            raise NotFoundError(msg="file_ids must not be empty")

        # ── 2. Query file records ────────────────────────────────────────────────
        db_files: List[KnowledgeFile] = KnowledgeFileDao.select_list(file_ids)
        # Keep only files that actually belong to this knowledge base
        db_files = [f for f in db_files if f.knowledge_id == knowledge_id]
        if not db_files:
            raise NotFoundError(msg="no valid files found")

        minio_client = get_minio_storage_sync()

        # ── 3. Single-file shortcut: return presigned URL directly ───────────────
        if len(db_files) == 1:
            file = db_files[0]
            object_name = file.object_name
            if not object_name:
                raise NotFoundError(msg="file has no stored object")
            return minio_client.get_share_link_sync(object_name)

        # ── 4. Multi-file: pack into ZIP, upload to tmp bucket, return URL ───────
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        zip_name = f"{knowledge.name}{timestamp}.zip"
        zip_uuid = generate_uuid()

        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, zip_name)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in db_files:
                    object_name = file.object_name
                    if not object_name:
                        continue
                    local_path = os.path.join(tmp_dir, file.file_name)
                    try:
                        resp = minio_client.download_object_sync(object_name=object_name)
                        with open(local_path, "wb") as fh:
                            for chunk in resp.stream(65536):
                                fh.write(chunk)
                        zf.write(local_path, arcname=file.file_name)
                    except Exception as exc:
                        logger.warning(f"batch_download: skip file {file.id} due to error: {exc}")
                    finally:
                        try:
                            resp.close()
                            resp.release_conn()
                        except Exception:
                            pass

            # ── 5. Upload ZIP to MinIO tmp bucket ────────────────────────────────
            minio_object_name = f"download/{zip_uuid}/{zip_name}"
            await minio_client.put_object_tmp(minio_object_name, Path(zip_path), content_type="application/zip")
            share_url = await minio_client.get_share_link(
                minio_object_name,
                bucket=minio_client.tmp_bucket,
                clear_host=True,
                expire_days=7,
            )

        return share_url

    # ──────────────────────────── Tags ───────────────────────────────────
    @classmethod
    async def get_knowledge_tags(
            cls,
            login_user: UserPayload,
            knowledge_id: int,
            keyword: Optional[str] = None,
            page: int = 1,
            limit: int = 10,
    ) -> Tuple[List[Tag], int]:
        await cls._get_readable_knowledge(login_user=login_user, knowledge_id=knowledge_id)
        keyword = keyword.strip() if keyword else None
        tags = await TagDao.asearch_tags(
            keyword=keyword,
            page=page,
            limit=limit,
            business_type=TagBusinessTypeEnum.KNOWLEDGE,
            business_id=str(knowledge_id),
        )
        total = await TagDao.acount_tags(
            keyword=keyword,
            business_type=TagBusinessTypeEnum.KNOWLEDGE,
            business_id=str(knowledge_id),
        )
        return tags, total

    @classmethod
    async def add_knowledge_tag(cls, login_user: UserPayload, knowledge_id: int, tag_name: str) -> Tag:
        await cls._get_writable_knowledge(login_user=login_user, knowledge_id=knowledge_id)

        existing_tags = await TagDao.get_tags_by_business(business_type=TagBusinessTypeEnum.KNOWLEDGE,
                                                          business_id=str(knowledge_id), name=tag_name)
        if any(t.name == tag_name for t in existing_tags):
            raise KnowledgeTagExistError()

        new_tag = Tag(
            name=tag_name,
            user_id=login_user.user_id,
            business_type=TagBusinessTypeEnum.KNOWLEDGE,
            business_id=str(knowledge_id),
        )
        return await TagDao.ainsert_tag(new_tag)

    @classmethod
    async def update_knowledge_tag(cls, login_user: UserPayload, knowledge_id: int, tag_id: int, tag_name: str) -> Tag:
        await cls._get_writable_knowledge(login_user=login_user, knowledge_id=knowledge_id)

        tag = await TagDao.get_tag(tag_id)
        if not tag or tag.business_id != str(knowledge_id) or tag.business_type != TagBusinessTypeEnum.KNOWLEDGE:
            raise KnowledgeTagNotExistError()

        return await TagDao.aupdate_tag(tag_id, name=tag_name)

    @classmethod
    async def delete_knowledge_tag(cls, login_user: UserPayload, knowledge_id: int, tag_id: int):
        await cls._get_writable_knowledge(login_user=login_user, knowledge_id=knowledge_id)
        return await TagDao.delete_business_tag(tag_id, business_id=str(knowledge_id),
                                                business_type=TagBusinessTypeEnum.KNOWLEDGE)

    @classmethod
    async def update_file_tags(cls, login_user: UserPayload, knowledge_id: int, file_id: int, tag_ids: List[int]):
        """ 设置单文件的标签 (全量替换) """
        tag_ids = cls._deduplicate_tag_ids(tag_ids)
        if len(tag_ids) > 5:
            raise KnowledgeFileTagLimitError()

        await cls._get_writable_knowledge(login_user=login_user, knowledge_id=knowledge_id)

        file_record = await KnowledgeFileDao.query_by_id(file_id)
        if not file_record or file_record.knowledge_id != knowledge_id:
            raise NotFoundError(msg="文档不存在")

        await cls._validate_knowledge_tag_ids(knowledge_id, tag_ids)

        resource_id = str(file_id)
        resource_type = ResourceTypeEnum.KNOWLEDGE_FILE
        await TagDao.aupdate_resource_tags(tag_ids, resource_id, resource_type, login_user.user_id)

    @classmethod
    async def batch_add_file_tags(cls, login_user: UserPayload, knowledge_id: int, file_ids: List[int], tag_ids: List[int]):
        """ 批量添加标签到文档 """
        tag_ids = cls._deduplicate_tag_ids(tag_ids)
        if len(tag_ids) > 5:
            raise KnowledgeFileTagLimitError()

        await cls._get_writable_knowledge(login_user=login_user, knowledge_id=knowledge_id)

        if not file_ids or not tag_ids:
            return

        await cls._validate_knowledge_tag_ids(knowledge_id, tag_ids)

        files = await KnowledgeFileDao.aget_file_by_ids(file_ids)
        valid_file_ids = [f.id for f in files if f.knowledge_id == knowledge_id]
        if not valid_file_ids:
            return

        resource_type = ResourceTypeEnum.KNOWLEDGE_FILE
        existing_tag_map = await TagDao.aget_resource_tag_ids_batch(
            [str(file_id) for file_id in valid_file_ids],
            resource_type,
        )
        for file_id in valid_file_ids:
            current_tag_ids = set(existing_tag_map.get(str(file_id), []))
            if len(current_tag_ids.union(tag_ids)) > 5:
                raise KnowledgeFileTagLimitError()
            await TagDao.add_tags(tag_ids, str(file_id), resource_type, login_user.user_id)

    @classmethod
    async def apply_tag_pre_filter(cls, tag_ids: List[int], knowledge_id: int) -> Optional[List[str]]:
        """
        根据标签 ID 获取 document_id (知识库文件的 file_id 的字符串列表)，用于传入向量检索的 filter_expr。
        返回 None 表示无需过滤（未指定标签）。
        返回 [] 表示指定了标签但没有找到任何文件（检索应返回空）。
        """
        if not tag_ids:
            return None

        links = await TagDao.aget_resources_by_tags(tag_ids, ResourceTypeEnum.KNOWLEDGE_FILE)

        # We need the resource IDs from links, but we must verify they belong to knowledge_id
        # To avoid extra DB queries, if we assume tags are already scoped to knowledge_id,
        # we can just return the resource_ids. But to be safe, let's filter valid file ids.
        if not links:
            return []

        resource_ids = list({link.resource_id for link in links})

        # Verify the resources actually belong to this knowledge base
        file_ids = [int(rid) for rid in resource_ids if rid.isdigit()]
        if not file_ids:
            return []

        files = await KnowledgeFileDao.aget_file_by_ids(file_ids)
        valid_file_ids = [str(f.id) for f in files if f.knowledge_id == knowledge_id]

        return valid_file_ids
