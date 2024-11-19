from datetime import datetime
from enum import Enum
from typing import Any, List, Optional, Union

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.knowledge_file import KnowledgeFile
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao
from langchain.pydantic_v1 import BaseModel
from sqlalchemy import Column, DateTime, delete, func, text, update
from sqlmodel import Field, or_, select
from sqlmodel.sql.expression import Select, SelectOfScalar


class KnowledgeTypeEnum(Enum):
    QA = 1
    NORMAL = 0


class KnowledgeBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True)
    name: str = Field(index=True, min_length=1, max_length=30, description='知识库名, 最少一个字符，最多30个字符')
    type: int = Field(index=False, default=0, description='0 为普通知识库，1 为QA知识库')
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


class KnowledgeUpdate(BaseModel):
    knowledge_id: int
    name: Optional[str]
    description: Optional[str]


class KnowledgeCreate(KnowledgeBase):
    is_partition: Optional[bool] = None


class KnowledgeDao(KnowledgeBase):

    @classmethod
    def insert_one(cls, data: Knowledge) -> Knowledge:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def update_one(cls, data: Knowledge) -> Knowledge:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def update_knowledge_update_time(cls, knowledge: Knowledge):
        statement = update(Knowledge).where(Knowledge.id == knowledge.id).values(
            update_time=text('NOW()'))
        with session_getter() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def query_by_id(cls, knowledge_id: int) -> Knowledge:
        with session_getter() as session:
            return session.get(Knowledge, knowledge_id)

    @classmethod
    def get_list_by_ids(cls, ids: List[int]) -> List[Knowledge]:
        with session_getter() as session:
            return session.exec(select(Knowledge).where(Knowledge.id.in_(ids))).all()

    @classmethod
    def _user_knowledge_filters(cls,
                                statement: Any,
                                user_id: int,
                                knowledge_id_extra: List[int] = None,
                                knowledge_type: KnowledgeTypeEnum = None,
                                name: str = None,
                                page: int = 0,
                                limit: int = 0) -> Union[Select, SelectOfScalar]:
        if knowledge_id_extra:
            statement = statement.where(
                or_(Knowledge.id.in_(knowledge_id_extra), Knowledge.user_id == user_id))
        else:
            statement = statement.where(Knowledge.user_id == user_id)
        if knowledge_type:
            statement = statement.where(Knowledge.type == knowledge_type.value)
        if name:
            statement = statement.where(Knowledge.name.like(f'%{name}%'))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        return statement

    @classmethod
    def get_user_knowledge(cls,
                           user_id: int,
                           knowledge_id_extra: List[int] = None,
                           knowledge_type: KnowledgeTypeEnum = None,
                           name: str = None,
                           page: int = 0,
                           limit: int = 10) -> List[Knowledge]:
        statement = select(Knowledge)

        statement = cls._user_knowledge_filters(statement, user_id, knowledge_id_extra,
                                                knowledge_type, name, page, limit)

        statement = statement.order_by(Knowledge.update_time.desc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def count_user_knowledge(cls,
                             user_id: int,
                             knowledge_id_extra: List[int] = None,
                             knowledge_type: KnowledgeTypeEnum = None,
                             name: str = None) -> int:
        statement = select(func.count(Knowledge.id))
        statement = cls._user_knowledge_filters(statement, user_id, knowledge_id_extra,
                                                knowledge_type, name)
        with session_getter() as session:
            return session.scalar(statement)

    @classmethod
    def count_by_filter(cls, filters: List[Any]) -> int:
        with session_getter() as session:
            return session.scalar(select(Knowledge.id).where(*filters))

    @classmethod
    def judge_knowledge_permission(cls, user_name: str,
                                   knowledge_ids: List[int]) -> List[Knowledge]:
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
        role_access_list = RoleAccessDao.find_role_access(role_id_list, knowledge_ids,
                                                          AccessType.KNOWLEDGE)
        if not role_access_list:
            return []
        statement = select(Knowledge).where(
            Knowledge.id.in_([access.third_id for access in role_access_list]))

        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def filter_knowledge_by_ids(cls,
                                knowledge_ids: List[int],
                                keyword: str = None,
                                page: int = 0,
                                limit: int = 0) -> (List[Knowledge], int):
        """
        根据关键字和知识库id过滤出对应的知识库

        """
        statement = select(Knowledge)
        count_statement = select(func.count(Knowledge.id))
        if knowledge_ids:
            statement = statement.where(Knowledge.id.in_(knowledge_ids))
            count_statement = count_statement.where(Knowledge.id.in_(knowledge_ids))
        if keyword:
            statement = statement.where(
                or_(Knowledge.name.like('%' + keyword + '%'),
                    Knowledge.description.like('%' + keyword + '%')))
            count_statement = count_statement.where(
                or_(Knowledge.name.like('%' + keyword + '%'),
                    Knowledge.description.like('%' + keyword + '%')))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(Knowledge.update_time.desc())
        with session_getter() as session:
            return session.exec(statement).all(), session.scalar(count_statement)

    @classmethod
    def get_all_knowledge(cls,
                          name: str = None,
                          knowledge_type: KnowledgeTypeEnum = None,
                          page: int = 0,
                          limit: int = 0) -> List[Knowledge]:
        statement = select(Knowledge)
        if knowledge_type:
            statement = statement.where(Knowledge.type == knowledge_type.value)
        if name:
            statement = statement.where(Knowledge.name.like(f'%{name}%'))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(Knowledge.update_time.desc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def count_all_knowledge(cls,
                            name: str = None,
                            knowledge_type: KnowledgeTypeEnum = None) -> int:
        statement = select(func.count(Knowledge.id))
        if knowledge_type:
            statement = statement.where(Knowledge.type == knowledge_type.value)
        if name:
            statement = statement.where(Knowledge.name.like(f'%{name}%'))
        with session_getter() as session:
            return session.scalar(statement)

    @classmethod
    def update_knowledge_list(cls, knowledge_list: List[Knowledge]):
        with session_getter() as session:
            for knowledge in knowledge_list:
                session.add(knowledge)
            session.commit()

    @classmethod
    def get_knowledge_by_name(cls, name: str, user_id: int = 0) -> Knowledge:
        """ 通过知识库名称获取知识库详情 """
        statement = select(Knowledge).where(Knowledge.name == name)
        if user_id:
            statement = statement.where(Knowledge.user_id == user_id)
        with session_getter() as session:
            return session.exec(statement).first()

    @classmethod
    def delete_knowledge(cls, knowledge_id: int, only_clear: bool = False):
        """
        删除或者清空知识库
        """
        # 处理knowledge file
        with session_getter() as session:
            session.exec(delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id))
            # 清空知识库时，不删除知识库记录
            if not only_clear:
                session.exec(delete(Knowledge).where(Knowledge.id == knowledge_id))
            session.commit()
