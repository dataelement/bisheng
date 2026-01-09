import json
import math
import os
from datetime import datetime
from typing import Any, Dict, List

from fastapi import BackgroundTasks, Request
from loguru import logger
from pymilvus import Collection

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.knowledge_imp import (
    KnowledgeUtils,
    decide_vectorstores,
    delete_knowledge_file_vectors,
    process_file_task,
    async_read_chunk_text,
)
from bisheng.api.v1.schema.knowledge import KnowledgeFileResp
from bisheng.api.v1.schemas import (
    FileChunk,
    FileProcessBase,
    KnowledgeFileOne,
    KnowledgeFileProcess,
    UpdatePreviewFileChunk, ExcelRule, KnowledgeFileReProcess,
)
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError, ServerError
from bisheng.common.errcode.knowledge import (
    KnowledgeChunkError,
    KnowledgeExistError,
    KnowledgeNoEmbeddingError, KnowledgeNotQAError, KnowledgeFileFailedError,
)
from bisheng.common.schemas.telemetry.event_data_schema import NewKnowledgeBaseEventData
from bisheng.common.services import telemetry_service
from bisheng.core.cache.redis_manager import get_redis_client_sync, get_redis_client
from bisheng.core.cache.utils import file_download, async_file_download
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync, get_minio_storage
from bisheng.database.models.group_resource import (
    GroupResource,
    GroupResourceDao,
    ResourceTypeEnum,
)
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.interface.embeddings.custom import FakeEmbedding
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
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models import LLMDao
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.utils import generate_uuid, generate_knowledge_index_name
from bisheng.utils import get_request_ip


class KnowledgeService(KnowledgeUtils):

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
    ) -> (List[KnowledgeRead], int):
        if not login_user.is_admin():
            knowledge_id_extra = []
            user_role = await UserRoleDao.aget_user_roles(login_user.user_id)
            if user_role:
                role_ids = [role.role_id for role in user_role]
                role_access = await RoleAccessDao.aget_role_access(role_ids, AccessType.KNOWLEDGE)
                if role_access:
                    knowledge_id_extra = [
                        int(access.third_id) for access in role_access
                    ]
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

        result = cls.convert_knowledge_read(login_user, res)
        return result, total

    @classmethod
    def convert_knowledge_read(
            cls, login_user: UserPayload, knowledge_list: List[Knowledge]
    ) -> List[KnowledgeRead]:
        db_user_ids = {one.user_id for one in knowledge_list}
        db_user_info = UserDao.get_user_by_ids(list(db_user_ids))
        db_user_dict = {one.user_id: one.user_name for one in db_user_info}
        res = []

        for one in knowledge_list:
            res.append(
                KnowledgeRead(
                    **one.model_dump(),
                    user_name=db_user_dict.get(one.user_id, str(one.user_id)),
                    copiable=login_user.access_check(
                        one.user_id, str(one.id), AccessType.KNOWLEDGE_WRITE
                    ),
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
        embed_info = LLMDao.get_model_by_id(int(db_knowledge.model))
        if not embed_info:
            raise KnowledgeNoEmbeddingError.http_exception()
        if embed_info.model_type != LLMModelType.EMBEDDING.value:
            raise KnowledgeNoEmbeddingError.http_exception()

        # generate index_name and collection_name
        db_knowledge.index_name = generate_knowledge_index_name()
        db_knowledge.collection_name = db_knowledge.index_name

        # Insert into Database
        db_knowledge.user_id = login_user.user_id
        db_knowledge = KnowledgeDao.insert_one(db_knowledge)

        try:
            vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(login_user.user_id,
                                                                                knowledge=db_knowledge,
                                                                                metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
            es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=db_knowledge,
                                                                        metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
            es_client._store._create_index_if_not_exists()
        except Exception as e:
            logger.exception("create knowledge index name error")

        # Handling the next steps in creating a Knowledge Base
        cls.create_knowledge_hook(request, login_user, db_knowledge)
        return db_knowledge

    @classmethod
    def create_knowledge_hook(
            cls, request: Request, login_user: UserPayload, knowledge: Knowledge
    ):
        # Query the user group the user belongs to under
        user_group = UserGroupDao.get_user_group(login_user.user_id)
        if user_group:
            # Batch Insert Knowledge Base Resources into Associated Tables
            batch_resource = []
            for one in user_group:
                batch_resource.append(
                    GroupResource(
                        group_id=one.group_id,
                        third_id=knowledge.id,
                        type=ResourceTypeEnum.KNOWLEDGE.value,
                    )
                )
            GroupResourceDao.insert_group_batch(batch_resource)

        # Log Audit Logs
        AuditLogService.create_knowledge(
            login_user, get_request_ip(request), knowledge.id
        )

        telemetry_service.log_event_sync(user_id=login_user.user_id,
                                         event_type=BaseTelemetryTypeEnum.NEW_KNOWLEDGE_BASE,
                                         trace_id=trace_id_var.get(),
                                         event_data=NewKnowledgeBaseEventData(
                                             kb_id=knowledge.id,
                                             kb_name=knowledge.name,
                                             kb_type=knowledge.type
                                         ))

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

        telemetry_service.log_event_sync(user_id=login_user.user_id,
                                         event_type=BaseTelemetryTypeEnum.DELETE_KNOWLEDGE_BASE,
                                         trace_id=trace_id_var.get())

        if not only_clear:
            cls.delete_knowledge_hook(request, login_user, knowledge)
        return True

    @classmethod
    def delete_knowledge_file_in_vector(cls, knowledge: Knowledge, del_es: bool = True):
        # <g id="Bold">Medical Treatment:</g>vector
        embeddings = FakeEmbedding()
        vector_client = decide_vectorstores(
            knowledge.collection_name, "Milvus", embeddings
        )
        if isinstance(vector_client.col, Collection):
            logger.info(
                f"delete_vector col={knowledge.collection_name} knowledge_id={knowledge.id}"
            )
            if knowledge.collection_name.startswith("col"):
                # Singularcollection, simply delete it
                vector_client.col.drop()
            else:
                # partitionMode requires partition key deletion
                pk = vector_client.col.query(
                    expr=f'knowledge_id=="{knowledge.id}"', output_fields=["pk"]
                )
                vector_client.col.delete(f"pk in {[p['pk'] for p in pk]}")
                # Judgingmilvus Are there any moreentity
                if vector_client.col.is_empty:
                    vector_client.col.drop()
        if del_es:
            # <g id="Bold">Medical Treatment:</g> es
            index_name = knowledge.index_name or knowledge.collection_name  # Compatible with older versions
            es_client = decide_vectorstores(index_name, "ElasticKeywordsSearch", embeddings)
            res = es_client.client.indices.delete(index=index_name, ignore=[400, 404])
            logger.info(f"act=delete_es index={index_name} res={res}")

    @classmethod
    def delete_knowledge_hook(
            cls, request: Request, login_user: UserPayload, knowledge: Knowledge
    ):
        logger.info(
            f"delete_knowledge_hook id={knowledge.id}, user: {login_user.user_id}"
        )

        # Delete Knowledge Base Audit Log
        AuditLogService.delete_knowledge(login_user, get_request_ip(request), knowledge)

        # Purge resources under user groups
        GroupResourceDao.delete_group_resource_by_third_id(
            str(knowledge.id), ResourceTypeEnum.KNOWLEDGE
        )

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
                if file[1]:
                    minio_client.remove_object_sync(object_name=file[1])

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
        if not await login_user.async_access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()

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

        # Split text
        texts, metadatas, parse_type, partitions = await async_read_chunk_text(
            login_user.user_id,
            filepath,
            file_name,
            req_data.separator,
            req_data.separator_rule,
            req_data.chunk_size,
            req_data.chunk_overlap,
            knowledge_id=req_data.knowledge_id,
            force_ocr=req_data.force_ocr,
            enable_formula=req_data.enable_formula,
            filter_page_header_footer=req_data.filter_page_header_footer,
            retain_images=req_data.retain_images,
            excel_rule=excel_rule,
            no_summary=True,
        )
        if len(texts) == 0:
            raise ValueError("File resolution is empty")
        res = []
        cache_map = {}
        for index, val in enumerate(texts):
            metadata_dict = metadatas[index].model_dump()
            cache_map[index] = {"text": val, "metadata": metadata_dict}
            res.append(FileChunk(text=val, metadata=metadata_dict))

        # Default is the address of the source file
        file_share_url = file_path
        if file_ext in ['doc', 'ppt', 'pptx']:
            file_share_url = ''
            new_file_name = KnowledgeUtils.get_tmp_preview_file_object_name(filepath)
            minio_client = await get_minio_storage()
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
        if not await login_user.async_access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()

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
                knowledge,
                process_files,
                req_data.separator,
                req_data.separator_rule,
                req_data.chunk_size,
                req_data.chunk_overlap,
                req_data.callback_url,
                req_data.extra,
                preview_cache_keys,
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
        from bisheng.worker.knowledge import file_worker

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

        split_rule_dict = req_data.model_dump(include=set(list(FileProcessBase.model_fields.keys())))
        if req_data.excel_rule is not None:
            split_rule_dict["excel_rule"] = req_data.excel_rule.model_dump()
        db_file.split_rule = json.dumps(split_rule_dict)
        db_file.status = KnowledgeFileStatus.WAITING.value  # Parsing
        db_file.updater_id = login_user.user_id
        db_file.updater_name = login_user.user_name
        db_file = await KnowledgeFileDao.async_update(db_file)

        preview_cache_key = cls.get_preview_cache_key(req_data.knowledge_id, file_path=req_data.file_path)
        file_worker.retry_knowledge_file_celery.delay(db_file.id, preview_cache_key, req_data.callback_url)

        return db_file.model_dump()

    @classmethod
    def retry_files(
            cls,
            request: Request,
            login_user: UserPayload,
            background_tasks: BackgroundTasks,
            req_data: dict,
    ):
        from bisheng.worker.knowledge import file_worker

        db_file_retry = req_data.get("file_objs")
        if not db_file_retry:
            return []
        id2input = {file.get("id"): file for file in db_file_retry}
        file_ids = list(id2input.keys())
        db_files: List[KnowledgeFile] = KnowledgeFileDao.select_list(file_ids=file_ids)
        if not db_files:
            return []
        knowledge = KnowledgeDao.query_by_id(db_files[0].knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()
        if not login_user.access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()
        res = []

        req_data["knowledge_id"] = knowledge.id

        minio_client = get_minio_storage_sync()

        for file in db_files:
            input_file = id2input.get(file.id)

            # file exist
            file.object_name = input_file.get("object_name", file.object_name)
            file_preview_cache_key = KnowledgeUtils.get_preview_cache_key(
                file.knowledge_id, input_file.get("file_path", "")
            )

            if file.object_name.startswith('tmp'):
                # Moving Temporary Files to the Official Directory
                new_object_name = KnowledgeUtils.get_knowledge_file_object_name(file.id, file.object_name)
                minio_client.copy_object_sync(source_object=file.object_name, dest_object=new_object_name,
                                              source_bucket=minio_client.tmp_bucket,
                                              dest_bucket=minio_client.bucket)
                file.object_name = new_object_name
            file.file_name = input_file.get("file_name", None) or file.file_name
            file.remark = ""
            file.split_rule = input_file["split_rule"]
            file.status = KnowledgeFileStatus.WAITING.value  # Parsing
            file.updater_id = login_user.user_id
            file.updater_name = login_user.user_name

            file = KnowledgeFileDao.update(file)
            res.append([file, file_preview_cache_key])
        tmp = []
        for one_file in res:
            file_worker.retry_knowledge_file_celery.delay(one_file[0].id, one_file[1], None)
            tmp.append(one_file[0])
        cls.upload_knowledge_file_hook(request, login_user, knowledge, tmp)
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
        AuditLogService.upload_knowledge_file(
            login_user, get_request_ip(request), knowledge.id, file_name
        )

    @classmethod
    def process_one_file(
            cls,
            login_user: UserPayload,
            knowledge: Knowledge,
            file_info: KnowledgeFileOne,
            split_rule: Dict,
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
            # Uploaded tominio, do not modify the database, it is up to the front-end to decide whether to overwrite or not. If it is overwritten, the retry interface
            with open(filepath, "rb") as file:
                minio_client.put_object_tmp_sync(db_file.object_name, file.read())
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
        )
        db_file = KnowledgeFileDao.add_file(db_file)
        telemetry_service.log_event_sync(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_KNOWLEDGE_FILE,
            trace_id=trace_id_var.get(),
        )
        # Saving original files
        db_file.object_name = KnowledgeUtils.get_knowledge_file_object_name(db_file.id, db_file.file_name)
        minio_client.put_object_sync(bucket_name=minio_client.bucket, object_name=db_file.object_name,
                                     file=filepath)
        logger.info("upload_original_file path={}", db_file.object_name)
        KnowledgeFileDao.update(db_file)
        return db_file

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
            embeddings = FakeEmbedding()
            es_client = decide_vectorstores(
                db_knowledge.index_name, "ElasticKeywordsSearch", embeddings
            )
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
        timeout_files = []
        for index, one in enumerate(res):
            finally_res.append(KnowledgeFileResp(**one.model_dump()))
            # Parsing more than one day, setting status to failed
            if one.status in [KnowledgeFileStatus.PROCESSING.value, KnowledgeFileStatus.WAITING.value] and (
                    datetime.now() - one.update_time).total_seconds() > 86400:
                timeout_files.append(one.id)
                continue
            finally_res[index].title = file_title_map.get(str(one.id), "")
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
        telemetry_service.log_event_sync(user_id=login_user.user_id,
                                         event_type=BaseTelemetryTypeEnum.DELETE_KNOWLEDGE_FILE,
                                         trace_id=trace_id_var.get())

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
        # Log Audit Logs
        # Log Audit Logs
        file_name = ""
        for one in file_list:
            file_name += "\n\n" + one.file_name
        AuditLogService.delete_knowledge_file(
            login_user, get_request_ip(request), knowledge_id, file_name
        )

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
        )
        logger.info(f"act=delete_es_over {res}")

        cls.update_chunk_updater_info(vector_client, es_client, db_knowledge, file_id, login_user)

        KnowledgeFileDao.update_file_updater(file_id, login_user.user_id, login_user.user_name)

        return True

    @classmethod
    def get_file_share_url(cls, file_id: int) -> (str, str):
        """ Get the original download address of the file And Corresponding preview file download address """
        file = KnowledgeFileDao.get_file_by_ids([file_id])
        if not file:
            raise NotFoundError()
        file = file[0]
        minio_client = get_minio_storage_sync()
        # 130File parsing prior to version
        if file.parse_type in [ParseType.LOCAL.value, ParseType.UNS.value]:
            original_url = minio_client.get_share_link_sync(cls.get_knowledge_file_object_name(file.id, file.file_name))
            preview_url = minio_client.get_share_link_sync(str(file.id))
        else:
            original_url = cls.get_file_share_url_with_empty(file.object_name)
            preview_url = ""
            # 130After the version of the file parsing logic, only the source file and preview file are no longer transferredpdfSettings Updated. what double check raws pls
            if file.file_name.endswith(('.doc', '.ppt', '.pptx')):
                preview_object_name = KnowledgeUtils.get_knowledge_preview_file_object_name(file.id, file.file_name)
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
        knowldge_dict["user_id"] = login_user.user_id
        knowldge_dict["index_name"] = generate_knowledge_index_name()
        knowldge_dict["collection_name"] = knowldge_dict["index_name"]
        knowldge_dict["name"] = f"{knowledge.name} Copy"[:200] if not knowledge_name else knowledge_name[:200]

        knowldge_dict["state"] = KnowledgeState.UNPUBLISHED.value
        knowledge_new = Knowledge(**knowldge_dict)
        target_knowlege = await KnowledgeDao.async_insert_one(knowledge_new)
        # celery not yetok
        params = {
            "source_knowledge_id": knowledge.id,
            "target_id": target_knowlege.id,
            "login_user_id": login_user.user_id,
        }
        cls.create_knowledge_hook(request, login_user, target_knowlege)
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
