"""Recycle-bin snapshot rows for soft-deleted knowledge space files/folders."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Integer, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class KnowledgeRecycleItemBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True),
    )
    file_id: int = Field(index=True)
    knowledge_id: int = Field(index=True)
    file_type: int = Field(default=1)
    is_list_entry: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    display_name: str = Field(max_length=200)
    file_category_code: str | None = Field(default=None, max_length=64)
    file_subcategory_code: str | None = Field(default=None, max_length=16)
    business_domain_code: str | None = Field(default=None, max_length=64)
    tags_snapshot: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(JsonType, nullable=True),
    )
    file_encoding: str | None = Field(default=None, max_length=64)
    file_size: int | None = Field(default=None)
    md5: str | None = Field(default=None, max_length=64)
    space_level: str | None = Field(default=None, max_length=32)
    space_level_label: str | None = Field(default=None, max_length=64)
    original_knowledge_id: int = Field()
    original_parent_id: int | None = Field(default=None)
    original_path: str = Field(default="", max_length=1024)
    original_file_level_path: str | None = Field(default=None, max_length=1024)
    original_path_fingerprint: str | None = Field(default=None, max_length=128)
    deleted_by: int = Field()
    deleted_by_name: str | None = Field(default=None, max_length=128)
    deleted_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    expire_at: datetime = Field(sa_column=Column(DateTime, nullable=False, index=True))
    recycle_batch_id: str = Field(max_length=64, index=True)
    recycle_root_id: int = Field(index=True)
    document_id: int | None = Field(default=None)
    version_file_ids: list[int] | None = Field(
        default=None,
        sa_column=Column(JsonType, nullable=True),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class KnowledgeRecycleItem(KnowledgeRecycleItemBase, table=True):
    __tablename__ = "knowledge_recycle_item"
    id: int | None = Field(default=None, primary_key=True)
