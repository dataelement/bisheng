# Path: src/backend/bisheng/database/models/flow.py

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role_access import AccessType, RoleAccess, RoleAccessDao
from bisheng.database.models.user_role import UserRoleDao
# if TYPE_CHECKING:
from pydantic import validator
from sqlalchemy import Column, DateTime, String, and_, func, or_, text
from sqlmodel import JSON, Field, select, update


class FlowStatus(Enum):
    OFFLINE = 1
    ONLINE = 2

class FlowType(Enum):
    FLOW= 1
    ASSISTANT= 5
    WORKFLOW= 10

class FlowBase(SQLModelSerializable):
    name: str = Field(index=True)
    user_id: Optional[int] = Field(index=True)
    description: Optional[str] = Field(index=False)
    data: Optional[Dict] = Field(default=None)
    logo: Optional[str] = Field(index=False)
    status: Optional[int] = Field(index=False, default=1)
    flow_type: Optional[int] = Field(index=False, default=1)
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    guide_word: Optional[str] = Field(sa_column=Column(String(length=1000)))

    @validator('data')
    def validate_json(v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if not isinstance(v, dict):
            raise ValueError('Flow must be a valid JSON')

        # data must contain nodes and edges
        if 'nodes' not in v.keys():
            raise ValueError('Flow must have nodes')
        if 'edges' not in v.keys():
            raise ValueError('Flow must have edges')

        return v


class Flow(FlowBase, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)
    data: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
    # style: Optional['FlowStyle'] = Relationship(
    #     back_populates='flow',
    #     # use "uselist=False" to make it a one-to-one relationship
    #     sa_relationship_kwargs={'uselist': False},
    # )


class FlowCreate(FlowBase):
    flow_id: Optional[UUID]


class FlowRead(FlowBase):
    id: UUID
    user_name: Optional[str]
    version_id: Optional[int]


class FlowReadWithStyle(FlowRead):
    # style: Optional['FlowStyleRead'] = None
    total: Optional[int] = None


class FlowUpdate(SQLModelSerializable):
    name: Optional[str] = None
    logo: Optional[str] = None
    description: Optional[str] = None
    data: Optional[Dict] = None
    status: Optional[int] = None
    guide_word: Optional[str] = None


class FlowDao(FlowBase):

    @classmethod
    def create_flow(cls, flow_info: Flow,flow_type: Optional[int]) -> Flow:
        from bisheng.database.models.flow_version import FlowVersion
        with session_getter() as session:
            session.add(flow_info)
            # 创建一个默认的版本
            flow_version = FlowVersion(name='v0',
                                       is_current=1,
                                       data=flow_info.data,
                                       flow_id=flow_info.id.hex,
                                       create_time=datetime.now(),
                                       user_id=flow_info.user_id,
                                       flow_type=flow_type)
            session.add(flow_version)
            session.commit()
            session.refresh(flow_info)
            return flow_info

    @classmethod
    def delete_flow(cls, flow_info: Flow) -> Flow:
        from bisheng.database.models.flow_version import FlowVersion
        with session_getter() as session:
            session.delete(flow_info)
            # 删除对应的版本信息
            update_statement = update(FlowVersion).where(
                FlowVersion.flow_id == flow_info.id.hex).values(is_delete=1)
            session.exec(update_statement)
            session.commit()
            return flow_info

    @classmethod
    def get_flow_by_id(cls, flow_id: str) -> Optional[Flow]:
        with session_getter() as session:
            statement = select(Flow).where(Flow.id == UUID(flow_id))
            return session.exec(statement).first()

    @classmethod
    def get_flow_by_idstr(cls, flow_id: str) -> Optional[Flow]:
        with session_getter() as session:
            statement = select(Flow).where(Flow.id == flow_id)
            return session.exec(statement).first()

    @classmethod
    def get_flow_by_ids(cls, flow_ids: List[str]) -> List[Flow]:
        if not flow_ids:
            return []
        with session_getter() as session:
            statement = select(Flow).where(Flow.id.in_(flow_ids))
            return session.exec(statement).all()

    @classmethod
    def get_flow_by_user(cls, user_id: int) -> List[Flow]:
        with session_getter() as session:
            statement = select(Flow).where(Flow.user_id == user_id)
            return session.exec(statement).all()

    @classmethod
    def get_flow_by_name(cls, user_id: int, name: str) -> Optional[Flow]:
        with session_getter() as session:
            statement = select(Flow).where(Flow.user_id == user_id, Flow.name == name)
            return session.exec(statement).first()

    @classmethod
    def get_flow_list_by_name(cls, name: str) -> List[Flow]:
        with session_getter() as session:
            statement = select(Flow).where(Flow.name.like('%{}%'.format(name)))
            return session.exec(statement).all()

    @classmethod
    def get_flow_by_access(cls, role_id: int, name: str, page_size: int,
                           page_num: int) -> List[Tuple[Flow, RoleAccess]]:
        statment = select(Flow, RoleAccess).join(RoleAccess,
                                                 and_(RoleAccess.role_id == role_id,
                                                      RoleAccess.type == AccessType.FLOW.value,
                                                      RoleAccess.third_id == Flow.id),
                                                 isouter=True)

        if name:
            statment = statment.where(Flow.name.like('%' + name + '%'))
        if page_num and page_size and page_num != 'undefined':
            page_num = int(page_num)
            statment = statment.order_by(RoleAccess.type.desc()).order_by(
                Flow.update_time.desc()).offset((page_num - 1) * page_size).limit(page_size)
        with session_getter() as session:
            return session.exec(statment).all()

    @classmethod
    def get_count_by_filters(cls, filters) -> int:
        with session_getter() as session:
            count_statement = session.query(func.count(Flow.id))
            return session.exec(count_statement.where(*filters)).scalar()

    @classmethod
    def get_flows(cls, user_id: Optional[int], extra_ids: Union[List[str], str], name: str,
                  status: Optional[int] = None, flow_ids: List[str] = None, page: int = 0, limit: int = 0,flow_type:Optional[int]= None) \
            -> List[Flow]:
        with session_getter() as session:
            # data 数据量太大，对mysql 有影响
            statement = select(Flow.id, Flow.user_id, Flow.name, Flow.status, Flow.create_time,
                               Flow.logo, Flow.update_time, Flow.description, Flow.guide_word,Flow.flow_type)
            if extra_ids and isinstance(extra_ids, List):
                statement = statement.where(or_(Flow.id.in_(extra_ids), Flow.user_id == user_id))
            elif not extra_ids:
                statement = statement.where(Flow.user_id == user_id)
            if name:
                statement = statement.where(
                    or_(Flow.name.like(f'%{name}%'), Flow.description.like(f'%{name}%')))
            if status is not None:
                statement = statement.where(Flow.status == status)
            if flow_type is not None:
                statement = statement.where(Flow.flow_type== flow_type)
            if flow_ids:
                statement = statement.where(Flow.id.in_(flow_ids))
            statement = statement.order_by(Flow.update_time.desc())
            if page > 0 and limit > 0:
                statement = statement.offset((page - 1) * limit).limit(limit)
            flows = session.exec(statement)
            flows_partial = flows.mappings().all()
            return [Flow.model_validate(f) for f in flows_partial]

    @classmethod
    def count_flows(cls,
                    user_id: Optional[int],
                    extra_ids: Union[List[str], str],
                    name: str,
                    status: Optional[int] = None,
                    flow_ids: List[str] = None,
                    flow_type:Optional[int]= None) -> int:
        with session_getter() as session:
            count_statement = session.query(func.count(Flow.id))
            if extra_ids and isinstance(extra_ids, List):
                count_statement = count_statement.filter(
                    or_(Flow.id.in_(extra_ids), Flow.user_id == user_id))
            elif not extra_ids:
                count_statement = count_statement.filter(Flow.user_id == user_id)
            if name:
                count_statement = count_statement.filter(
                    or_(Flow.name.like(f'%{name}%'), Flow.description.like(f'%{name}%')))
            if flow_type is not None:
                count_statement= count_statement.where(Flow.flow_type== flow_type)
            if flow_ids:
                count_statement = count_statement.filter(Flow.id.in_(flow_ids))
            if status is not None:
                count_statement = count_statement.filter(Flow.status == status)
            return count_statement.scalar()

    @classmethod
    def get_all_online_flows(cls, keyword: str = None, flow_ids: List[str] = None,flow_type:int=FlowType.FLOW.value) -> List[Flow]:
        with session_getter() as session:
            statement = select(Flow.id, Flow.user_id, Flow.name, Flow.status, Flow.create_time,
                               Flow.logo, Flow.update_time, Flow.description,
                               Flow.guide_word).where(Flow.status == FlowStatus.ONLINE.value)
            if flow_ids:
                statement = statement.where(Flow.id.in_(flow_ids))
            if keyword:
                statement = statement.where(
                    or_(Flow.name.like(f'%{keyword}%'), Flow.description.like(f'%{keyword}%')))
            result = session.exec(statement).mappings().all()
            return [Flow.model_validate(f) for f in result]

    @classmethod
    def get_user_access_online_flows(cls,
                                     user_id: int,
                                     page: int = 0,
                                     limit: int = 0,
                                     keyword: str = None,
                                     flow_ids: List[str] = None,
                                     flow_type:int=FlowType.FLOW.value) -> List[Flow]:
        user_role = UserRoleDao.get_user_roles(user_id)
        flow_id_extra = []
        if user_role:
            role_ids = [role.role_id for role in user_role]
            if 1 in role_ids:
                # admin
                flow_id_extra = 'admin'
            else:
                role_access = RoleAccessDao.get_role_access(role_ids, AccessType.FLOW)
                if role_access:
                    flow_id_extra = [access.third_id for access in role_access]
        return FlowDao.get_flows(user_id,
                                 flow_id_extra,
                                 keyword,
                                 FlowStatus.ONLINE.value,
                                 flow_ids=flow_ids,
                                 page=page,
                                 limit=limit,flow_type=flow_type)

    @classmethod
    def filter_flows_by_ids(cls, flow_ids: List[UUID], keyword: str = None, page: int = 0, limit: int = 0,flow_type:int=FlowType.FLOW.value) \
            -> (List[Flow], int):
        """
        通过技能ID过滤技能列表，只返回简略信息，不包含data
        """
        statement = select(Flow.id, Flow.user_id, Flow.name, Flow.status, Flow.create_time,
                           Flow.update_time, Flow.description, Flow.guide_word)
        count_statement = select(func.count(Flow.id))
        if flow_ids:
            statement = statement.where(Flow.id.in_(flow_ids))
            count_statement = count_statement.where(Flow.id.in_(flow_ids))
        if keyword:
            statement = statement.where(
                or_(Flow.name.like(f'%{keyword}%'), Flow.description.like(f'%{keyword}%')))
            count_statement = count_statement.where(
                or_(Flow.name.like(f'%{keyword}%'), Flow.description.like(f'%{keyword}%')))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.where(Flow.flow_type==flow_type)
        statement = statement.order_by(Flow.update_time.desc())
        with session_getter() as session:
            result = session.exec(statement).mappings().all()
            return [Flow.model_validate(f) for f in result], session.scalar(count_statement)
