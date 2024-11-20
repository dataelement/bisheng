# Path: src/backend/bisheng/database/models/flow.py

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import func

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
# if TYPE_CHECKING:
from pydantic import validator
from sqlmodel import JSON, Field, select, update, text, Column, DateTime

from bisheng.database.models.flow import Flow


class FlowVersionBase(SQLModelSerializable):
    id: Optional[int] = Field(default=None, primary_key=True, unique=True)
    flow_id: str = Field(index=True, max_length=32, description="所属的技能ID")
    name: str = Field(index=True, description="版本的名字")
    data: Optional[Dict] = Field(default=None, description="版本的数据")
    description: Optional[str] = Field(index=False, description="版本的描述")
    user_id: Optional[int] = Field(index=True, description="创建者")
    flow_type: Optional[int] = Field(default=1, description="版本的类型")
    is_current: Optional[int] = Field(default=0, description="是否为正在使用版本")
    is_delete: Optional[int] = Field(default=0, description="是否删除")
    original_version_id: Optional[int] = Field(default=None, description="来源版本的ID")
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

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


class FlowVersion(FlowVersionBase, table=True):
    data: Optional[Dict] = Field(default=None, sa_column=Column(JSON), description="版本的数据")


class FlowVersionRead(FlowVersionBase):
    pass


class FlowVersionDao(FlowVersion):

    @classmethod
    def create_version(cls, version: FlowVersion) -> FlowVersion:
        """
        创建新版本
        """
        with session_getter() as session:
            session.add(version)
            session.commit()
            session.refresh(version)
            return version

    @classmethod
    def update_version(cls, version: FlowVersion) -> FlowVersion:
        """
        更新版本信息，同时更新技能表里的data数据
        """
        with session_getter() as session:
            session.add(version)
            session.commit()
            # 如果是当前版本，则更新技能表里的数据
            if version.is_current == 1:
                # 更新技能表里的data数据
                update_flow = update(Flow).where(Flow.id == version.flow_id).values(data=version.data)
                session.exec(update_flow)
                session.commit()
            session.refresh(version)
            return version

    @classmethod
    def get_version_by_name(cls, flow_id: str, name: str) -> Optional[FlowVersion]:
        """
        根据技能ID和版本名字获取版本的信息
        """
        with session_getter() as session:
            statement = select(FlowVersion).where(FlowVersion.flow_id == flow_id,
                                                  FlowVersion.name == name,
                                                  FlowVersion.is_delete == 0)
            return session.exec(statement).first()

    @classmethod
    def get_version_by_id(cls, version_id: int, include_delete: bool = False) -> Optional[FlowVersion]:
        """
        根据版本ID获取技能版本的信息
        """
        with session_getter() as session:
            statement = select(FlowVersion).where(FlowVersion.id == version_id)
            if not include_delete:
                statement = statement.where(FlowVersion.is_delete == 0)
            return session.exec(statement).first()

    @classmethod
    def get_version_by_flow(cls, flow_id: str) -> Optional[FlowVersion]:
        """
        根据技能ID获取当前技能版本的信息
        """
        with session_getter() as session:
            statement = select(FlowVersion).where(FlowVersion.flow_id == flow_id,
                                                  FlowVersion.is_current == 1,
                                                  FlowVersion.is_delete == 0)
            return session.exec(statement).first()

    @classmethod
    def get_list_by_ids(cls, ids: List[int]) -> List[FlowVersion]:
        """
        根据ID列表获取所有版本详情
        """
        with session_getter() as session:
            statement = select(FlowVersion).where(FlowVersion.id.in_(ids))
            return session.exec(statement).all()

    @classmethod
    def get_list_by_flow(cls, flow_id: str) -> List[FlowVersionRead]:
        """
        根据技能ID 获取所有的技能版本
        """
        with session_getter() as session:
            statement = select(FlowVersion.id, FlowVersion.flow_id, FlowVersion.name, FlowVersion.description,
                               FlowVersion.is_current, FlowVersion.create_time, FlowVersion.update_time).where(
                FlowVersion.flow_id == flow_id, FlowVersion.is_delete == 0).order_by(FlowVersion.id.desc())
            ret = session.exec(statement).mappings().all()
            return [FlowVersionRead.model_validate(f) for f in ret]

    @classmethod
    def count_list_by_flow(cls, flow_id: str, include_delete: bool = False) -> int:
        """
        根据技能ID 技能版本的数量
        """
        with session_getter() as session:
            count_statement = session.query(func.count()).where(FlowVersion.flow_id == flow_id)
            if not include_delete:
                count_statement = count_statement.where(FlowVersion.is_delete == 0)
            return count_statement.scalar()

    @classmethod
    def get_list_by_flow_ids(cls, flow_ids: List[str]) -> List[FlowVersionRead]:
        """
        根据技能ID列表 获取所有的技能的所有版本信息
        """
        with session_getter() as session:
            statement = select(FlowVersion.id, FlowVersion.flow_id, FlowVersion.name, FlowVersion.description,
                               FlowVersion.is_current, FlowVersion.create_time, FlowVersion.update_time).where(
                FlowVersion.flow_id.in_(flow_ids), FlowVersion.is_delete == 0).order_by(FlowVersion.id.desc())
            ret = session.exec(statement).mappings().all()
            return [FlowVersionRead.model_validate(f) for f in ret]

    @classmethod
    def delete_flow_version(cls, version_id: int) -> None:
        """
        删除某个版本，正在使用的版本不能删除
        """
        with session_getter() as session:
            update_statement = update(FlowVersion).where(
                FlowVersion.id == version_id, FlowVersion.is_current == 0).values(is_delete=1)
            session.exec(update_statement)
            session.commit()

    @classmethod
    def change_current_version(cls, flow_id: str, new_version_info: FlowVersion) -> bool:
        """
        修改技能的当前版本, 判断当前版本是否存在
        同时修改技能表里的data数据
        """
        with session_getter() as session:
            # 设置当前版本
            set_statement = update(FlowVersion).where(
                FlowVersion.flow_id == flow_id,
                FlowVersion.id == new_version_info.id,
                FlowVersion.is_delete == 0,
            ).values(is_current=1)
            update_ret = session.exec(set_statement)
            if update_ret.rowcount == 0:
                # 未更新成功则不取消之前设置的当前版本
                return False

            # 更新技能表里的data数据
            update_flow = update(Flow).where(Flow.id == flow_id).values(data=new_version_info.data)
            session.exec(update_flow)
            session.commit()

            # 把其他版本修改为非当前版本
            statement = update(FlowVersion).where(
                FlowVersion.flow_id == flow_id,
                FlowVersion.id != new_version_info.id,
                FlowVersion.is_current == 1).values(
                is_current=0)
            session.exec(statement)
            session.commit()

            return True
