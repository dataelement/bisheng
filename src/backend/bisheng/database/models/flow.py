# Path: src/backend/bisheng/database/models/flow.py

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role_access import AccessType, RoleAccess, RoleAccessDao
from bisheng.database.models.user_role import UserRoleDao
# if TYPE_CHECKING:
from pydantic import validator
from sqlalchemy import Column, DateTime, String, and_, func, or_, text
from sqlmodel import JSON, Field, select


class FlowStatus(Enum):
    OFFLINE = 1
    ONLINE = 2


class FlowBase(SQLModelSerializable):
    name: str = Field(index=True)
    user_id: Optional[int] = Field(index=True)
    description: Optional[str] = Field(index=False)
    data: Optional[Dict] = Field(default=None)
    logo: Optional[str] = Field(index=False)
    status: Optional[int] = Field(index=False, default=1)
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))
    create_time: Optional[datetime] = Field(default=(datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                                            index=True)
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


class FlowReadWithStyle(FlowRead):
    # style: Optional['FlowStyleRead'] = None
    total: Optional[int] = None


class FlowUpdate(SQLModelSerializable):
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[Dict] = None
    status: Optional[int] = None
    guide_word: Optional[str] = None


class FlowDao(FlowBase):

    @classmethod
    def get_flow_by_id(cls, flow_id: str) -> Optional[Flow]:
        with session_getter() as session:
            statement = select(Flow).where(Flow.id == UUID(flow_id))
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
    def get_flows(cls, user_id: Optional[int], extra_ids: List[str], name: str, status: int) -> List[Flow]:
        with session_getter() as session:
            statement = select(Flow).where(Flow.status == status)
            if extra_ids:
                statement = statement.where(or_(Flow.id.in_(extra_ids), Flow.user_id == user_id))
            else:
                statement = statement.where(Flow.user_id == user_id)
            if name:
                statement = statement.where(Flow.name.like(f'%{name}%'))
            statement = statement.order_by(Flow.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    def get_all_online_flows(cls):
        with session_getter() as session:
            statement = select(Flow).where(Flow.status == FlowStatus.ONLINE.value)
            return session.exec(statement).all()

    @classmethod
    def get_user_access_online_flows(cls, user_id: int) -> List[Flow]:
        user_role = UserRoleDao.get_user_roles(user_id)
        flow_id_extra = []
        if user_role:
            role_ids = [role.id for role in user_role]
            role_access = RoleAccessDao.get_role_access(role_ids, AccessType.FLOW)
            if role_access:
                flow_id_extra = [access.third_id for access in role_access]
        return FlowDao.get_flows(user_id, flow_id_extra, '', FlowStatus.ONLINE.value)
