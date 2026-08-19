from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType

KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE = "knowledge_space_file_change_request"
KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE = "knowledge_space_file_change_request"


class KnowledgeSpaceFileChangeAction:
    UPLOAD = "upload"
    RENAME = "rename"
    MOVE = "move"
    DELETE = "delete"


class KnowledgeSpaceFileChangeResourceType:
    STAGED_UPLOAD = "staged_upload"
    KNOWLEDGE_FILE = "knowledge_file"
    FOLDER = "folder"
    KNOWLEDGE_FILE_VERSION = "knowledge_file_version"


class KnowledgeSpaceFileChangeExecutionState:
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    COMPENSATING = "compensating"
    CLOSED = "closed"


class KnowledgeSpaceFileChangeCleanupState:
    NONE = "none"
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class KnowledgeSpaceFileChangeLockScope:
    EXACT = "exact"
    SUBTREE = "subtree"
    DESTINATION = "destination"


class KnowledgeSpaceFileChangeRequestBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    space_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    action: str = Field(sa_column=Column(String(32), nullable=False))
    resource_type: str = Field(sa_column=Column(String(32), nullable=False))
    resource_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    applicant_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    business_key: str = Field(sa_column=Column(String(255), nullable=False))
    request_fingerprint: str = Field(sa_column=Column(String(128), nullable=False))
    approval_instance_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    decision_event_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    upload_stage_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    file_name: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    file_size: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    content_hash: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    source_parent_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    target_space_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    target_parent_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    action_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    result_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    executed_resource_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    execution_state: str = Field(
        default=KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=text("'not_started'"),
        ),
    )
    execution_token: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    execution_checkpoint: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    cleanup_state: str = Field(
        default=KnowledgeSpaceFileChangeCleanupState.NONE,
        sa_column=Column(String(32), nullable=False, server_default=text("'none'")),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class KnowledgeSpaceFileChangeRequest(KnowledgeSpaceFileChangeRequestBase, table=True):
    __tablename__ = "knowledge_space_file_change_request"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "approval_instance_id",
            name="uq_ks_change_request_instance",
        ),
        UniqueConstraint(
            "tenant_id",
            "upload_stage_id",
            name="uq_ks_change_request_upload",
        ),
        UniqueConstraint(
            "tenant_id",
            "decision_event_id",
            name="uq_ks_change_request_event",
        ),
        Index(
            "idx_ks_change_request_business_key",
            "tenant_id",
            "business_key",
        ),
        Index(
            "idx_ks_change_request_space_created",
            "tenant_id",
            "space_id",
            "create_time",
            "id",
        ),
        Index(
            "idx_ks_change_request_executed_file",
            "tenant_id",
            "space_id",
            "executed_resource_id",
        ),
        Index(
            "idx_ks_change_request_compensate",
            "tenant_id",
            "execution_state",
            "cleanup_state",
            "update_time",
            "id",
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


class KnowledgeSpaceFileChangeFootprintBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    request_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    space_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    resource_type: str = Field(sa_column=Column(String(32), nullable=False))
    resource_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    path_root: str | None = Field(default=None, sa_column=Column(String(2048), nullable=True))
    lock_scope: str = Field(sa_column=Column(String(16), nullable=False))


class KnowledgeSpaceFileChangeFootprint(KnowledgeSpaceFileChangeFootprintBase, table=True):
    __tablename__ = "knowledge_space_file_change_footprint"
    __table_args__ = (
        Index(
            "idx_ks_change_fp_request",
            "tenant_id",
            "request_id",
        ),
        Index(
            "idx_ks_change_fp_resource",
            "tenant_id",
            "space_id",
            "resource_type",
            "resource_id",
        ),
        Index(
            "idx_ks_change_fp_path",
            "tenant_id",
            "space_id",
            "path_root",
            mysql_length={"path_root": 512},
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
