import time
from uuid import uuid4

from fastapi import Request

from bisheng.api.errcode.base import NotFoundError, UnAuthorizedError
from bisheng.api.errcode.knowledge import KnowledgeExistError
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import get_request_ip
from bisheng.database.models.group_resource import GroupResource, GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeDao, Knowledge, KnowledgeUpdate
from bisheng.database.models.role_access import AccessType
from bisheng.database.models.user_group import UserGroupDao
from bisheng.settings import settings


class KnowledgeService:

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




