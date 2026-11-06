"""Conversation-owned file manifests outlive individual chat messages."""

from sqlmodel import Column, Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import LargeText


class WorkflowFileManifest(SQLModelSerializable, table=True):
    __tablename__ = "workflow_file_manifest"

    id: str = Field(primary_key=True, max_length=64)
    tenant_id: int = Field(nullable=False, index=True)
    user_id: int = Field(nullable=False)
    chat_id: str = Field(max_length=255, index=True)
    files: str = Field(sa_column=Column(LargeText, nullable=False))
