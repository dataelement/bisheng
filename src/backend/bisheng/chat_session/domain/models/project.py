"""Account-private project metadata; conversations retain their original owner."""

from datetime import datetime
from uuid import uuid4

from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class ChatProject(SQLModelSerializable, table=True):
    __tablename__ = "chat_project"
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int = Field(index=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=30)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    deleted_at: datetime | None = None


class ChatProjectMembership(SQLModelSerializable, table=True):
    __tablename__ = "chat_project_membership"
    tenant_id: int = Field(primary_key=True, index=True)
    user_id: int = Field(primary_key=True)
    chat_id: str = Field(primary_key=True, max_length=255)
    project_id: str = Field(index=True, max_length=36)
