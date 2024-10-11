import math
import os
import io
import time
from typing import List, Any
from uuid import uuid4
import json

from fastapi import Request, BackgroundTasks
from loguru import logger
from pymilvus import Collection

from bisheng.api.errcode.base import NotFoundError, UnAuthorizedError
from bisheng.api.errcode.knowledge import KnowledgeExistError, KnowledgeNoEmbeddingError, KnowledgeChunkError
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.knowledge_imp import decide_vectorstores, read_chunk_text, process_file_task, KnowledgeUtils, \
    delete_knowledge_file_vectors, retry_files
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import get_request_ip
from bisheng.api.v1.schemas import PreviewFileChunk, FileChunk, UpdatePreviewFileChunk, KnowledgeFileProcess, \
    KnowledgeFileOne, FileChunkMetadata
from bisheng.cache.utils import file_download
from bisheng.cache.redis import redis_client
from bisheng.database.models.group_resource import GroupResource, GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeDao, Knowledge, KnowledgeUpdate, KnowledgeRead, \
    KnowledgeTypeEnum
from bisheng.database.models.knowledge_file import KnowledgeFileDao, KnowledgeFile, KnowledgeFileStatus, ParseType
from bisheng.database.models.llm_server import LLMDao, LLMModelType
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.user_role import UserRoleDao
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.settings import settings
from bisheng.utils.minio_client import MinioClient
from bisheng.utils.embedding import decide_embeddings


class KnowledgeService(KnowledgeUtils):

    @classmethod
    def get_knowledge(cls, request: Request, login_user: UserPayload, knowledge_type: KnowledgeTypeEnum,
                      name: str = None, page: int = 1, limit: int = 10) -> (List[KnowledgeRead], int):
        if not login_user.is_admin():
            knowledge_id_extra = []
            user_role = UserRoleDao.get_user_roles(login_user.user_id)
            if user_role:
                role_ids = [role.role_id for role in user_role]
                role_access = RoleAccessDao.get_role_access(role_ids, AccessType.KNOWLEDGE)
                if role_access:
                    knowledge_id_extra = [int(access.third_id) for access in role_access]
            res = KnowledgeDao.get_user_knowledge(login_user.user_id, knowledge_id_extra,
                                                  knowledge_type, name, page, limit)
            total = KnowledgeDao.count_user_knowledge(login_user.user_id, knowledge_id_extra,
                                                      knowledge_type, name)
        else:
            res = KnowledgeDao.get_all_knowledge(name, knowledge_type, page=page, limit=limit)
            total = KnowledgeDao.count_all_knowledge(name, knowledge_type)

        db_user_ids = {one.user_id for one in res}
        db_user_info = UserDao.get_user_by_ids(list(db_user_ids))
        db_user_dict = {one.user_id: one.user_name for one in db_user_info}

        result = []
        for one in res:
            result.append(KnowledgeRead(**one.model_dump(), user_name=db_user_dict.get(one.user_id, one.user_id)))
        return result, total

    @classmethod
    def create_knowledge(cls, request: Request, login_user: UserPayload, knowledge: KnowledgeCreate) -> Knowledge:
        # 设置默认的is_partition
        knowledge.is_partition = knowledge.is_partition if knowledge.is_partition is not None \
            else settings.get_knowledge().get('vectorstores', {}).get('Milvus', {}).get('is_partition', True)

        # 判断知识库是否重名
        repeat_knowledge = KnowledgeDao.get_knowledge_by_name(knowledge.name, login_user.user_id)
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

        # 自动生成 es和milvus的 collection_name
        if not db_knowledge.collection_name:
            if knowledge.is_partition:
                embedding = knowledge.model
                suffix_id = settings.get_knowledge().get('vectorstores').get('Milvus', {}).get(
                    'partition_suffix', 1)
                db_knowledge.collection_name = f'partition_{embedding}_knowledge_{suffix_id}'
            else:
                # 默认collectionName
                db_knowledge.collection_name = f'col_{int(time.time())}_{str(uuid4())[:8]}'
        db_knowledge.index_name = f'col_{int(time.time())}_{str(uuid4())[:8]}'

        # 插入到数据库
        db_knowledge.user_id = login_user.user_id
        db_knowledge = KnowledgeDao.insert_one(db_knowledge)

        # 处理创建知识库的后续操作
        cls.create_knowledge_hook(request, login_user, db_knowledge)
        return db_knowledge

    @classmethod
    def create_knowledge_hook(cls, request: Request, login_user: UserPayload, knowledge: Knowledge):
        # 查询下用户所在的用户组
        user_group = UserGroupDao.get_user_group(login_user.user_id)
        if user_group:
            # 批量将知识库资源插入到关联表里
            batch_resource = []
            for one in user_group:
                batch_resource.append(GroupResource(
                    group_id=one.group_id,
                    third_id=knowledge.id,
                    type=ResourceTypeEnum.KNOWLEDGE.value))
            GroupResourceDao.insert_group_batch(batch_resource)

        # 记录审计日志
        AuditLogService.create_knowledge(login_user, get_request_ip(request), knowledge.id)
        return True

    @classmethod
    def update_knowledge(cls, request: Request, login_user: UserPayload, knowledge: KnowledgeUpdate) -> KnowledgeRead:
        db_knowledge = KnowledgeDao.query_by_id(knowledge.knowledge_id)
        if not db_knowledge:
            raise NotFoundError.http_exception()

        # judge access
        if not login_user.access_check(db_knowledge.user_id, str(db_knowledge.id), AccessType.KNOWLEDGE_WRITE):
            raise UnAuthorizedError.http_exception()

        if knowledge.name and knowledge.name != db_knowledge.name:
            repeat_knowledge = KnowledgeDao.get_knowledge_by_name(knowledge.name, db_knowledge.user_id)
            if repeat_knowledge and repeat_knowledge.id != db_knowledge.id:
                raise KnowledgeExistError.http_exception()
            db_knowledge.name = knowledge.name
        if knowledge.description:
            db_knowledge.description = knowledge.description

        db_knowledge = KnowledgeDao.update_one(db_knowledge)
        user = UserDao.get_user(db_knowledge.user_id)
        res = KnowledgeRead(**db_knowledge.model_dump(), user_name=user.user_name if user else db_knowledge.user_id)
        return res

    @classmethod
    def delete_knowledge(cls, request: Request, login_user: UserPayload, knowledge_id: int, only_clear: bool = False):
        knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()

        if not login_user.access_check(knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE_WRITE):
            raise UnAuthorizedError.http_exception()

        # 清理 vector中的数据
        cls.delete_knowledge_file_in_vector(knowledge)

        # 清理minio的数据
        cls.delete_knowledge_file_in_minio(knowledge_id)

        # 删除mysql数据
        KnowledgeDao.delete_knowledge(knowledge_id, only_clear)

        if not only_clear:
            cls.delete_knowledge_hook(request, login_user, knowledge)
        return True

    @classmethod
    def delete_knowledge_file_in_vector(cls, knowledge: Knowledge):
        # 处理vector
        embeddings = FakeEmbedding()
        vector_client = decide_vectorstores(knowledge.collection_name, 'Milvus', embeddings)
        if isinstance(vector_client.col, Collection):
            logger.info(f'delete_vector col={knowledge.collection_name} knowledge_id={knowledge.id}')
            if knowledge.collection_name.startswith('col'):
                # 单独的collection，直接删除即可
                vector_client.col.drop()
            else:
                # partition模式需要使用分区键删除
                pk = vector_client.col.query(expr=f'knowledge_id=="{knowledge.id}"', output_fields=['pk'])
                vector_client.col.delete(f"pk in {[p['pk'] for p in pk]}")
                # 判断milvus 是否还有entity
                if vector_client.col.is_empty:
                    vector_client.col.drop()

        # 处理 es
        index_name = knowledge.index_name or knowledge.collection_name  # 兼容老版本
        es_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)
        res = es_client.client.indices.delete(index=index_name, ignore=[400, 404])
        logger.info(f'act=delete_es index={index_name} res={res}')

    @classmethod
    def delete_knowledge_hook(cls, request: Request, login_user: UserPayload, knowledge: Knowledge):
        logger.info(f'delete_knowledge_hook id={knowledge.id}, user: {login_user.user_id}')

        # 删除知识库的审计日志
        AuditLogService.delete_knowledge(login_user, get_request_ip(request), knowledge)

        # 清理用户组下的资源
        GroupResourceDao.delete_group_resource_by_third_id(str(knowledge.id), ResourceTypeEnum.KNOWLEDGE)

    @classmethod
    def delete_knowledge_file_in_minio(cls, knowledge_id: int):
        # 每1000条记录去删除minio文件
        count = KnowledgeFileDao.count_file_by_knowledge_id(knowledge_id)
        if count == 0:
            return
        page_size = 1000
        page_num = math.ceil(count / page_size)
        minio_client = MinioClient()
        for i in range(page_num):
            file_list = KnowledgeFileDao.get_file_simple_by_knowledge_id(knowledge_id, i + 1,
                                                                         page_size)
            for file in file_list:
                minio_client.delete_minio(str(file[0]))
                if file[1]:
                    minio_client.delete_minio(file[1])

    @classmethod
    def get_preview_file_chunk(cls, request: Request, login_user: UserPayload, req_data: PreviewFileChunk) \
            -> (str, str, List[FileChunk], Any):
        """
         0：解析模式，uns 或者 local
         1：转换后的文件路径
         2：切分后的chunk列表
         3: ocr识别后的bbox
        """
        knowledge = KnowledgeDao.query_by_id(req_data.knowledge_id)
        if not login_user.access_check(knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE):
            raise UnAuthorizedError.http_exception()

        cache_key = cls.get_preview_cache_key(req_data.knowledge_id, req_data.file_path)

        # 尝试从缓存获取
        if req_data.cache:
            if cache_value := cls.get_preview_cache(cache_key):
                parse_type = redis_client.get(f"{cache_key}_parse_type")
                file_share_url = redis_client.get(f"{cache_key}_file_path")
                partitions = redis_client.get(f"{cache_key}_partitions")
                res = []
                for key, val in cache_value.items():
                    res.append(FileChunk(
                        text=val['text'],
                        metadata=val['metadata']
                    ))
                return parse_type, file_share_url, res, partitions

        filepath, file_name = file_download(req_data.file_path)

        # 切分文本
        texts, metadatas, parse_type, partitions = read_chunk_text(filepath, file_name, req_data.separator,
                                                                   req_data.separator_rule,
                                                                   req_data.chunk_size, req_data.chunk_overlap)
        res = []
        cache_map = {}
        for index, val in enumerate(texts):
            cache_map[index] = {
                'text': val,
                'metadata': metadatas[index]
            }
            res.append(FileChunk(
                text=val,
                metadata=metadatas[index]
            ))

        # 将转换后pdf文件上传到minio
        file_share_url = ""
        if parse_type == ParseType.UNS.value:
            minio_client = MinioClient()
            with open(filepath, 'rb') as f:
                minio_client.upload_tmp(f"{cache_key}.pdf", f.read())
            file_share_url = minio_client.get_share_link(f"{cache_key}.pdf", minio_client.tmp_bucket)

        # 存入缓存
        cls.save_preview_cache(cache_key, mapping=cache_map)
        redis_client.set(f"{cache_key}_parse_type", parse_type)
        redis_client.set(f"{cache_key}_file_path", file_share_url)
        redis_client.set(f"{cache_key}_partitions", partitions)
        return parse_type, file_share_url, res, partitions

    @classmethod
    def update_preview_file_chunk(cls, request: Request, login_user: UserPayload, req_data: UpdatePreviewFileChunk):
        knowledge = KnowledgeDao.query_by_id(req_data.knowledge_id)
        if not login_user.access_check(knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE):
            raise UnAuthorizedError.http_exception()

        cache_key = cls.get_preview_cache_key(req_data.knowledge_id, req_data.file_path)
        chunk_info = cls.get_preview_cache(cache_key, req_data.chunk_index)
        if not chunk_info:
            raise NotFoundError.http_exception()
        chunk_info['text'] = req_data.text
        chunk_info['metadata']['bbox'] = req_data.bbox
        cls.save_preview_cache(cache_key, chunk_index=req_data.chunk_index, value=chunk_info)

    @classmethod
    def delete_preview_file_chunk(cls, request: Request, login_user: UserPayload, req_data: UpdatePreviewFileChunk):
        knowledge = KnowledgeDao.query_by_id(req_data.knowledge_id)
        if not login_user.access_check(knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE):
            raise UnAuthorizedError.http_exception()

        cache_key = cls.get_preview_cache_key(req_data.knowledge_id, req_data.file_path)
        cls.delete_preview_cache(cache_key, chunk_index=req_data.chunk_index)

    @classmethod
    def save_knowledge_file(cls, login_user: UserPayload, req_data: KnowledgeFileProcess):
        """ 处理上传的文件, 只上传到minio和mysql """
        knowledge = KnowledgeDao.query_by_id(req_data.knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()
        if not login_user.access_check(knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE):
            raise UnAuthorizedError.http_exception()
        failed_files = []
        # 处理每个文件
        process_files = []
        preview_cache_keys = []
        for one in req_data.file_list:
            # 上传源文件，创建数据记录
            db_file = cls.process_one_file(login_user, knowledge, one)
            # 不重复的文件数据使用异步任务去执行
            if db_file.status != KnowledgeFileStatus.FAILED.value:
                # 获取此文件的预览缓存key
                cache_key = cls.get_preview_cache_key(req_data.knowledge_id, one.file_path)
                preview_cache_keys.append(cache_key)
                process_files.append(db_file)
            else:
                failed_file_info = db_file.model_dump()
                failed_file_info["file_path"] = one.file_path
                failed_files.append(failed_file_info)
        return knowledge, failed_files, process_files, preview_cache_keys

    @classmethod
    def process_knowledge_file(cls, request: Request, login_user: UserPayload, background_tasks: BackgroundTasks,
                               req_data: KnowledgeFileProcess) -> List[KnowledgeFile]:
        """ 处理上传的文件 """
        knowledge, failed_files, process_files, preview_cache_keys = cls.save_knowledge_file(login_user,
                                                                                             req_data)

        # 异步处理文件解析和入库, 如果通过cache_key可以获取到数据，则使用cache中的数据来进行入库操作
        if process_files:
            background_tasks.add_task(process_file_task,
                                      knowledge=knowledge,
                                      db_files=process_files,
                                      separator=req_data.separator,
                                      separator_rule=req_data.separator_rule,
                                      chunk_size=req_data.chunk_size,
                                      chunk_overlap=req_data.chunk_overlap,
                                      callback_url=req_data.callback_url,
                                      extra_metadata=None,
                                      preview_cache_keys=preview_cache_keys)

        cls.upload_knowledge_file_hook(request, login_user, knowledge, process_files)
        return failed_files + process_files

    @classmethod
    def sync_process_knowledge_file(cls, request: Request, login_user: UserPayload, req_data: KnowledgeFileProcess) \
            -> List[KnowledgeFile]:
        """ 同步处理上传的文件 """
        knowledge, failed_files, process_files, preview_cache_keys = cls.save_knowledge_file(login_user,
                                                                                             req_data)

        if process_files:
            process_file_task(knowledge, process_files, req_data.separator, req_data.separator_rule,
                              req_data.chunk_size, req_data.chunk_overlap, req_data.callback_url,
                              req_data.extra, preview_cache_keys)

            process_files = KnowledgeFileDao.select_list([f.id for f in process_files])

        cls.upload_knowledge_file_hook(request, login_user, knowledge, process_files)
        return failed_files + process_files

    @classmethod
    def retry_files(cls, request: Request, login_user: UserPayload, background_tasks: BackgroundTasks, req_data: dict):
        db_file_retry = req_data.get('file_objs')
        if not db_file_retry:
            return []
        id2input = {file.get('id'): file for file in db_file_retry}
        file_ids = list(id2input.keys())
        db_files = KnowledgeFileDao.select_list(file_ids=file_ids)
        if not db_files:
            return []
        knowledge = KnowledgeDao.query_by_id(db_files[0].knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()
        if not login_user.access_check(knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE):
            raise UnAuthorizedError.http_exception()
        res = []
        for file in db_files:
            # file exist
            input_file = id2input.get(file.id)
            if input_file["remark"] and '对应已存在文件' in input_file["remark"]:
                file.file_name = input_file["remark"].split(' 对应已存在文件 ')[0]
                file.remark = ''
            file.status = 1  # 解析中
            file = KnowledgeFileDao.update(file)
            res.append(file)
        background_tasks.add_task(retry_files, res, id2input)
        cls.upload_knowledge_file_hook(request, login_user, knowledge, res)
        return []

    @classmethod
    def upload_knowledge_file_hook(cls, request: Request, login_user: UserPayload, knowledge: Knowledge,
                                   file_list: List[KnowledgeFile]):
        logger.info(f'act=upload_knowledge_file_hook user={login_user.user_name} knowledge_id={knowledge.id}')
        if file_list:
            KnowledgeDao.update_knowledge_update_time(knowledge)
        # 记录审计日志
        file_name = ""
        for one in file_list:
            file_name += "\n\n" + one.file_name
        AuditLogService.upload_knowledge_file(login_user, get_request_ip(request), knowledge.id, file_name)

    @classmethod
    def process_one_file(cls, login_user: UserPayload, knowledge: Knowledge,
                         file_info: KnowledgeFileOne) -> KnowledgeFile:
        """ 处理上传的文件 """
        minio_client = MinioClient()
        # download original file
        filepath, file_name = file_download(file_info.file_path)
        md5_ = os.path.splitext(os.path.basename(filepath))[0].split('_')[0]

        # 是否包含重复文件
        content_repeat = KnowledgeFileDao.get_file_by_condition(md5_=md5_, knowledge_id=knowledge.id)
        name_repeat = KnowledgeFileDao.get_file_by_condition(file_name=file_name, knowledge_id=knowledge.id)
        if content_repeat or name_repeat:
            db_file = content_repeat[0] if content_repeat else name_repeat[0]
            old_name = db_file.file_name
            file_type = file_name.rsplit('.', 1)[-1]
            obj_name = f'tmp/{db_file.id}.{file_type}'
            db_file.object_name = obj_name
            db_file.remark = f'{file_name} 对应已存在文件 {old_name}'
            # 上传到minio，不修改数据库，由前端决定是否覆盖，覆盖的话调用重试接口
            with open(filepath, 'rb') as file:
                minio_client.upload_tmp(db_file.object_name, file.read())
            db_file.status = KnowledgeFileStatus.FAILED.value
            return db_file

        # 插入新的数据，把原始文件上传到minio
        db_file = KnowledgeFile(knowledge_id=knowledge.id,
                                file_name=file_name,
                                md5=md5_,
                                user_id=login_user.user_id)
        db_file = KnowledgeFileDao.add_file(db_file)
        # 原始文件保存
        file_type = db_file.file_name.rsplit('.', 1)[-1]
        db_file.object_name = f'original/{db_file.id}.{file_type}'
        res = minio_client.upload_minio(db_file.object_name, filepath)
        logger.info('upload_original_file path={} res={}', db_file.object_name, res)
        KnowledgeFileDao.update(db_file)
        return db_file

    @classmethod
    def get_knowledge_files(cls, request: Request, login_user: UserPayload, knowledge_id: int, file_name: str = None,
                            status: int = None, page: int = 1, page_size: int = 10) -> (List[KnowledgeFile], int, bool):
        db_knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not db_knowledge:
            raise NotFoundError.http_exception()

        if not login_user.access_check(db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE):
            raise UnAuthorizedError.http_exception()

        res = KnowledgeFileDao.get_file_by_filters(knowledge_id, file_name, status, page, page_size)
        total = KnowledgeFileDao.count_file_by_filters(knowledge_id, file_name, status)

        return res, total, login_user.access_check(db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE_WRITE)

    @classmethod
    def delete_knowledge_file(cls, request: Request, login_user: UserPayload, file_ids: List[int]):
        knowledge_file = KnowledgeFileDao.select_list(file_ids)
        if not knowledge_file:
            raise NotFoundError.http_exception()
        db_knowledge = KnowledgeDao.query_by_id(knowledge_file[0].knowledge_id)
        if not login_user.access_check(db_knowledge.user_id, str(db_knowledge.id), AccessType.KNOWLEDGE_WRITE):
            raise UnAuthorizedError.http_exception()

        # 处理vectordb
        delete_knowledge_file_vectors(file_ids)
        KnowledgeFileDao.delete_batch(file_ids)

        # 删除知识库文件的审计日志
        cls.delete_knowledge_file_hook(request, login_user, db_knowledge.id, knowledge_file)

        return True

    @classmethod
    def delete_knowledge_file_hook(cls, request: Request, login_user: UserPayload, knowledge_id: int,
                                   file_list: List[KnowledgeFile]):
        logger.info(f'act=delete_knowledge_file_hook user={login_user.user_name} knowledge_id={knowledge_id}')
        # 记录审计日志
        # 记录审计日志
        file_name = ""
        for one in file_list:
            file_name += "\n\n" + one.file_name
        AuditLogService.delete_knowledge_file(login_user, get_request_ip(request), knowledge_id, file_name)

    @classmethod
    def get_knowledge_chunks(cls, request: Request, login_user: UserPayload, knowledge_id: int,
                             file_ids: List[int] = None, keyword: str = None, page: int = None,
                             limit: int = None) -> (List[FileChunk], int):
        db_knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not db_knowledge:
            raise NotFoundError.http_exception()

        if not login_user.access_check(db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE):
            raise UnAuthorizedError.http_exception()

        index_name = db_knowledge.index_name if db_knowledge.index_name else db_knowledge.collection_name
        embeddings = FakeEmbedding()
        es_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

        search_data = {
            "from": (page - 1) * limit,
            "size": limit,
            "sort": [
                {"metadata.file_id": {"order": "desc", "missing": 0, "unmapped_type": "long"}},
                {"metadata.chunk_index": {"order": "asc", "missing": 0, "unmapped_type": "long"}}
            ]
        }
        if file_ids:
            search_data["post_filter"] = {"terms": {"metadata.file_id": file_ids}}
        if keyword:
            search_data["query"] = {"match": {"text": keyword}}
        try:
            res = es_client.client.search(index=index_name, body=search_data)
        except Exception as e:
            logger.warning(f'act=get_knowledge_chunks error={str(e)}')
            raise KnowledgeChunkError.http_exception()

        # 查询下分块对应的文件信息
        file_ids = set()
        result = []
        for one in res["hits"]["hits"]:
            file_ids.add(one["_source"]["metadata"]["file_id"])
        file_map = {}
        if file_ids:
            file_list = KnowledgeFileDao.get_file_by_ids(list(file_ids))
            file_map = {one.id: one for one in file_list}
        for one in res["hits"]["hits"]:
            file_id = one["_source"]["metadata"]["file_id"]
            file_info = file_map.get(file_id, None)
            # 过滤文件名和总结的文档摘要内容
            result.append(FileChunk(text=one["_source"]["text"].split(KnowledgeUtils.chunk_split, 1)[-1],
                                    metadata=one["_source"]["metadata"],
                                    parse_type=file_info.parse_type if file_info else None))
        return result, res['hits']['total']['value']

    @classmethod
    def update_knowledge_chunk(cls, request: Request, login_user: UserPayload, knowledge_id: int, file_id: int,
                               chunk_index: int, text: str, bbox: str):
        db_knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not db_knowledge:
            raise NotFoundError.http_exception()

        if not login_user.access_check(db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE):
            raise UnAuthorizedError.http_exception()

        index_name = db_knowledge.index_name if db_knowledge.index_name else db_knowledge.collection_name

        embeddings = decide_embeddings(db_knowledge.model)

        logger.info(f'act=update_vector knowledge_id={knowledge_id} file_id={file_id} chunk_index={chunk_index}')
        vector_client = decide_vectorstores(db_knowledge.collection_name, 'Milvus', embeddings)
        # search metadata
        output_fields = ['pk']
        output_fields.extend(list(FileChunkMetadata.__fields__.keys()))
        res = vector_client.col.query(expr=f'file_id == {file_id} && chunk_index == {chunk_index}',
                                      output_fields=output_fields, timeout=10)
        metadata = []
        pk = []
        for one in res:
            pk.append(one.pop('pk'))
            one['knowledge_id'] = str(knowledge_id)
            metadata.append(one)
        # insert data
        if metadata:
            logger.info(f'act=add_vector')
            new_metadata = metadata[0]
            new_metadata['bbox'] = bbox
            text = f"{new_metadata['source']}\n{new_metadata['title']}{KnowledgeUtils.chunk_split}{text}"
            res = vector_client.add_texts([text], [new_metadata], timeout=10)
        # delete data
        logger.info(f'act=delete_vector pk={pk}')
        res = vector_client.col.delete(f"pk in {pk}", timeout=10)
        logger.info(f'act=update_vector_over {res}')

        logger.info(f'act=update_es knowledge_id={knowledge_id} file_id={file_id} chunk_index={chunk_index}')
        es_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)
        res = es_client.client.update_by_query(index=index_name, body={
            "query": {"bool": {
                "must": {
                    "match": {
                        "metadata.file_id": file_id
                    }
                },
                "filter": {
                    "match": {
                        "metadata.chunk_index": chunk_index
                    }
                }
            }},
            "script": {
                "source": "ctx._source.text=params.text;ctx._source.metadata.bbox=params.bbox;",
                "params": {"text": text, "bbox": bbox}
            }
        })
        logger.info(f'act=update_es_over {res}')
        return True

    @classmethod
    def delete_knowledge_chunk(cls, request: Request, login_user: UserPayload, knowledge_id: int, file_id: int,
                               chunk_index: int):
        db_knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not db_knowledge:
            raise NotFoundError.http_exception()

        if not login_user.access_check(db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE):
            raise UnAuthorizedError.http_exception()

        index_name = db_knowledge.index_name if db_knowledge.index_name else db_knowledge.collection_name
        embeddings = FakeEmbedding()

        logger.info(f'act=delete_vector knowledge_id={knowledge_id} file_id={file_id} chunk_index={chunk_index}')
        vector_client = decide_vectorstores(db_knowledge.collection_name, 'Milvus', embeddings)
        pk = vector_client.col.query(expr=f'file_id == {file_id} && chunk_index == {chunk_index}',
                                     output_fields=['pk'],
                                     timeout=10)
        res = vector_client.col.delete(f"pk in {[p['pk'] for p in pk]}", timeout=10)
        logger.info(f'act=delete_vector_over {res}')

        logger.info(f'act=delete_es knowledge_id={knowledge_id} file_id={file_id} chunk_index={chunk_index} res={res}')
        es_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)
        res = es_client.client.delete_by_query(
            index=index_name, query={
                "bool": {
                    "must": {
                        "match": {
                            "metadata.file_id": file_id
                        }
                    },
                    "filter": {
                        "match": {
                            "metadata.chunk_index": chunk_index
                        }
                    }
                }
            })
        logger.info(f'act=delete_es_over {res}')

        return True

    @classmethod
    def get_file_share_url(cls, request: Request, login_user: UserPayload, file_id: int) -> str:
        minio_client = MinioClient()
        download_url = minio_client.get_share_link(str(file_id))
        return download_url

    @classmethod
    def get_file_bbox(cls, request: Request, login_user: UserPayload, file_id: int) -> Any:
        file_info = KnowledgeFileDao.select_list([file_id])
        file_info = file_info[0]
        if not file_info.bbox_object_name:
            return None

        # download bbox file
        minio_client = MinioClient()
        resp = minio_client.download_minio(file_info.bbox_object_name)
        new_data = io.BytesIO()
        for d in resp.stream(32 * 1024):
            new_data.write(d)
        resp.close()
        resp.release_conn()
        new_data.seek(0)
        return json.loads(new_data.read().decode('utf-8'))
