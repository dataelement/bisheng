from datetime import datetime
from enum import Enum
from typing import Any, List, Optional, Tuple, Union, Dict

from pydantic import BaseModel, field_validator
from sqlalchemy import Boolean, Integer, String, collate
from sqlmodel import Column, DateTime, Field, case, delete, func, or_, select, text, update
from sqlmodel.sql.expression import Select, SelectOfScalar, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.core.database.dialect_helpers import JsonType, UPDATE_TIME_SERVER_DEFAULT, name_sort_clauses
from bisheng.core.database.manager import get_database_connection
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao
from bisheng.user.domain.models.user import UserDao

class KnowledgeTypeEnum(Enum):
    QA = 1  # QAThe knowledge base upon
    NORMAL = 0  # Docly Knowledge Base
    PRIVATE = 2  # Workbench Personal Knowledge Base
    SPACE = 3  # Knowledge Space

class AuthTypeEnum(str, Enum):
    PUBLIC = 'public'
    PRIVATE = 'private'
    APPROVAL = 'approval'

class KnowledgeState(Enum):
    UNPUBLISHED = 0
    PUBLISHED = 1  # Document Knowledge Base Success Status
    COPYING = 2
    REBUILDING = 3  # Status in Document Knowledge Base Reconstruction
    FAILED = 4  # Status of Documentation Knowledge Base Reconstruction Failure

class MetadataFieldType(str, Enum):
    """ Metadata field type"""
    STRING = "string"
    NUMBER = "number"
    TIME = "time"

    # Case-insensitive enumeration matching
    @classmethod
    def _missing_(cls, value: Any) -> Optional["MetadataFieldType"]:
        if isinstance(value, str):
            for member in cls:
                if member.value.lower() == value.lower():
                    return member
        return None

class KnowledgeBase(SQLModelSerializable):
    user_id: Optional[int] = Field(default=None, index=True)
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )
    name: str = Field(index=True, min_length=1, max_length=200,
                      description='Knowledge Base Name')
    type: int = Field(index=False, default=KnowledgeTypeEnum.NORMAL.value,
                      description='Knowledge Base Type, value from KnowledgeTypeEnum')
    description: Optional[str] = Field(default=None, index=True)
    model: Optional[str] = Field(default=None, index=False)
    collection_name: Optional[str] = Field(default=None, index=False)
    index_name: Optional[str] = Field(default=None, index=False)
    state: Optional[int] = Field(index=False, default=KnowledgeState.PUBLISHED.value,
                                 description='value from KnowledgeState')
    is_released: bool = Field(default=False, description='is released to knowledge space square')
    auth_type: AuthTypeEnum = Field(default=AuthTypeEnum.PUBLIC, description='Authentication Type')
    is_shared: bool = Field(
        default=False,
        sa_column=Column(
            Boolean, nullable=False, server_default=text('0'),
            comment='F017: Root resource shared to all children (mirrors FGA shared_with tuples)',
        ),
    )
    auto_tag_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text('0'), comment='是否启用自动标签'),
    )
    auto_tag_library_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True, comment='绑定的自动标签库ID'),
    )

    metadata_fields: Optional[List[Dict]] = Field(default=None, sa_column=Column(JsonType, nullable=True),
                                                  description="Metadata Field Configuration for Knowledge Base")
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))

    @field_validator('model', mode='before')
    @classmethod
    def convert_model(cls, v: Any) -> str:
        if isinstance(v, int):
            v = str(v)
        return v

class Knowledge(KnowledgeBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

class KnowledgeRead(KnowledgeBase):
    id: int
    user_name: Optional[str] = None
    copiable: Optional[bool] = None
    is_pinned: Optional[bool] = False
    permission_ids: Optional[List[str]] = None

class KnowledgeUpdate(BaseModel):
    knowledge_id: int
    name: Optional[str] = None
    description: Optional[str] = None

class KnowledgeCreate(BaseModel):
    user_id: Optional[int] = Field(default=None, index=True)
    name: str = Field(index=True, min_length=1, max_length=200,
                      description='Knowledge Base Name')
    type: int = Field(index=False, default=KnowledgeTypeEnum.NORMAL.value,
                      description='Knowledge Base Type, value from KnowledgeTypeEnum')
    description: Optional[str] = Field(default=None, index=True)
    model: Optional[str] = Field(default=None, index=False)
    collection_name: Optional[str] = Field(default=None, index=False)
    index_name: Optional[str] = Field(default=None, index=False)
    state: Optional[int] = Field(index=False, default=KnowledgeState.PUBLISHED.value,
                                 description='value from KnowledgeState')
    is_released: bool = Field(default=False, description='is released to knowledge space square')
    auth_type: AuthTypeEnum = Field(default=AuthTypeEnum.PUBLIC, description='Authentication Type')
    is_shared: bool = Field(default=False)
    auto_tag_enabled: bool = Field(default=False)
    auto_tag_library_id: Optional[int] = None
    metadata_fields: Optional[List[Dict]] = Field(default=None,
                                                  description="Metadata Field Configuration for Knowledge Base")
    is_partition: Optional[bool] = None

    @field_validator('model', mode='before')
    @classmethod
    def convert_model(cls, v: Any) -> str:
        if isinstance(v, int):
            v = str(v)
        return v

class KnowledgeDao(KnowledgeBase):

    @classmethod
    def insert_one(cls, data: Knowledge) -> Knowledge:
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    async def async_insert_one(cls, data: Knowledge) -> Knowledge:
        async with get_async_db_session() as session:
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    def update_one(cls, data: Knowledge) -> Knowledge:
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    async def aupdate_one(cls, data: Knowledge) -> Knowledge:
        async with get_async_db_session() as session:
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    async def async_update_state(cls, knowledge_id: int, state: KnowledgeState, update_time: Optional[datetime] = None):
        async with get_async_db_session() as session:
            statement = update(Knowledge).where(col(Knowledge.id) == knowledge_id)
            statement = statement.values(state=state.value,
                                         update_time=update_time or datetime.now())
            await session.exec(statement)
            await session.commit()

    @classmethod
    def update_state(cls, knowledge_id: int, state: KnowledgeState, update_time: Optional[datetime] = None):
        with get_sync_db_session() as session:
            statement = update(Knowledge).where(col(Knowledge.id) == knowledge_id)
            statement = statement.values(state=state.value,
                                         update_time=update_time or datetime.now())
            session.exec(statement)
            session.commit()

    @classmethod
    def update_knowledge_update_time(cls, knowledge: Knowledge):
        statement = update(Knowledge).where(Knowledge.id == knowledge.id).values(
            update_time=text('NOW()'))
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    async def async_update_knowledge_update_time_by_id(cls, knowledge_id: int):
        statement = update(Knowledge).where(col(Knowledge.id) == knowledge_id).values(
            update_time=text('NOW()'))
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.commit()

    @classmethod
    def query_by_id(cls, knowledge_id: int) -> Knowledge:
        with get_sync_db_session() as session:
            return session.get(Knowledge, knowledge_id)

    @classmethod
    async def aquery_by_id(cls, knowledge_id: int) -> Knowledge:
        async with get_async_db_session() as session:
            return await session.get(Knowledge, knowledge_id)

    @classmethod
    async def async_query_by_id(cls, knowledge_id: int) -> Knowledge:
        async with get_async_db_session() as session:
            result = await session.execute(select(Knowledge).where(Knowledge.id == knowledge_id))
            return result.scalars().first()

    @classmethod
    def get_list_by_ids(cls, ids: List[int]) -> List[Knowledge]:
        with get_sync_db_session() as session:
            return session.exec(select(Knowledge).where(Knowledge.id.in_(ids))).all()

    @classmethod
    async def aget_list_by_ids(cls, ids: List[int]) -> List[Knowledge]:
        async with get_async_db_session() as session:
            result = await session.exec(select(Knowledge).where(col(Knowledge.id).in_(ids)))
            return result.all()

    @classmethod
    async def aget_knowledge_ids_created_by(
        cls, user_id: int, knowledge_type: KnowledgeTypeEnum,
    ) -> List[int]:
        """当前用户在指定类型下创建的知识库主键，用于与 OpenFGA can_read 列表取并集。"""
        async with get_async_db_session() as session:
            stmt = select(Knowledge.id).where(
                Knowledge.user_id == user_id,
                Knowledge.type == knowledge_type.value,
            )
            result = await session.exec(stmt)
            rows = result.all()
        out: List[int] = []
        for row in rows:
            if row is None:
                continue
            rid = row[0] if isinstance(row, tuple) else row
            out.append(int(rid))
        return out

    @classmethod
    def _user_knowledge_filters(
            cls,
            statement: Any,
            user_id: int,
            knowledge_id_extra: List[int] = None,
            knowledge_type: KnowledgeTypeEnum = None,
            name: str = None,
            page: int = 0,
            limit: int = 0,
            filter_knowledge: List[int] = None) -> Union[Select, SelectOfScalar]:
        if knowledge_id_extra:
            statement = statement.where(
                or_(Knowledge.id.in_(knowledge_id_extra), Knowledge.user_id == user_id))
        else:
            statement = statement.where(Knowledge.user_id == user_id)
        if filter_knowledge:
            statement = statement.where(Knowledge.id.in_(filter_knowledge))
        # 使用 is not None：避免 NORMAL=0 被当作「未传类型」而漏掉 type 条件
        if knowledge_type is not None:
            statement = statement.where(Knowledge.type == knowledge_type.value)
        if name:

            conditions = [col(Knowledge.name).like(f'%{name}%'), col(Knowledge.description).like(f'%{name}%')]

            file_knowledge_ids = KnowledgeFileDao.get_knowledge_ids_by_name(name)
            if file_knowledge_ids:
                conditions.append(Knowledge.id.in_(file_knowledge_ids))

            if conditions:
                statement = statement.where(or_(*conditions))

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
                           limit: int = 10,
                           filter_knowledge: List[int] = None) -> List[Knowledge]:
        statement = select(Knowledge)

        statement = cls._user_knowledge_filters(statement, user_id, knowledge_id_extra,
                                                knowledge_type, name, page, limit,
                                                filter_knowledge)

        statement = statement.order_by(Knowledge.update_time.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_user_knowledge(cls,
                                  user_id: int,
                                  knowledge_id_extra: List[int] = None,
                                  knowledge_type: KnowledgeTypeEnum = None,
                                  name: str = None,
                                  sort_by: str = "update_time",
                                  page: int = 0,
                                  limit: int = 10,
                                  filter_knowledge: List[int] = None,
                                  preferred_ids: Optional[List[int]] = None) -> List[Knowledge]:
        statement = select(Knowledge)

        statement = cls._user_knowledge_filters(statement, user_id, knowledge_id_extra,
                                                knowledge_type, name, page, limit,
                                                filter_knowledge)

        order_clauses = []
        if preferred_ids:
            # Float pinned ids to the top of the global sort so they land on page 1
            # no matter what sort_by is, then fall back to the requested sort.
            order_clauses.append(case((Knowledge.id.in_(preferred_ids), 0), else_=1))
        if sort_by == "create_time":
            order_clauses.append(Knowledge.create_time.desc())
        elif sort_by == "update_time":
            order_clauses.append(Knowledge.update_time.desc())
        elif sort_by == "name":
            db_conn = await get_database_connection()
            order_clauses.extend(name_sort_clauses(db_conn.async_engine.dialect.name))
        if order_clauses:
            statement = statement.order_by(*order_clauses)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    def count_user_knowledge(cls,
                             user_id: int,
                             knowledge_id_extra: List[int] = None,
                             knowledge_type: KnowledgeTypeEnum = None,
                             name: str = None) -> int:
        statement = select(func.count(Knowledge.id))
        statement = cls._user_knowledge_filters(statement, user_id, knowledge_id_extra,
                                                knowledge_type, name)
        with get_sync_db_session() as session:
            return session.scalar(statement)

    @classmethod
    async def acount_user_knowledge(cls,
                                    user_id: int,
                                    knowledge_id_extra: List[int] = None,
                                    knowledge_type: KnowledgeTypeEnum = None,
                                    name: str = None) -> int:
        statement = select(func.count(Knowledge.id))
        statement = cls._user_knowledge_filters(statement, user_id, knowledge_id_extra,
                                                knowledge_type, name)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    def count_by_filter(cls, filters: List[Any]) -> int:
        with get_sync_db_session() as session:
            return session.scalar(select(Knowledge.id).where(*filters))

    @classmethod
    def judge_knowledge_permission(cls, user_name: str,
                                   knowledge_ids: List[int]) -> List[Knowledge]:
        """Filter knowledge_ids to those the user can read.

        F008 follow-up: delegates to ReBAC via PermissionService instead of
        the legacy role_access table. Admin still gets the full set; owners
        and tenant-admin scope are picked up by list_accessible_ids' implicit
        scope expansion.
        """
        if not knowledge_ids:
            return []
        user_info = UserDao.get_user_by_username(user_name)
        if not user_info:
            return []

        from bisheng.permission.domain.services.owner_service import _run_async_safe
        from bisheng.permission.domain.services.permission_service import PermissionService
        from bisheng.user.domain.services.auth import LoginUser

        login_user = LoginUser.init_login_user_sync(
            user_id=user_info.user_id,
            user_name=user_name,
        )
        accessible_ids = _run_async_safe(
            PermissionService.list_accessible_ids(
                user_id=login_user.user_id,
                relation='can_read',
                object_type='knowledge_library',
                login_user=login_user,
            ),
        )
        if accessible_ids is None:
            return cls.get_list_by_ids(knowledge_ids)

        accessible_set = {int(x) for x in accessible_ids}
        filtered = [kid for kid in knowledge_ids if int(kid) in accessible_set]
        return cls.get_list_by_ids(filtered) if filtered else []

    @classmethod
    async def ajudge_knowledge_permission(cls, user_name: str,
                                          knowledge_ids: List[int]) -> List[Knowledge]:
        """Async variant of :meth:`judge_knowledge_permission`. Same semantics."""
        if not knowledge_ids:
            return []
        user_info = await UserDao.aget_user_by_username(user_name)
        if not user_info:
            return []

        from bisheng.permission.domain.services.permission_service import PermissionService
        from bisheng.user.domain.services.auth import LoginUser

        login_user = await LoginUser.init_login_user(
            user_id=user_info.user_id,
            user_name=user_name,
        )
        accessible_ids = await PermissionService.list_accessible_ids(
            user_id=login_user.user_id,
            relation='can_read',
            object_type='knowledge_library',
            login_user=login_user,
        )
        if accessible_ids is None:
            return await cls.aget_list_by_ids(knowledge_ids)

        accessible_set = {int(x) for x in accessible_ids}
        filtered = [kid for kid in knowledge_ids if int(kid) in accessible_set]
        return await cls.aget_list_by_ids(filtered) if filtered else []

    @classmethod
    def filter_knowledge_by_ids(cls,
                                knowledge_ids: List[int],
                                keyword: str = None,
                                page: int = 0,
                                limit: int = 0) -> (List[Knowledge], int):
        """
        Based on keywords and knowledge baseidFilter out the corresponding knowledge base

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
        with get_sync_db_session() as session:
            return session.exec(statement).all(), session.scalar(count_statement)

    @classmethod
    def generate_all_knowledge_filter(cls,
                                      statement,
                                      name: str = None,
                                      knowledge_type: KnowledgeTypeEnum = None):
        if knowledge_type is not None:
            statement = statement.where(Knowledge.type == knowledge_type.value)

        if name:
            conditions = [col(Knowledge.name).like(f'%{name}%'), col(Knowledge.description).like(f'%{name}%')]

            file_knowledge_ids = KnowledgeFileDao.get_knowledge_ids_by_name(name)
            if file_knowledge_ids:
                conditions.append(Knowledge.id.in_(file_knowledge_ids))

            if conditions:
                statement = statement.where(or_(*conditions))

        return statement

    @classmethod
    def get_all_knowledge(cls,
                          name: str = None,
                          knowledge_type: KnowledgeTypeEnum = None,
                          page: int = 0,
                          limit: int = 0) -> List[Knowledge]:
        statement = select(Knowledge)
        statement = cls.generate_all_knowledge_filter(statement,
                                                      name=name,
                                                      knowledge_type=knowledge_type)

        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(Knowledge.update_time.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_all_knowledge(cls,
                                 name: str = None,
                                 knowledge_type: KnowledgeTypeEnum = None,
                                 sort_by: str = "update_time",
                                 page: int = 0,
                                 limit: int = 0,
                                 preferred_ids: Optional[List[int]] = None) -> List[Knowledge]:
        statement = select(Knowledge)
        statement = cls.generate_all_knowledge_filter(statement,
                                                      name=name,
                                                      knowledge_type=knowledge_type)

        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        order_clauses = []
        if preferred_ids:
            order_clauses.append(case((Knowledge.id.in_(preferred_ids), 0), else_=1))
        if sort_by == "create_time":
            order_clauses.append(Knowledge.create_time.desc())
        elif sort_by == "update_time":
            order_clauses.append(Knowledge.update_time.desc())
        elif sort_by == "name":
            db_conn = await get_database_connection()
            order_clauses.extend(name_sort_clauses(db_conn.async_engine.dialect.name))
        if order_clauses:
            statement = statement.order_by(*order_clauses)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    def count_all_knowledge(cls,
                            name: str = None,
                            knowledge_type: KnowledgeTypeEnum = None) -> int:
        statement = select(func.count(Knowledge.id))
        statement = cls.generate_all_knowledge_filter(statement,
                                                      name=name,
                                                      knowledge_type=knowledge_type)
        with get_sync_db_session() as session:
            return session.scalar(statement)

    @classmethod
    async def acount_all_knowledge(cls,
                                   name: str = None,
                                   knowledge_type: KnowledgeTypeEnum = None) -> int:
        statement = select(func.count(Knowledge.id))
        statement = cls.generate_all_knowledge_filter(statement,
                                                      name=name,
                                                      knowledge_type=knowledge_type)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    def update_knowledge_list(cls, knowledge_list: List[Knowledge]):
        with get_sync_db_session() as session:
            for knowledge in knowledge_list:
                session.add(knowledge)
            session.commit()

    @classmethod
    def get_knowledge_by_name(cls, name: str, user_id: int = 0) -> Knowledge:
        """ Get Knowledge Base Details by Knowledge Base Name """
        statement = select(Knowledge).where(Knowledge.name == name)
        if user_id:
            statement = statement.where(Knowledge.user_id == user_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    def delete_knowledge(cls, knowledge_id: int, only_clear: bool = False):
        """
        Delete or empty the knowledge base
        """
        # <g id="Bold">Medical Treatment:</g>knowledge file
        with get_sync_db_session() as session:
            session.exec(delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id))
            # Do not delete knowledge base records when clearing the knowledge base
            if not only_clear:
                session.exec(delete(Knowledge).where(Knowledge.id == knowledge_id))
            session.commit()

    @classmethod
    async def async_delete_knowledge(cls, knowledge_id: int, only_clear: bool = False):
        async with get_async_db_session() as session:
            await session.exec(delete(KnowledgeFile).where(col(KnowledgeFile.knowledge_id) == knowledge_id))
            if not only_clear:
                await session.exec(delete(Knowledge).where(col(Knowledge.id) == knowledge_id))
            await session.commit()

    @classmethod
    def get_knowledge_by_time_range(cls, start_time: datetime, end_time: datetime, page: int = 0,
                                    page_size: int = 0) -> List[Knowledge]:
        """ Get a list of knowledge bases based on the creation timeframe """
        statement = select(Knowledge).where(
            Knowledge.create_time >= start_time,
            Knowledge.create_time < end_time
        )
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        statement = statement.order_by(col(Knowledge.id).asc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_first_knowledge(cls) -> Optional[Knowledge]:
        """ Get the first knowledge base """
        statement = select(Knowledge).order_by(col(Knowledge.id).asc()).limit(1)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    # ─── Knowledge Space specific ────────────────────────────────────────────

    @classmethod
    def _exclude_department_spaces(cls, statement):
        from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace

        return statement.where(
            ~col(Knowledge.id).in_(select(DepartmentKnowledgeSpace.space_id))
        )

    @classmethod
    def count_spaces_by_user(cls, user_id: int, exclude_department_spaces: bool = False) -> int:
        """ Count how many Knowledge Spaces a user has created """
        statement = select(func.count(Knowledge.id)).where(
            Knowledge.user_id == user_id,
            Knowledge.type == KnowledgeTypeEnum.SPACE.value
        )
        if exclude_department_spaces:
            statement = cls._exclude_department_spaces(statement)
        with get_sync_db_session() as session:
            return session.scalar(statement)

    @classmethod
    async def async_count_spaces_by_user(cls, user_id: int, exclude_department_spaces: bool = False) -> int:
        """ Async: Count how many Knowledge Spaces a user has created """
        statement = select(func.count(Knowledge.id)).where(
            Knowledge.user_id == user_id,
            Knowledge.type == KnowledgeTypeEnum.SPACE.value
        )
        if exclude_department_spaces:
            statement = cls._exclude_department_spaces(statement)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    def get_spaces_by_user(cls, user_id: int, order_by: str = 'update_time') -> List[Knowledge]:
        """ Get all Knowledge Spaces created by a user """
        statement = select(Knowledge).where(
            Knowledge.user_id == user_id,
            Knowledge.type == KnowledgeTypeEnum.SPACE.value
        )
        statement = cls._apply_space_order(statement, order_by)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def async_get_spaces_by_user(cls, user_id: int, order_by: str = 'update_time') -> List[Knowledge]:
        """ Async: Get all Knowledge Spaces created by a user """
        statement = select(Knowledge).where(
            Knowledge.user_id == user_id,
            Knowledge.type == KnowledgeTypeEnum.SPACE.value
        )
        statement = cls._apply_space_order(statement, order_by)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_spaces_by_ids(cls, space_ids: List[int], order_by: str = 'update_time') -> List[Knowledge]:
        """ Get Knowledge Spaces by a list of IDs """
        if not space_ids:
            return []
        statement = select(Knowledge).where(
            Knowledge.id.in_(space_ids),
            Knowledge.type == KnowledgeTypeEnum.SPACE.value
        )
        statement = cls._apply_space_order(statement, order_by)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def async_get_spaces_by_ids(cls, space_ids: List[int], order_by: str = 'update_time') -> List[Knowledge]:
        """ Async: Get Knowledge Spaces by a list of IDs """
        if not space_ids:
            return []
        statement = select(Knowledge).where(
            Knowledge.id.in_(space_ids),
            Knowledge.type == KnowledgeTypeEnum.SPACE.value
        )
        statement = cls._apply_space_order(statement, order_by)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_public_spaces(cls, order_by: str = 'update_time') -> List[Knowledge]:
        """ Get all PUBLIC and APPROVAL Knowledge Spaces (Knowledge Square) """
        statement = select(Knowledge).where(
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            Knowledge.auth_type.in_([AuthTypeEnum.PUBLIC.value, AuthTypeEnum.APPROVAL.value])
        )
        statement = cls._apply_space_order(statement, order_by)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def async_get_public_spaces(cls, keyword: str = None, order_by: str = 'update_time') -> List[Knowledge]:
        """ Async: Get all PUBLIC and APPROVAL Knowledge Spaces (Knowledge Square) """
        statement = select(Knowledge).where(
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            Knowledge.is_released.is_(True),
            Knowledge.auth_type.in_([AuthTypeEnum.PUBLIC.value, AuthTypeEnum.APPROVAL.value])
        )
        if keyword:
            statement = statement.where(or_(Knowledge.name.like(f"%{keyword}%"),
                                            Knowledge.description.like(f"%{keyword}%")))
        statement = cls._apply_space_order(statement, order_by)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def update_space(cls, space: Knowledge) -> Knowledge:
        """ Persist an updated Knowledge Space record """
        with get_sync_db_session() as session:
            session.add(space)
            session.commit()
            session.refresh(space)
            return space

    @classmethod
    async def async_update_space(cls, space: Knowledge) -> Knowledge:
        """ Async: Persist an updated Knowledge Space record """
        async with get_async_db_session() as session:
            session.add(space)
            await session.commit()
            await session.refresh(space)
            return space

    @classmethod
    async def async_get_public_spaces_paginated(
            cls,
            user_id: int,
            keyword: Optional[str] = None,
            page: int = 1,
            page_size: int = 20,
    ) -> List[Tuple[Any, ...]]:
        """
        Paginated query of released public/approval spaces for the Knowledge Square.
        Uses multi-table LEFT JOIN:
        - LEFT JOIN space_channel_member for current user's subscription status
        - LEFT JOIN subquery for subscriber count (status=ACTIVE)
        Returns list of tuples:
        (Knowledge, user_subscription_status, user_subscription_update_time, subscriber_count)
        """
        from bisheng.common.models.space_channel_member import (
            SpaceChannelMember, BusinessTypeEnum, MembershipStatusEnum, REJECTED_STATUS_DISPLAY_WINDOW,
        )

        rejection_cutoff = datetime.now() - REJECTED_STATUS_DISPLAY_WINDOW

        # Subquery: count subscribers (status=ACTIVE) per space
        subscriber_subq = (
            select(
                SpaceChannelMember.business_id,
                func.count().label('subscriber_count'),
            )
            .where(
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
            )
            .group_by(SpaceChannelMember.business_id)
            .subquery()
        )

        # Main query with LEFT JOINs
        query = (
            select(
                Knowledge,
                SpaceChannelMember.status.label('user_subscription_status'),
                SpaceChannelMember.update_time.label('user_subscription_update_time'),
                func.coalesce(subscriber_subq.c.subscriber_count, 0).label('subscriber_count'),
            )
            .outerjoin(
                SpaceChannelMember,
                (collate(col(Knowledge.id).cast(String), 'utf8mb4_unicode_ci') == SpaceChannelMember.business_id)
                & (SpaceChannelMember.business_type == BusinessTypeEnum.SPACE)
                & (SpaceChannelMember.user_id == user_id),
            )
            .outerjoin(
                subscriber_subq,
                collate(col(Knowledge.id).cast(String), 'utf8mb4_unicode_ci') == subscriber_subq.c.business_id,
            )
            .where(
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Knowledge.is_released.is_(True),
                Knowledge.auth_type.in_([AuthTypeEnum.PUBLIC.value, AuthTypeEnum.APPROVAL.value]),
            )
        )

        # Keyword filter
        if keyword:
            like_pattern = f'%{keyword}%'
            query = query.where(
                or_(
                    Knowledge.name.like(like_pattern),
                    Knowledge.description.like(like_pattern),
                )
            )

        # Sort: not-subscribed first, then by update_time DESC
        subscription_order = case(
            (SpaceChannelMember.status.is_(None), 0),
            (
                (SpaceChannelMember.status == MembershipStatusEnum.REJECTED)
                & (SpaceChannelMember.update_time < rejection_cutoff),
                0,
            ),
            else_=1,
        )
        query = query.order_by(
            subscription_order.asc(),
            func.coalesce(Knowledge.update_time, Knowledge.create_time).desc(),
        )

        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        async with get_async_db_session() as session:
            result = await session.exec(query)
            return list(result.all())

    @classmethod
    async def async_count_public_spaces(cls, keyword: Optional[str] = None) -> int:
        """Count total released public/approval spaces matching the keyword filter."""
        query = (
            select(func.count())
            .select_from(Knowledge)
            .where(
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Knowledge.is_released.is_(True),
                Knowledge.auth_type.in_([AuthTypeEnum.PUBLIC.value, AuthTypeEnum.APPROVAL.value]),
            )
        )

        if keyword:
            like_pattern = f'%{keyword}%'
            query = query.where(
                or_(
                    Knowledge.name.like(like_pattern),
                    Knowledge.description.like(like_pattern),
                )
            )

        async with get_async_db_session() as session:
            return await session.scalar(query) or 0

    @staticmethod
    def _apply_space_order(statement, order_by: str):
        if order_by == 'create_time':
            return statement.order_by(Knowledge.create_time.desc())
        elif order_by == 'name':
            return statement.order_by(Knowledge.name.asc())
        else:
            return statement.order_by(Knowledge.update_time.desc())
