from datetime import datetime
from typing import Any, List, Optional

from sqlmodel import JSON, Column, DateTime, Field, select, text

from bisheng.core.database import get_sync_db_session
from bisheng.common.models.base import SQLModelSerializable
from bisheng.utils import generate_uuid


class ComponentBase(SQLModelSerializable):
    name: str = Field(max_length=50, index=True, description='Saved Component Name')
    description: Optional[str] = Field(default='', description='DESCRIPTION')
    data: Optional[Any] = Field(default=None, description='Component Data')
    version: str = Field(default='', index=True, description='Component Revision')
    user_id: int = Field(default=None, index=True, description='creatorID')
    user_name: str = Field(default=None, description='creatorName')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Component(ComponentBase, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True, unique=True)
    data: Optional[Any] = Field(default=None, sa_column=Column(JSON))


class ComponentDao(ComponentBase):

    @classmethod
    def get_user_components(cls, user_id: int) -> List[Component]:
        with get_sync_db_session() as session:
            statement = select(Component).where(
                Component.user_id == user_id
            ).order_by(Component.create_time.desc())
            return session.exec(statement).all()

    @classmethod
    def get_component_by_name(cls, user_id: int, name: str) -> Component | None:
        with get_sync_db_session() as session:
            statement = select(Component).where(Component.user_id == user_id, Component.name == name)
            return session.exec(statement).first()

    @classmethod
    def insert_component(cls, component: Component) -> Component:
        with get_sync_db_session() as session:
            session.add(component)
            session.commit()
            session.refresh(component)
            return component

    @classmethod
    def update_component(cls, component: Component) -> Component:
        with get_sync_db_session() as session:
            session.add(component)
            session.commit()
            session.refresh(component)
            return component

    @classmethod
    def delete_component(cls, component: Component) -> Component:
        with get_sync_db_session() as session:
            session.delete(component)
            session.commit()
            return component
