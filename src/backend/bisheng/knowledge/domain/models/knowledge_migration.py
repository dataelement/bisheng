"""持久化的跨知识库文件迁移批次、单元、文件和尝试记录。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType

_BIGINT_PK = BigInteger().with_variant(Integer(), "sqlite")


class KnowledgeMigrationBatchStatus(str, Enum):
    PREFLIGHT_QUEUED = "preflight_queued"
    PREFLIGHTING = "preflighting"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    ABANDONED = "abandoned"


class KnowledgeMigrationUnitStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    POLICY_SKIPPED = "policy_skipped"
    FAILED = "failed"
    UNPROCESSED = "unprocessed"


class KnowledgeMigrationCheckpoint(str, Enum):
    PLANNED = "planned"
    TARGET_ROWS_CREATED = "target_rows_created"
    TARGET_OBJECTS_COPIED = "target_objects_copied"
    TARGET_INDEXES_BUILT = "target_indexes_built"
    TARGET_PERMISSIONS_READY = "target_permissions_ready"
    TARGET_VERIFIED = "target_verified"
    DB_SWITCHED = "db_switched"
    SOURCE_EXTERNAL_CLEANED = "source_external_cleaned"
    SOURCE_ROWS_CLEANED = "source_rows_cleaned"
    COMPLETED = "completed"


class KnowledgeMigrationAttemptResult(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


TERMINAL_BATCH_STATUSES = frozenset(
    {
        KnowledgeMigrationBatchStatus.SUCCEEDED.value,
        KnowledgeMigrationBatchStatus.PARTIAL_SUCCESS.value,
        KnowledgeMigrationBatchStatus.FAILED.value,
        KnowledgeMigrationBatchStatus.ABANDONED.value,
    }
)


def _created_at_column() -> Column:
    return Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


def _updated_at_column() -> Column:
    return Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)


class KnowledgeMigrationBatch(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_migration_batch"

    id: int | None = Field(
        default=None,
        sa_column=Column(_BIGINT_PK, primary_key=True, autoincrement=True),
    )
    batch_no: str = Field(sa_column=Column(String(36), nullable=False))
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    request_id: str = Field(sa_column=Column(String(64), nullable=False))
    operator_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    operator_name: str = Field(sa_column=Column(String(128), nullable=False))
    source_selection_snapshot: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=False),
    )
    source_spaces_snapshot: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=False),
    )
    target_space_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    target_space_name: str = Field(sa_column=Column(String(200), nullable=False))
    target_space_level: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    target_folder_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    target_folder_name: str | None = Field(default=None, sa_column=Column(String(200), nullable=True))
    target_path_snapshot: str = Field(
        default="/",
        sa_column=Column(String(1024), nullable=False, server_default=text("'/'")),
    )
    conflict_strategy: str = Field(
        default="skip",
        sa_column=Column(String(16), nullable=False, server_default=text("'skip'")),
    )
    preserve_structure: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1")),
    )
    preserve_link: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("0"),
            comment="Publish each unit up one level and leave a shortcut at the source",
        ),
    )
    status: str = Field(
        default=KnowledgeMigrationBatchStatus.PREFLIGHT_QUEUED.value,
        sa_column=Column(String(32), nullable=False, server_default=text("'preflight_queued'")),
    )
    current_stage: str = Field(
        default="preflight_queued",
        sa_column=Column(String(32), nullable=False, server_default=text("'preflight_queued'")),
    )
    round_no: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    scanned_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    total_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    executable_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    completed_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    succeeded_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    skipped_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    failed_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    unprocessed_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    overwrite_target_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    preflight_task_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    execution_task_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    last_error_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    last_error_summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    confirmed_by: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    confirmed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    abandoned_by: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    abandoned_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    deleted_by: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    queued_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(default=None, sa_column=_created_at_column())
    update_time: datetime | None = Field(default=None, sa_column=_updated_at_column())

    __table_args__ = (
        UniqueConstraint("batch_no", name="uk_knowledge_migration_batch_no"),
        UniqueConstraint("operator_id", "request_id", name="uk_knowledge_migration_request"),
        Index("ix_kmb_deleted_created", "deleted_at", "create_time", "id"),
        Index("ix_kmb_status_created", "status", "create_time", "id"),
        Index("ix_kmb_status_queued", "status", "queued_at", "id"),
    )

    @property
    def can_soft_delete(self) -> bool:
        return self.status in TERMINAL_BATCH_STATUSES


class KnowledgeMigrationUnit(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_migration_unit"

    id: int | None = Field(
        default=None,
        sa_column=Column(_BIGINT_PK, primary_key=True, autoincrement=True),
    )
    batch_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    unit_key: str = Field(sa_column=Column(String(96), nullable=False))
    unit_type: str = Field(
        default="file",
        sa_column=Column(String(24), nullable=False, server_default=text("'file'")),
    )
    source_document_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    source_space_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    source_space_name: str = Field(sa_column=Column(String(200), nullable=False))
    source_space_level: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    source_parent_folder_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    source_path_snapshot: str = Field(
        default="/",
        sa_column=Column(String(1024), nullable=False, server_default=text("'/'")),
    )
    planned_target_folder_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    planned_target_path_snapshot: str = Field(
        default="/",
        sa_column=Column(String(1024), nullable=False, server_default=text("'/'")),
    )
    status: str = Field(
        default=KnowledgeMigrationUnitStatus.PLANNED.value,
        sa_column=Column(String(24), nullable=False, server_default=text("'planned'")),
    )
    reason_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    checkpoint: str = Field(
        default=KnowledgeMigrationCheckpoint.PLANNED.value,
        sa_column=Column(String(32), nullable=False, server_default=text("'planned'")),
    )
    target_document_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    overwrite_unit_key: str | None = Field(default=None, sa_column=Column(String(96), nullable=True))
    overwrite_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    folder_mapping_snapshot: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(JsonType, nullable=True),
    )
    attempt_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    current_round_no: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(default=None, sa_column=_created_at_column())
    update_time: datetime | None = Field(default=None, sa_column=_updated_at_column())

    __table_args__ = (
        UniqueConstraint("batch_id", "unit_key", name="uk_knowledge_migration_unit_key"),
        Index("ix_kmu_batch_status", "batch_id", "status", "id"),
        Index("ix_kmu_batch_round_status", "batch_id", "current_round_no", "status", "id"),
    )


class KnowledgeMigrationFile(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_migration_file"

    id: int | None = Field(
        default=None,
        sa_column=Column(_BIGINT_PK, primary_key=True, autoincrement=True),
    )
    batch_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    unit_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    source_file_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    source_document_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    source_version_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    source_version_no: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    is_primary: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    source_space_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    source_space_name: str = Field(sa_column=Column(String(200), nullable=False))
    source_folder_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    source_path_snapshot: str = Field(
        default="/",
        sa_column=Column(String(1024), nullable=False, server_default=text("'/'")),
    )
    source_file_name: str = Field(sa_column=Column(String(200), nullable=False))
    source_metadata_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    source_resource_manifest: dict[str, Any] | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    target_file_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    target_space_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    target_space_name: str = Field(sa_column=Column(String(200), nullable=False))
    target_folder_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    target_path_snapshot: str = Field(
        default="/",
        sa_column=Column(String(1024), nullable=False, server_default=text("'/'")),
    )
    target_file_name: str = Field(sa_column=Column(String(200), nullable=False))
    target_resource_manifest: dict[str, Any] | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    status: str = Field(
        default=KnowledgeMigrationUnitStatus.PLANNED.value,
        sa_column=Column(String(24), nullable=False, server_default=text("'planned'")),
    )
    checkpoint: str = Field(
        default=KnowledgeMigrationCheckpoint.PLANNED.value,
        sa_column=Column(String(32), nullable=False, server_default=text("'planned'")),
    )
    reason_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    create_time: datetime | None = Field(default=None, sa_column=_created_at_column())
    update_time: datetime | None = Field(default=None, sa_column=_updated_at_column())

    __table_args__ = (
        UniqueConstraint("batch_id", "source_file_id", name="uk_knowledge_migration_source_file"),
        Index("ix_kmf_unit_version", "unit_id", "source_version_no", "id"),
    )


class KnowledgeMigrationAttempt(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_migration_attempt"

    id: int | None = Field(
        default=None,
        sa_column=Column(_BIGINT_PK, primary_key=True, autoincrement=True),
    )
    batch_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    unit_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    round_no: int = Field(sa_column=Column(Integer, nullable=False))
    attempt_no: int = Field(sa_column=Column(Integer, nullable=False))
    worker_task_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    execution_token: str = Field(sa_column=Column(String(64), nullable=False))
    start_checkpoint: str = Field(
        default=KnowledgeMigrationCheckpoint.PLANNED.value,
        sa_column=Column(String(32), nullable=False, server_default=text("'planned'")),
    )
    end_checkpoint: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    result: str = Field(
        default=KnowledgeMigrationAttemptResult.RUNNING.value,
        sa_column=Column(String(24), nullable=False, server_default=text("'running'")),
    )
    reason_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    error_summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    started_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(default=None, sa_column=_created_at_column())
    update_time: datetime | None = Field(default=None, sa_column=_updated_at_column())

    __table_args__ = (
        UniqueConstraint("unit_id", "attempt_no", name="uk_knowledge_migration_attempt_no"),
        Index("ix_kma_batch_round", "batch_id", "round_no", "id"),
    )
