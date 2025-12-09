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
    KnowledgeNoEmbeddingError,
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
                page,
                limit,
            )
            total = await KnowledgeDao.acount_user_knowledge(
                login_user.user_id, knowledge_id_extra, knowledge_type, name
            )
        else:
            res = await KnowledgeDao.aget_all_knowledge(
                name, knowledge_type, page=page, limit=limit
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
                # 判断用户是否有权限
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

        # 判断知识库是否重名
        repeat_knowledge = KnowledgeDao.get_knowledge_by_name(
            knowledge.name, login_user.user_id
        )
        if repeat_knowledge:
            raise KnowledgeExistError.http_exception()

        db_knowledge = Knowledge.model_validate(knowledge)

        # 校验embedding模型
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

        # 插入到数据库
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

        # 处理创建知识库的后续操作
        cls.create_knowledge_hook(request, login_user, db_knowledge)
        return db_knowledge

    @classmethod
    def create_knowledge_hook(
            cls, request: Request, login_user: UserPayload, knowledge: Knowledge
    ):
        # 查询下用户所在的用户组
        user_group = UserGroupDao.get_user_group(login_user.user_id)
        if user_group:
            # 批量将知识库资源插入到关联表里
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

        # 记录审计日志
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

        # 清理 vector中的数据
        cls.delete_knowledge_file_in_vector(knowledge)

        # 清理minio的数据
        cls.delete_knowledge_file_in_minio(knowledge_id)

        # 删除mysql数据
        KnowledgeDao.delete_knowledge(knowledge_id, only_clear)

        telemetry_service.log_event_sync(user_id=login_user.user_id,
                                         event_type=BaseTelemetryTypeEnum.DELETE_KNOWLEDGE_BASE,
                                         trace_id=trace_id_var.get())

        if not only_clear:
            cls.delete_knowledge_hook(request, login_user, knowledge)
        return True

    @classmethod
    def delete_knowledge_file_in_vector(cls, knowledge: Knowledge, del_es: bool = True):
        # 处理vector
        embeddings = FakeEmbedding()
        vector_client = decide_vectorstores(
            knowledge.collection_name, "Milvus", embeddings
        )
        if isinstance(vector_client.col, Collection):
            logger.info(
                f"delete_vector col={knowledge.collection_name} knowledge_id={knowledge.id}"
            )
            if knowledge.collection_name.startswith("col"):
                # 单独的collection，直接删除即可
                vector_client.col.drop()
            else:
                # partition模式需要使用分区键删除
                pk = vector_client.col.query(
                    expr=f'knowledge_id=="{knowledge.id}"', output_fields=["pk"]
                )
                vector_client.col.delete(f"pk in {[p['pk'] for p in pk]}")
                # 判断milvus 是否还有entity
                if vector_client.col.is_empty:
                    vector_client.col.drop()
        if del_es:
            # 处理 es
            index_name = knowledge.index_name or knowledge.collection_name  # 兼容老版本
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

        # 删除知识库的审计日志
        AuditLogService.delete_knowledge(login_user, get_request_ip(request), knowledge)

        # 清理用户组下的资源
        GroupResourceDao.delete_group_resource_by_third_id(
            str(knowledge.id), ResourceTypeEnum.KNOWLEDGE
        )

    @classmethod
    def delete_knowledge_file_in_minio(cls, knowledge_id: int):
        # 每1000条记录去删除minio文件
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
        通过uuid的文件名，获取上传文件的原始名称
        """
        if not file_name:
            raise ServerError.http_exception("file_name is empty")
        # 从redis内获取
        uuid_file_name = file_name.split(".")[0]
        original_file_name = get_redis_client_sync().get(f"file_name:{uuid_file_name}") or file_name
        return original_file_name

    @classmethod
    async def save_upload_file_original_name(cls, original_file_name: str) -> str:
        """
        保存上传文件的原始名称到redis，生成一个uuid的文件名
        """
        if not original_file_name:
            raise ServerError.http_exception("original_file_name is empty")
        file_ext = original_file_name.split(".")[-1]
        # 生成一个唯一的uuid作为key
        uuid_file_name = generate_uuid()
        redis_client = await get_redis_client()
        await redis_client.aset(f"file_name:{uuid_file_name}", original_file_name, expiration=86400)
        return f"{uuid_file_name}.{file_ext}"

    @classmethod
    async def get_preview_file_chunk(
            cls, request: Request, login_user: UserPayload, req_data: KnowledgeFileProcess
    ) -> (str, str, List[FileChunk], Any):
        """
        0：解析模式，uns 或者 local
        1：转换后的文件路径
        2：切分后的chunk列表
        3: ocr识别后的bbox
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

        # 尝试从缓存获取
        if req_data.cache:
            if cache_value := await cls.async_get_preview_cache(cache_key):
                parse_type = await redis_client.aget(f"{cache_key}_parse_type")
                file_share_url = await redis_client.aget(f"{cache_key}_file_path")
                partitions = await redis_client.aget(f"{cache_key}_partitions")
                res = []

                # 根据分段顺序排序
                cache_value = dict(sorted(cache_value.items(), key=lambda x: int(x[0])))

                for key, val in cache_value.items():
                    res.append(FileChunk(text=val["text"], metadata=val["metadata"]))
                return parse_type, file_share_url, res, partitions

        filepath, file_name = await async_file_download(file_path)
        file_ext = file_name.split(".")[-1].lower()
        file_name = cls.get_upload_file_original_name(file_name)

        # 切分文本
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
            raise ValueError("文件解析为空")
        res = []
        cache_map = {}
        for index, val in enumerate(texts):
            metadata_dict = metadatas[index].model_dump()
            cache_map[index] = {"text": val, "metadata": metadata_dict}
            res.append(FileChunk(text=val, metadata=metadata_dict))

        # 默认是源文件的地址
        file_share_url = file_path
        if file_ext in ['doc', 'ppt', 'pptx']:
            file_share_url = ''
            new_file_name = KnowledgeUtils.get_tmp_preview_file_object_name(filepath)
            minio_client = await get_minio_storage()
            if await minio_client.object_exists(minio_client.tmp_bucket, new_file_name):
                file_share_url = minio_client.get_share_link(
                    new_file_name, minio_client.tmp_bucket
                )

        # 存入缓存
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
        """处理上传的文件, 只上传到minio和mysql"""
        knowledge = KnowledgeDao.query_by_id(req_data.knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()
        if not login_user.access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError.http_exception()
        failed_files = []
        # 处理每个文件
        process_files = []
        preview_cache_keys = []
        split_rule_dict = req_data.model_dump(include=set(list(FileProcessBase.model_fields.keys())))
        for one in req_data.file_list:
            # 上传源文件，创建数据记录
            db_file = cls.process_one_file(login_user, knowledge, one, split_rule_dict)
            # 不重复的文件数据使用异步任务去执行
            if db_file.status != KnowledgeFileStatus.FAILED.value:
                # 获取此文件的预览缓存key
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

        """处理上传的文件"""
        knowledge, failed_files, process_files, preview_cache_keys = (
            cls.save_knowledge_file(login_user, req_data)
        )

        # 异步处理文件解析和入库, 如果通过cache_key可以获取到数据，则使用cache中的数据来进行入库操作
        for index, one in enumerate(process_files):
            file_worker.parse_knowledge_file_celery.delay(one.id, preview_cache_keys[index], req_data.callback_url)

        cls.upload_knowledge_file_hook(request, login_user, knowledge, process_files)
        return failed_files + process_files

    @classmethod
    def sync_process_knowledge_file(
            cls, request: Request, login_user: UserPayload, req_data: KnowledgeFileProcess
    ) -> List[KnowledgeFile]:
        """同步处理上传的文件"""
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
        重建知识库文件
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
        db_file.status = KnowledgeFileStatus.PROCESSING.value  # 解析中
        db_file.updater_id = login_user.user_id
        db_file.updater_name = login_user.user_name
        db_file = await KnowledgeFileDao.async_update(db_file)

        file_path, _ = cls.get_file_share_url(db_file.id)

        preview_cache_key = cls.get_preview_cache_key(req_data.knowledge_id, file_path=file_path)
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
                # 把临时文件移动到正式目录
                new_object_name = KnowledgeUtils.get_knowledge_file_object_name(file.id, file.object_name)
                minio_client.copy_object_sync(source_object=file.object_name, dest_object=new_object_name,
                                              source_bucket=minio_client.tmp_bucket,
                                              dest_bucket=minio_client.bucket)
                file.object_name = new_object_name

            if input_file["remark"] and "对应已存在文件" in input_file["remark"]:
                file.file_name = input_file["remark"].split(" 对应已存在文件 ")[0]
                file.remark = ""

            file.split_rule = input_file["split_rule"]
            file.status = KnowledgeFileStatus.PROCESSING.value  # 解析中
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
        # 记录审计日志
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
        """处理上传的文件"""
        # download original file
        filepath, file_name = file_download(file_info.file_path)
        md5_ = os.path.splitext(os.path.basename(filepath))[0].split("_")[0]

        # 获取文件大小（单位为bytes）
        file_size = os.path.getsize(filepath)

        file_extension_name = file_name.split(".")[-1]
        original_file_name = cls.get_upload_file_original_name(file_name)
        # 是否包含重复文件
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
            db_file.remark = f"{original_file_name} 对应已存在文件 {old_name}"
            # 上传到minio，不修改数据库，由前端决定是否覆盖，覆盖的话调用重试接口
            with open(filepath, "rb") as file:
                minio_client.put_object_tmp_sync(db_file.object_name, file.read())
            db_file.status = KnowledgeFileStatus.FAILED.value
            db_file.split_rule = str_split_rule
            # 更新文件大小信息
            db_file.file_size = file_size
            return db_file

        # 插入新的数据，把原始文件上传到minio
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
        # 原始文件保存
        db_file.object_name = KnowledgeUtils.get_knowledge_file_object_name(db_file.id, db_file.file_name)
        minio_client.put_object_sync(bucket_name=minio_client.bucket, object_name=db_file.object_name,
                                     file=filepath)
        logger.info("upload_original_file path={}", db_file.object_name)
        KnowledgeFileDao.update(db_file)
        return db_file

    @classmethod
    def get_knowledge_files_title(cls, db_knowledge: Knowledge, files: List[KnowledgeFile]) -> Dict[str, str]:
        """通过文件id获取文件标题"""
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
            # 超过一天还在解析中的，将状态置为失败
            if one.status == KnowledgeFileStatus.PROCESSING.value and (
                    datetime.now() - one.update_time).total_seconds() > 86400:
                timeout_files.append(one.id)
                continue
            finally_res[index].title = file_title_map.get(str(one.id), "")
        if timeout_files:
            KnowledgeFileDao.update_file_status(timeout_files, KnowledgeFileStatus.FAILED,
                                                'Parsing time exceeds 24 hours')

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

        # 处理vectordb
        delete_knowledge_file_vectors(file_ids)
        KnowledgeFileDao.delete_batch(file_ids)
        telemetry_service.log_event_sync(user_id=login_user.user_id,
                                         event_type=BaseTelemetryTypeEnum.DELETE_KNOWLEDGE_FILE,
                                         trace_id=trace_id_var.get())

        # 删除知识库文件的审计日志
        cls.delete_knowledge_file_hook(
            request, login_user, db_knowledge.id, knowledge_file
        )

        # 5分钟检查下文件是否真的被删除
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
        # 记录审计日志
        # 记录审计日志
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

        # 查询下分块对应的文件信息
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
            # 过滤文件名和总结的文档摘要内容
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
        """ 获取文件原始下载地址 和 对应的预览文件下载地址 """
        file = KnowledgeFileDao.get_file_by_ids([file_id])
        if not file:
            raise NotFoundError.http_exception()
        file = file[0]
        minio_client = get_minio_storage_sync()
        # 130版本以前的文件解析
        if file.parse_type in [ParseType.LOCAL.value, ParseType.UNS.value]:
            original_url = minio_client.get_share_link(cls.get_knowledge_file_object_name(file.id, file.file_name))
            preview_url = minio_client.get_share_link(str(file.id))
        else:
            original_url = cls.get_file_share_url_with_empty(file.object_name)
            preview_url = ""
            # 130版本以后的文件解析逻辑，只有源文件和预览文件，不再都转pdf了
            if file.file_name.endswith(('.doc', '.ppt', '.pptx')):
                preview_object_name = KnowledgeUtils.get_knowledge_preview_file_object_name(file.id, file.file_name)
                preview_url = cls.get_file_share_url_with_empty(preview_object_name)
        return original_url, preview_url

    @classmethod
    def get_file_share_url_with_empty(cls, object_name: str) -> str:
        """
        获取文件的分享链接
        :param object_name: 文件在minio中的对象名称
        :return: 文件的分享链接
        """
        minio_client = get_minio_storage_sync()
        if minio_client.object_exists_sync(minio_client.bucket, object_name):
            return minio_client.get_share_link(object_name, minio_client.bucket)
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
        knowldge_dict["name"] = f"{knowledge.name} 副本"[:30]
        knowldge_dict["state"] = KnowledgeState.UNPUBLISHED.value
        knowledge_new = Knowledge(**knowldge_dict)
        target_knowlege = await KnowledgeDao.async_insert_one(knowledge_new)
        # celery 还没ok
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
        qa_knowldge_dict["name"] = f"{qa_knowledge.name} 副本"[:30]
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
        # 查询当前知识库，是否有写入权限
        if not db_knowledge:
            raise ServerError.http_exception(msg="当前知识库不可用，返回上级目录")
        if not login_user.access_check(
                db_knowledge.user_id, str(qa_knowledge_id), AccessType.KNOWLEDGE
        ):
            raise UnAuthorizedError.http_exception()

        if db_knowledge.type == KnowledgeTypeEnum.NORMAL.value:
            raise ServerError.http_exception(msg="知识库为普通知识库")
        return db_knowledge
