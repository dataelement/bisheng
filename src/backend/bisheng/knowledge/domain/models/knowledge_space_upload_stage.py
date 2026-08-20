from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeSpaceUploadStageState:
    UPLOADED = "uploaded"
    # The request bundle is committed, but the temporary-bucket object has not
    # yet been copied to its deterministic permanent-bucket key.
    ATTACHING = "attaching"
    ATTACHED = "attached"
    CONSUMED = "consumed"
    CLEANUP_PENDING = "cleanup_pending"
    CLEANED = "cleaned"


class KnowledgeSpaceUploadStageBase(SQLModelSerializable):
    upload_id: str = Field(sa_column=Column(String(64), nullable=False))
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    space_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    uploader_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    object_name: str = Field(sa_column=Column(String(1024), nullable=False))
    file_name: str = Field(sa_column=Column(String(500), nullable=False))
    file_size: int = Field(sa_column=Column(BigInteger, nullable=False))
    content_hash: str = Field(sa_column=Column(String(128), nullable=False))
    state: str = Field(
        default=KnowledgeSpaceUploadStageState.UPLOADED,
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=text("'uploaded'"),
        ),
    )
    expire_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class KnowledgeSpaceUploadStage(KnowledgeSpaceUploadStageBase, table=True):
    __tablename__ = "knowledge_space_upload_stage"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "upload_id",
            name="uq_ks_upload_stage_tenant_upload",
        ),
        Index(
            "idx_ks_upload_stage_cleanup",
            "tenant_id",
            "state",
            "expire_at",
            "id",
        ),
        Index(
            "idx_ks_upload_stage_user",
            "tenant_id",
            "uploader_user_id",
            "state",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger().with_variant(Integer, "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
    )
