# Path: src/backend/bisheng/database/models/flow.py

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from pydantic import field_validator
from sqlalchemy import Column, DateTime, String, and_, func, or_, text
from sqlmodel import JSON, Field, select, update

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.models.base import SQLModelSerializable
from bisheng.common.schemas.telemetry.event_data_schema import NewApplicationEventData
from bisheng.common.services import telemetry_service
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.core.logger import trace_id_var
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.role_access import AccessType, RoleAccess, RoleAccessDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.utils import generate_uuid


# if TYPE_CHECKING:


class FlowStatus(Enum):
    OFFLINE = 1
    ONLINE = 2


class FlowType(Enum):
    FLOW = 1
    ASSISTANT = 5
    WORKFLOW = 10
    WORKSTATION = 15
    LINSIGHT = 20  # Inspiration Mode


class AppEnum(Enum):
    Flow = 'flow'
    ASSISTANT = 'assistant'
    WORKFLOW = 'workflow'


class UserLinkType(Enum):
    app = AppEnum


class FlowBase(SQLModelSerializable):
    name: str = Field(index=True)
    user_id: Optional[int] = Field(default=None, index=True)
    description: Optional[str] = Field(default=None, sa_column=Column(String(length=1000)))
    data: Optional[Dict] = Field(default=None)
    logo: Optional[str] = Field(default=None, index=False)
    status: Optional[int] = Field(index=False, default=1)
    flow_type: Optional[int] = Field(index=False, default=1)
    guide_word: Optional[str] = Field(default=None, sa_column=Column(String(length=1000)))
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    @field_validator('data', mode='before')
    @classmethod
    def validate_json(cls, v):
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
    id: str = Field(default_factory=generate_uuid, primary_key=True, unique=True)
    data: Optional[Dict] = Field(default=None, sa_column=Column(JSON))


class FlowCreate(FlowBase):
    flow_id: Optional[str] = None


class FlowRead(FlowBase):
    id: str
    user_name: Optional[str] = None
    version_id: Optional[int] = None


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
    def create_flow(cls, flow_info: Flow, flow_type: Optional[int]) -> Flow:
        from bisheng.database.models.flow_version import FlowVersion
        with get_sync_db_session() as session:
            session.add(flow_info)
            # Create a default version
            flow_version = FlowVersion(name='v0',
                                       is_current=1,
                                       data=flow_info.data,
                                       flow_id=flow_info.id,
                                       create_time=datetime.now(),
                                       user_id=flow_info.user_id,
                                       flow_type=flow_type)
            session.add(flow_version)
            session.commit()
            session.refresh(flow_info)

            if flow_type == FlowType.FLOW.value:
                app_type = ApplicationTypeEnum.SKILL
            elif flow_type == FlowType.WORKFLOW.value:
                app_type = ApplicationTypeEnum.WORKFLOW
            elif flow_type == FlowType.ASSISTANT.value:
                app_type = ApplicationTypeEnum.ASSISTANT
            elif flow_type == FlowType.LINSIGHT.value:
                app_type = ApplicationTypeEnum.LINSIGHT
            else:
                app_type = ApplicationTypeEnum.DAILY_CHAT

            # RecordTelemetryJournal
            telemetry_service.log_event_sync(user_id=flow_info.user_id,
                                             event_type=BaseTelemetryTypeEnum.NEW_APPLICATION,
                                             trace_id=trace_id_var.get(),
                                             event_data=NewApplicationEventData(
                                                 app_id=flow_info.id,
                                                 app_name=flow_info.name,
                                                 app_type=app_type.value
                                             ))

            return flow_info

    @classmethod
    def delete_flow(cls, flow_info: Flow) -> Flow:
        from bisheng.database.models.flow_version import FlowVersion
        with get_sync_db_session() as session:
            session.delete(flow_info)
            # Delete the corresponding version information
            update_statement = update(FlowVersion).where(
                FlowVersion.flow_id == flow_info.id).values(is_delete=1)
            session.exec(update_statement)
            session.commit()
            return flow_info

    @classmethod
    def get_flow_by_id(cls, flow_id: str) -> Optional[Flow]:
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.id == flow_id)
            return session.exec(statement).first()

    @classmethod
    async def aget_flow_by_id(cls, flow_id: str) -> Optional[Flow]:
        async with get_async_db_session() as session:
            statement = select(Flow).where(Flow.id == flow_id)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_flow_by_idstr(cls, flow_id: str) -> Optional[Flow]:
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.id == flow_id)
            return session.exec(statement).first()

    @classmethod
    def get_flow_by_ids(cls, flow_ids: List[str]) -> List[Flow]:
        if not flow_ids:
            return []
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.id.in_(flow_ids))
            return session.exec(statement).all()

    @classmethod
    def get_flow_by_user(cls, user_id: int) -> List[Flow]:
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.user_id == user_id)
            return session.exec(statement).all()

    @classmethod
    def get_flow_by_name(cls, user_id: int, name: str) -> Optional[Flow]:
        with get_sync_db_session() as session:
            statement = select(Flow).where(Flow.user_id == user_id, Flow.name == name)
            return session.exec(statement).first()

    @classmethod
    def get_flow_list_by_name(cls, name: str) -> List[Flow]:
        with get_sync_db_session() as session:
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
        with get_sync_db_session() as session:
            return session.exec(statment).all()

    @classmethod
    def get_count_by_filters(cls, filters) -> int:
        with get_sync_db_session() as session:
            count_statement = session.query(func.count(Flow.id))
            return session.exec(count_statement.where(*filters)).scalar()

    @classmethod
    def get_flows(cls,
                  user_id: Optional[int],
                  extra_ids: Union[List[str], str],
                  name: str,
                  status: Optional[int] = None,
                  flow_ids: List[str] = None,
                  page: int = 0,
                  limit: int = 0,
                  flow_type: Optional[int] = None) -> List[Flow]:
        with get_sync_db_session() as session:
            # data The amount of data is too large, yesmysql Influential
            statement = select(Flow.id, Flow.user_id, Flow.name, Flow.status, Flow.create_time,
                               Flow.logo, Flow.update_time, Flow.description, Flow.guide_word,
                               Flow.flow_type)
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
                statement = statement.where(Flow.flow_type == flow_type)
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
                    flow_type: Optional[int] = None) -> int:
        with get_sync_db_session() as session:
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
                count_statement = count_statement.where(Flow.flow_type == flow_type)
            if flow_ids:
                count_statement = count_statement.filter(Flow.id.in_(flow_ids))
            if status is not None:
                count_statement = count_statement.filter(Flow.status == status)
            return count_statement.scalar()

    @classmethod
    def get_all_online_flows(cls,
                             keyword: str = None,
                             flow_ids: List[str] = None,
                             flow_type: int = FlowType.FLOW.value) -> List[Flow]:
        with get_sync_db_session() as session:
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
                                     flow_type: int = FlowType.FLOW.value) -> List[Flow]:
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
                                 limit=limit,
                                 flow_type=flow_type)

    @classmethod
    def filter_flows_by_ids(cls, flow_ids: List[str], keyword: str = None,
                            page: int = 0, limit: int = 0, flow_type: int = FlowType.FLOW.value) \
            -> (List[Flow], int):
        """
        Via SkillsIDFilter the list of skills by returning only brief information and not includingdata
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
        statement = statement.where(Flow.flow_type == flow_type)
        statement = statement.order_by(Flow.update_time.desc())
        with get_sync_db_session() as session:
            result = session.exec(statement).mappings().all()
            return [Flow.model_validate(f) for f in result], session.scalar(count_statement)

    @classmethod
    def update_flow(cls, flow: Flow) -> Flow:
        with get_sync_db_session() as session:
            session.add(flow)
            session.commit()
            session.refresh(flow)
        return flow

    @classmethod
    async def aupdate_flow(cls, flow: Flow) -> Flow:
        async with get_async_db_session() as session:
            session.add(flow)
            await session.commit()
            await session.refresh(flow)
        return flow

    @classmethod
    def get_all_apps(cls,
                     name: str = None,
                     status: int = None,
                     id_list: list = None,
                     flow_type: int = None,
                     user_id: int = None,
                     id_extra: list = None,
                     id_list_not_in: list = None,
                     page: int = 0,
                     limit: int = 0) -> (List[Dict], int):
        """ Get all apps Contains skills, assistants, workflows """
        sub_query = select(
            Flow.id, Flow.name, Flow.description, Flow.flow_type, Flow.logo, Flow.user_id,
            Flow.status, Flow.create_time, Flow.update_time).union_all(
            select(Assistant.id, Assistant.name, Assistant.desc, FlowType.ASSISTANT.value,
                   Assistant.logo, Assistant.user_id, Assistant.status, Assistant.create_time,
                   Assistant.update_time).where(Assistant.is_delete == 0)).subquery()

        statement = select(sub_query.c.id, sub_query.c.name, sub_query.c.description,
                           sub_query.c.flow_type, sub_query.c.logo, sub_query.c.user_id,
                           sub_query.c.status, sub_query.c.create_time, sub_query.c.update_time)
        count_statement = select(func.count(sub_query.c.id))
        if name:
            statement = statement.where(sub_query.c.name.like(f'%{name}%'))
            count_statement = count_statement.where(sub_query.c.name.like(f'%{name}%'))
        if status is not None:
            statement = statement.where(sub_query.c.status == status)
            count_statement = count_statement.where(sub_query.c.status == status)
        if id_list:
            statement = statement.where(sub_query.c.id.in_(id_list))
            count_statement = count_statement.where(sub_query.c.id.in_(id_list))
        if flow_type is not None:
            statement = statement.where(sub_query.c.flow_type == flow_type)
            count_statement = count_statement.where(sub_query.c.flow_type == flow_type)
        if user_id is not None:
            if id_extra:
                statement = statement.where(
                    or_(sub_query.c.user_id == user_id, sub_query.c.id.in_(id_extra)))
                count_statement = count_statement.where(
                    or_(sub_query.c.user_id == user_id, sub_query.c.id.in_(id_extra)))
            else:
                statement = statement.where(sub_query.c.user_id == user_id)
                count_statement = count_statement.where(sub_query.c.user_id == user_id)
        if id_list_not_in:
            statement = statement.where(~sub_query.c.id.in_(id_list_not_in))
            count_statement = count_statement.where(~sub_query.c.id.in_(id_list_not_in))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(sub_query.c.update_time.desc())
        with (get_sync_db_session() as session):
            ret = session.exec(statement).all()
            total = session.scalar(count_statement)
        data = []
        for one in ret:
            data.append({
                'id': one[0],
                'name': one[1],
                'description': one[2],
                'flow_type': one[3],
                'logo': one[4],
                'user_id': one[5],
                'status': one[6],
                'create_time': one[7],
                'update_time': one[8]
            })
        return data, total

    @classmethod
    async def get_one_flow_simple(cls, flow_id: str) -> Optional[Flow]:
        """ get simple info of one flow by id. not contain data field """
        statement = select(Flow.id, Flow.name, Flow.description, Flow.flow_type, Flow.logo, Flow.user_id,
                           Flow.status, Flow.create_time, Flow.update_time).where(Flow.id == flow_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            one = result.first()
            if not one:
                return None
            return Flow(**{
                'id': one[0],
                'name': one[1],
                'description': one[2],
                'flow_type': one[3],
                'logo': one[4],
                'user_id': one[5],
                'status': one[6],
                'create_time': one[7],
                'update_time': one[8]
            })

    @classmethod
    def get_one_flow_simple_sync(cls, flow_id: str) -> Optional[Flow]:
        """ get simple info of one flow by id. not contain data field """
        statement = select(Flow.id, Flow.name, Flow.description, Flow.flow_type, Flow.logo, Flow.user_id,
                           Flow.status, Flow.create_time, Flow.update_time).where(Flow.id == flow_id)
        with get_sync_db_session() as session:
            result = session.exec(statement)
            one = result.first()
            if not one:
                return None
            return Flow(**{
                'id': one[0],
                'name': one[1],
                'description': one[2],
                'flow_type': one[3],
                'logo': one[4],
                'user_id': one[5],
                'status': one[6],
                'create_time': one[7],
                'update_time': one[8]
            })

    @classmethod
    def get_all_app_by_time_range_sync(cls, start_time: datetime, end_time: datetime, page: int = 0,
                                       page_size: int = 0):
        sub_query = select(
            Flow.id, Flow.name, Flow.description, Flow.flow_type, Flow.logo, Flow.user_id,
            Flow.status, Flow.create_time, Flow.update_time).union_all(
            select(Assistant.id, Assistant.name, Assistant.desc, FlowType.ASSISTANT.value,
                   Assistant.logo, Assistant.user_id, Assistant.status, Assistant.create_time,
                   Assistant.update_time).where(Assistant.is_delete == 0)).subquery()

        statement = select(sub_query.c.id, sub_query.c.name, sub_query.c.description,
                           sub_query.c.flow_type, sub_query.c.logo, sub_query.c.user_id,
                           sub_query.c.status, sub_query.c.create_time, sub_query.c.update_time)
        statement = statement.where(and_(sub_query.c.create_time >= start_time,
                                         sub_query.c.create_time < end_time))
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        with get_sync_db_session() as session:
            result = session.exec(statement).all()
            data = []
            for one in result:
                data.append({
                    'id': one[0],
                    'name': one[1],
                    'description': one[2],
                    'flow_type': one[3],
                    'logo': one[4],
                    'user_id': one[5],
                    'status': one[6],
                    'create_time': one[7],
                    'update_time': one[8]
                })
            return data

    @classmethod
    def get_first_app(cls):
        sub_query = select(
            Flow.id, Flow.name, Flow.description, Flow.flow_type, Flow.logo, Flow.user_id,
            Flow.status, Flow.create_time, Flow.update_time).union_all(
            select(Assistant.id, Assistant.name, Assistant.desc, FlowType.ASSISTANT.value,
                   Assistant.logo, Assistant.user_id, Assistant.status, Assistant.create_time,
                   Assistant.update_time).where(Assistant.is_delete == 0)).subquery()

        statement = select(sub_query.c.id, sub_query.c.name, sub_query.c.description,
                           sub_query.c.flow_type, sub_query.c.logo, sub_query.c.user_id,
                           sub_query.c.status, sub_query.c.create_time, sub_query.c.update_time)
        statement = statement.order_by(sub_query.c.create_time.asc()).limit(1)
        with get_sync_db_session() as session:
            result = session.exec(statement).all()
            data = []
            for one in result:
                data.append({
                    'id': one[0],
                    'name': one[1],
                    'description': one[2],
                    'flow_type': one[3],
                    'logo': one[4],
                    'user_id': one[5],
                    'status': one[6],
                    'create_time': one[7],
                    'update_time': one[8]
                })
            return data[0] if data else None
