# Path: src/backend/bisheng/database/models/flow.py

from datetime import datetime
from typing import Dict, List, Optional

# if TYPE_CHECKING:
from pydantic import field_validator
from sqlalchemy import func, String
from sqlmodel import JSON, Field, select, update, text, Column, DateTime

from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.common.models.base import SQLModelSerializable
from bisheng.database.models.flow import Flow


class FlowVersionBase(SQLModelSerializable):
    id: Optional[int] = Field(default=None, primary_key=True, unique=True)
    flow_id: str = Field(index=True, max_length=32, description="Belonging SkillsID")
    name: str = Field(index=True, description="Version Name")
    data: Optional[Dict] = Field(default=None, description="Version Data")
    description: Optional[str] = Field(default=None, sa_column=Column(String(length=1000)))
    user_id: Optional[int] = Field(default=None, index=True, description="creator")
    flow_type: Optional[int] = Field(default=1, description="Type of version")
    is_current: Optional[int] = Field(default=0, description="Is version in use")
    is_delete: Optional[int] = Field(default=0, description="whether delete")
    original_version_id: Optional[int] = Field(default=None, description="Source Version ofID")
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    @field_validator('data')
    @classmethod
    def validate_json(cls, v):
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
    data: Optional[Dict] = Field(default=None, sa_column=Column(JSON), description="Version Data")


class FlowVersionRead(FlowVersionBase):
    pass


class FlowVersionDao(FlowVersionBase):

    @classmethod
    def create_version(cls, version: FlowVersion) -> FlowVersion:
        """
        Create New Version
        """
        with get_sync_db_session() as session:
            session.add(version)
            session.commit()
            session.refresh(version)
            return version

    @classmethod
    def update_version(cls, version: FlowVersion) -> FlowVersion:
        """
        Update the version information while updating the Skill SheetdataDATA
        """
        with get_sync_db_session() as session:
            session.add(version)
            session.commit()
            # Update the data in the skill sheet if it is the current version
            if version.is_current == 1:
                # Update Skill SheetdataDATA
                update_flow = update(Flow).where(Flow.id == version.flow_id).values(data=version.data)
                session.exec(update_flow)
                session.commit()
            session.refresh(version)
            return version

    @classmethod
    async def aupdate_version(cls, version: FlowVersion) -> FlowVersion:
        """
        Update version information asynchronously while updating the Skill SheetdataDATA
        """
        async with get_async_db_session() as session:
            session.add(version)
            await session.commit()
            # Update the data in the skill sheet if it is the current version
            if version.is_current == 1:
                # Update Skill SheetdataDATA
                update_flow = update(Flow).where(Flow.id == version.flow_id).values(data=version.data)
                await session.exec(update_flow)
                await session.commit()
            await session.refresh(version)
            return version

    @classmethod
    def get_version_by_name(cls, flow_id: str, name: str) -> Optional[FlowVersion]:
        """
        By SkillIDand version name for version information
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion).where(FlowVersion.flow_id == flow_id,
                                                  FlowVersion.name == name,
                                                  FlowVersion.is_delete == 0)
            return session.exec(statement).first()

    @classmethod
    def get_version_by_id(cls, version_id: int, include_delete: bool = False) -> Optional[FlowVersion]:
        """
        According to versionIDGet information on the skill version
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion).where(FlowVersion.id == version_id)
            if not include_delete:
                statement = statement.where(FlowVersion.is_delete == 0)
            return session.exec(statement).first()

    @classmethod
    async def aget_version_by_id(cls, version_id: int, include_delete: bool = False) -> Optional[FlowVersion]:
        """
        According to versionIDGet skill version information (asynchronous)
        """
        async with get_async_db_session() as session:
            statement = select(FlowVersion).where(FlowVersion.id == version_id)
            if not include_delete:
                statement = statement.where(FlowVersion.is_delete == 0)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_version_by_flow(cls, flow_id: str) -> Optional[FlowVersion]:
        """
        By SkillIDGet information on the current skill version
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion).where(FlowVersion.flow_id == flow_id,
                                                  FlowVersion.is_current == 1,
                                                  FlowVersion.is_delete == 0)
            return session.exec(statement).first()

    @classmethod
    def get_list_by_ids(cls, ids: List[int]) -> List[FlowVersion]:
        """
        accordingIDList for all version details
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion).where(FlowVersion.id.in_(ids))
            return session.exec(statement).all()

    @classmethod
    def get_list_by_flow(cls, flow_id: str) -> List[FlowVersionRead]:
        """
        By SkillID Get all skill versions
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion.id, FlowVersion.flow_id, FlowVersion.name, FlowVersion.description,
                               FlowVersion.is_current, FlowVersion.create_time, FlowVersion.update_time).where(
                FlowVersion.flow_id == flow_id, FlowVersion.is_delete == 0).order_by(FlowVersion.id.desc())
            ret = session.exec(statement).mappings().all()
            return [FlowVersionRead.model_validate(f) for f in ret]

    @classmethod
    def count_list_by_flow(cls, flow_id: str, include_delete: bool = False) -> int:
        """
        By SkillID Number of Skill Versions
        """
        with get_sync_db_session() as session:
            count_statement = session.query(func.count()).where(FlowVersion.flow_id == flow_id)
            if not include_delete:
                count_statement = count_statement.where(FlowVersion.is_delete == 0)
            return count_statement.scalar()

    @classmethod
    def get_list_by_flow_ids(cls, flow_ids: List[str]) -> List[FlowVersionRead]:
        """
        By SkillIDVertical Get all versions of all skills
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion.id, FlowVersion.flow_id, FlowVersion.name, FlowVersion.description,
                               FlowVersion.is_current, FlowVersion.create_time, FlowVersion.update_time).where(
                FlowVersion.flow_id.in_(flow_ids), FlowVersion.is_delete == 0).order_by(FlowVersion.id.desc())
            ret = session.exec(statement).mappings().all()
            return [FlowVersionRead.model_validate(f) for f in ret]

    @classmethod
    def delete_flow_version(cls, version_id: int) -> None:
        """
        Deleting a version, the version in use cannot be deleted
        """
        with get_sync_db_session() as session:
            update_statement = update(FlowVersion).where(
                FlowVersion.id == version_id, FlowVersion.is_current == 0).values(is_delete=1)
            session.exec(update_statement)
            session.commit()

    @classmethod
    async def change_current_version(cls, flow_id: str, new_version_info: FlowVersion) -> bool:
        """
        Modify the current version of the skill, Determine if the current version exists
        Also modify the Skill SheetdataDATA
        """
        async with get_async_db_session() as session:
            # Set current version
            set_statement = update(FlowVersion).where(
                FlowVersion.flow_id == flow_id,
                FlowVersion.id == new_version_info.id,
                FlowVersion.is_delete == 0,
            ).values(is_current=1)
            update_ret = await session.exec(set_statement)
            if update_ret.rowcount == 0:
                # If the update is not successful, the current version of the previous setting is not canceled
                return False

            # Update Skill SheetdataDATA
            update_flow = update(Flow).where(Flow.id == flow_id).values(data=new_version_info.data)
            await session.exec(update_flow)
            await session.commit()

            # Modify another version to not the current version
            statement = update(FlowVersion).where(
                FlowVersion.flow_id == flow_id,
                FlowVersion.id != new_version_info.id,
                FlowVersion.is_current == 1).values(
                is_current=0)
            await session.exec(statement)
            await session.commit()

            return True
