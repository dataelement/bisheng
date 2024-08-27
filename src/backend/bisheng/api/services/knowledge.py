import math
import time
from typing import List
from uuid import uuid4

from fastapi import Request
from loguru import logger

from bisheng.api.errcode.base import NotFoundError, UnAuthorizedError
from bisheng.api.errcode.knowledge import KnowledgeExistError
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.knowledge_imp import decide_vectorstores
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import get_request_ip
from bisheng.database.models.group_resource import GroupResource, GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeDao, Knowledge, KnowledgeUpdate, KnowledgeRead
from bisheng.database.models.knowledge_file import KnowledgeFileDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.user_role import UserRoleDao
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.settings import settings
from bisheng.utils.minio_client import MinioClient


class KnowledgeService:

    @classmethod
    def get_knowledge(cls, request: Request, login_user: UserPayload, name: str = None, page: int = 1,
                      limit: int = 10) -> (List[KnowledgeRead], int):
        if not login_user.is_admin():
            knowledge_id_extra = []
            user_role = UserRoleDao.get_user_roles(login_user.user_id)
            if user_role:
                role_ids = [role.role_id for role in user_role]
                role_access = RoleAccessDao.get_role_access(role_ids, AccessType.KNOWLEDGE)
                if role_access:
                    knowledge_id_extra = [int(access.third_id) for access in role_access]
            res = KnowledgeDao.get_user_knowledge(login_user.user_id, knowledge_id_extra, name, page, limit)
            total = KnowledgeDao.count_user_knowledge(login_user.user_id, knowledge_id_extra, name)
        else:
            res = KnowledgeDao.get_all_knowledge(name, page, limit)
            total = KnowledgeDao.count_all_knowledge(name)

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
    def update_knowledge(cls, request: Request, login_user: UserPayload, knowledge: KnowledgeUpdate) -> Knowledge:
        db_knowledge = KnowledgeDao.query_by_id(knowledge.id)
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
        return db_knowledge

    @classmethod
    def delete_knowledge(cls, request: Request, login_user: UserPayload, knowledge_id: int, only_clear: bool = False):
        knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge:
            raise NotFoundError.http_exception()

        if not login_user.access_check(knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE_WRITE):
            raise UnAuthorizedError.http_exception()

        # 处理vector
        embeddings = FakeEmbedding()
        vector_client = decide_vectorstores(knowledge.collection_name, 'Milvus', embeddings)
        logger.info(f'delete_vector col={knowledge.collection_name}')
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

        # 清理minio的数据
        cls.delete_knowledge_file_in_minio(knowledge_id)

        # 删除mysql数据
        KnowledgeDao.delete_knowledge(knowledge_id, only_clear)

        cls.delete_knowledge_hook(request, login_user, knowledge)
        return True

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
