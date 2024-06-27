from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy import Column, DateTime, and_, text, func
from sqlmodel import Field, select, or_

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role_access import RoleAccess, AccessType, RoleAccessDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao


class KnowledgeBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True)
    name: str = Field(index=True)
    description: Optional[str] = Field(index=True)
    model: Optional[str] = Field(index=False)
    collection_name: Optional[str] = Field(index=False)
    index_name: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Knowledge(KnowledgeBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeRead(KnowledgeBase):
    id: int
    user_name: Optional[str]


class KnowledgeUpdate(KnowledgeBase):
    id: int
    name: str


class KnowledgeCreate(KnowledgeBase):
    is_partition: Optional[bool] = None


class KnowledgeDao(KnowledgeBase):
    from bisheng.database.models.role_access import RoleAccess

    @classmethod
    def query_by_id(cls, id: int) -> Knowledge:
        with session_getter() as session:
            return session.get(Knowledge, id)

    @classmethod
    def get_list_by_ids(cls, ids: List[int]):
        with session_getter() as session:
            return session.exec(select(Knowledge).where(Knowledge.id.in_(ids))).all()

    @classmethod
    def get_knowledge_by_access(role_id: int, name: str, page_size: int,
                                page_num: int) -> List[Tuple[Knowledge, RoleAccess]]:
        from bisheng.database.models.role_access import RoleAccess, AccessType
        statment = select(Knowledge,
                          RoleAccess).join(RoleAccess,
                                           and_(RoleAccess.role_id == role_id,
                                                RoleAccess.type == AccessType.KNOWLEDGE.value,
                                                RoleAccess.third_id == Knowledge.id),
                                           isouter=True)
        if name:
            statment = statment.where(Knowledge.name.like('%' + name + '%'))
        if page_num and page_size and page_num != 'undefined':
            page_num = int(page_num)
            statment = statment.order_by(RoleAccess.type.desc()).order_by(
                Knowledge.update_time.desc()).offset((page_num - 1) * page_size).limit(page_size)
        with session_getter() as session:
            return session.exec(statment).all()

    @classmethod
    def get_count_by_filter(cls, filters: List[Any]) -> int:
        with session_getter() as session:
            return session.scalar(select(Knowledge.id).where(*filters))

    @classmethod
    def judge_knowledge_permission(cls, user_name: str, knowledge_ids: List[int]) -> List[Knowledge]:
        """
        根据用户名和知识库ID列表，获取用户有权限查看的知识库列表
        :param user_name: 用户名
        :param knowledge_ids: 知识库ID列表
        :return: 返回用户有权限的知识库列表
        """
        # 获取用户信息
        user_info = UserDao.get_user_by_username(user_name)
        if not user_info:
            return []

        # 查询用户所属于的角色
        role_list = UserRoleDao.get_user_roles(user_info.user_id)
        if not role_list:
            return []

        role_id_list = []
        is_admin = False
        for role in role_list:
            role_id_list.append(role.role_id)
            if role.role_id == 1:
                is_admin = True
        # admin 用户拥有所有知识库权限
        if is_admin:
            return KnowledgeDao.get_list_by_ids(knowledge_ids)

        # 查询角色 有使用权限的知识库列表
        role_access_list = RoleAccessDao.find_role_access(role_id_list, knowledge_ids, AccessType.KNOWLEDGE)
        if not role_access_list:
            return []
        statement = select(Knowledge).where(Knowledge.id.in_([access.third_id for access in role_access_list]))

        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def filter_knowledge_by_ids(cls, knowledge_ids: List[int], keyword: str = None,
                                page: int = 0, limit: int = 0) -> (List[Knowledge], int):
        """
        根据关键字和知识库id过滤出对应的知识库

        """
        statement = select(Knowledge)
        count_statement = select(func.count(Knowledge.id))
        if knowledge_ids:
            statement = statement.where(Knowledge.id.in_(knowledge_ids))
            count_statement = count_statement.where(Knowledge.id.in_(knowledge_ids))
        if keyword:
            statement = statement.where(or_(
                Knowledge.name.like('%' + keyword + '%'),
                Knowledge.description.like('%' + keyword + '%')
            ))
            count_statement = count_statement.where(or_(
                Knowledge.name.like('%' + keyword + '%'),
                Knowledge.description.like('%' + keyword + '%')
            ))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(Knowledge.update_time.desc())
        with session_getter() as session:
            return session.exec(statement).all(), session.scalar(count_statement)
