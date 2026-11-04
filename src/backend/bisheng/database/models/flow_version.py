# Path: src/backend/bisheng/database/models/flow.py

from datetime import datetime

# if TYPE_CHECKING:
from pydantic import field_validator
from sqlalchemy import Integer, String, func
from sqlmodel import Column, DateTime, Field, select, text, update

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
from bisheng.database.models.flow import Flow, FlowType


class FlowVersionBase(SQLModelSerializable):
    id: int | None = Field(default=None, primary_key=True, unique=True)
    flow_id: str = Field(index=True, max_length=32, description="Belonging SkillsID")
    name: str = Field(index=True, description="Version Name")
    data: dict | None = Field(default=None, description="Version Data")
    description: str | None = Field(default=None, sa_column=Column(String(length=1000)))
    user_id: int | None = Field(default=None, index=True, description="creator")
    flow_type: int | None = Field(default=FlowType.WORKFLOW.value, description="Type of version")
    is_current: int | None = Field(default=0, description="Is version in use")
    is_delete: int | None = Field(default=0, description="whether delete")
    original_version_id: int | None = Field(default=None, description="Source Version ofID")
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )

    @field_validator("data")
    @classmethod
    def validate_json(cls, v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            return v
        if not isinstance(v, dict):
            raise ValueError("Flow must be a valid JSON")

        # data must contain nodes and edges
        if "nodes" not in v.keys():
            raise ValueError("Flow must have nodes")
        if "edges" not in v.keys():
            raise ValueError("Flow must have edges")
        return v


class FlowVersion(FlowVersionBase, table=True):
    data: dict | None = Field(default=None, sa_column=Column(JsonType), description="Version Data")


class FlowVersionRead(FlowVersionBase):
    pass


class FlowVersionDao(FlowVersionBase):
    @classmethod
    def create_version(cls, version: FlowVersion) -> FlowVersion:
        with get_sync_db_session() as session:
            parent = session.exec(
                select(Flow).where(Flow.id == version.flow_id, Flow.is_delete == 0).with_for_update()
            ).first()
            if parent is None:
                raise NotFoundError()
            session.add(version)
            session.commit()
            session.refresh(version)
            return version

    @classmethod
    def update_version(cls, version: FlowVersion) -> FlowVersion:
        with get_sync_db_session() as session:
            parent = session.exec(
                select(Flow).where(Flow.id == version.flow_id, Flow.is_delete == 0).with_for_update()
            ).first()
            if parent is None:
                raise NotFoundError()
            current = session.exec(
                select(FlowVersion).where(FlowVersion.id == version.id, FlowVersion.flow_id == parent.id)
            ).first()
            if current is None:
                raise NotFoundError()
            for key in ("name", "description", "data", "is_delete"):
                setattr(current, key, getattr(version, key))
            if current.is_current == 1:
                parent.data = current.data
                session.add(parent)
            session.add(current)
            session.commit()
            session.refresh(current)
            return current

    @classmethod
    async def aupdate_version(cls, version: FlowVersion) -> FlowVersion:
        async with get_async_db_session() as session:
            parent = (
                await session.exec(
                    select(Flow).where(Flow.id == version.flow_id, Flow.is_delete == 0).with_for_update()
                )
            ).first()
            if parent is None:
                raise NotFoundError()
            current = (
                await session.exec(
                    select(FlowVersion).where(FlowVersion.id == version.id, FlowVersion.flow_id == parent.id)
                )
            ).first()
            if current is None:
                raise NotFoundError()
            for key in ("name", "description", "data", "is_delete"):
                setattr(current, key, getattr(version, key))
            if current.is_current == 1:
                parent.data = current.data
                session.add(parent)
            session.add(current)
            await session.commit()
            await session.refresh(current)
            return current

    @classmethod
    def get_version_by_name(cls, flow_id: str, name: str) -> FlowVersion | None:
        """
        By SkillIDand version name for version information
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion).where(
                FlowVersion.flow_id == flow_id, FlowVersion.name == name, FlowVersion.is_delete == 0
            )
            return session.exec(statement).first()

    @classmethod
    def get_version_by_id(cls, version_id: int, include_delete: bool = False) -> FlowVersion | None:
        """
        According to versionIDGet information on the skill version
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion).where(FlowVersion.id == version_id)
            if not include_delete:
                statement = statement.where(FlowVersion.is_delete == 0)
            return session.exec(statement).first()

    @classmethod
    async def aget_version_by_id(cls, version_id: int, include_delete: bool = False) -> FlowVersion | None:
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
    def get_version_by_flow(cls, flow_id: str) -> FlowVersion | None:
        """
        By SkillIDGet information on the current skill version
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion).where(
                FlowVersion.flow_id == flow_id, FlowVersion.is_current == 1, FlowVersion.is_delete == 0
            )
            return session.exec(statement).first()

    @classmethod
    def get_list_by_ids(cls, ids: list[int]) -> list[FlowVersion]:
        """
        accordingIDList for all version details
        """
        with get_sync_db_session() as session:
            statement = select(FlowVersion).where(FlowVersion.id.in_(ids))
            return session.exec(statement).all()

    @classmethod
    def get_list_by_flow(cls, flow_id: str) -> list[FlowVersionRead]:
        """
        By SkillID Get all skill versions
        """
        with get_sync_db_session() as session:
            statement = (
                select(
                    FlowVersion.id,
                    FlowVersion.flow_id,
                    FlowVersion.name,
                    FlowVersion.description,
                    FlowVersion.is_current,
                    FlowVersion.create_time,
                    FlowVersion.update_time,
                )
                .where(FlowVersion.flow_id == flow_id, FlowVersion.is_delete == 0)
                .order_by(FlowVersion.id.desc())
            )
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
    def get_list_by_flow_ids(cls, flow_ids: list[str]) -> list[FlowVersionRead]:
        """
        By SkillIDVertical Get all versions of all skills
        """
        with get_sync_db_session() as session:
            statement = (
                select(
                    FlowVersion.id,
                    FlowVersion.flow_id,
                    FlowVersion.name,
                    FlowVersion.description,
                    FlowVersion.is_current,
                    FlowVersion.create_time,
                    FlowVersion.update_time,
                )
                .where(FlowVersion.flow_id.in_(flow_ids), FlowVersion.is_delete == 0)
                .order_by(FlowVersion.id.desc())
            )
            ret = session.exec(statement).mappings().all()
            return [FlowVersionRead.model_validate(f) for f in ret]

    @classmethod
    def delete_flow_version(cls, version_id: int) -> None:
        """
        Deleting a version, the version in use cannot be deleted
        """
        with get_sync_db_session() as session:
            update_statement = (
                update(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.is_current == 0).values(is_delete=1)
            )
            session.exec(update_statement)
            session.commit()

    @classmethod
    async def change_current_version(cls, flow_id: str, new_version_info: FlowVersion) -> bool:
        async with get_async_db_session() as session:
            parent = (
                await session.exec(select(Flow).where(Flow.id == flow_id, Flow.is_delete == 0).with_for_update())
            ).first()
            if parent is None:
                return False
            target = (
                await session.exec(
                    select(FlowVersion).where(
                        FlowVersion.id == new_version_info.id,
                        FlowVersion.flow_id == flow_id,
                        FlowVersion.is_delete == 0,
                    )
                )
            ).first()
            if target is None:
                return False
            await session.exec(
                update(FlowVersion)
                .where(FlowVersion.flow_id == flow_id, FlowVersion.id != target.id)
                .values(is_current=0)
            )
            target.is_current = 1
            parent.data = target.data
            session.add(target)
            session.add(parent)
            await session.commit()
            return True
