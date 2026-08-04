"""Logical document — anchors a version chain in a knowledge space."""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Index, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


def _default_document_tenant_id() -> int:
    tenant_id = get_current_tenant_id()
    if tenant_id is not None:
        return int(tenant_id)

    from bisheng.common.services.config_service import settings

    if settings.multi_tenant.enabled:
        raise ValueError(
            "KnowledgeDocument requires an explicit tenant context "
            "when multi-tenant mode is enabled"
        )
    return DEFAULT_TENANT_ID


class KnowledgeDocumentLifecycleStatus(str, Enum):
    ACTIVE = "active"
    DELETING = "deleting"
    INVALID = "invalid"


class KnowledgeDocumentBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(
        default_factory=_default_document_tenant_id,
        sa_column=Column(
            Integer,
            nullable=False,
            comment="Tenant ID populated by tenant context",
        ),
    )
    knowledge_id: int = Field(index=True, description="Owning knowledge space ID")
    file_level_path: Optional[str] = Field(
        default=None,
        index=True,
        description="Parent folder path, e.g. '/12/34'. None = root.",
    )
    level: Optional[int] = Field(default=0, description="Folder depth")
    primary_version_id: Optional[int] = Field(
        default=None,
        description="FK to knowledge_document_version.id of the current primary version",
    )
    predecessor_logic_file_id: Optional[int] = Field(
        default=None,
        description="Direct publish predecessor KnowledgeFile ID",
    )
    content_generation: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
        description="Canonical content generation",
    )
    lifecycle_status: str = Field(
        default=KnowledgeDocumentLifecycleStatus.ACTIVE.value,
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=text("'active'"),
        ),
        description="Canonical lifecycle state",
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')
        ),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT
        ),
    )


class KnowledgeDocument(KnowledgeDocumentBase, table=True):
    __tablename__ = 'knowledge_document'
    __table_args__ = (
        Index(
            "idx_kdoc_tenant_lifecycle",
            "tenant_id",
            "lifecycle_status",
        ),
        Index(
            "idx_kdoc_tenant_content_generation",
            "tenant_id",
            "content_generation",
        ),
        Index(
            "idx_kdoc_tenant_predecessor",
            "tenant_id",
            "predecessor_logic_file_id",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeDocumentRead(KnowledgeDocumentBase):
    id: int


class KnowledgeDocumentCreate(KnowledgeDocumentBase):
    pass
