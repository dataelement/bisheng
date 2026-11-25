"""External provider control facts. No file content, provider payloads or secrets.

Only the binding's active_generation selects a library. Generation rows are
retained for historical citations, reconciliation and cleanup; their state is
not a routing predicate. A repository changes the pointer under revision CAS.
"""

from datetime import UTC, datetime
from secrets import randbelow
from uuid import uuid4

from sqlalchemy import VARBINARY, BigInteger, CheckConstraint, Column, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class OpaqueId(TypeDecorator):
    """Compare exact UTF-8 bytes even on case-insensitive MySQL/DM8 installations."""

    impl = VARBINARY
    cache_ok = True

    def __init__(self, length=255):
        self.length = length
        super().__init__(length)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        raw = value.encode("utf-8")
        if not 0 < len(raw) <= self.length:
            raise ValueError("provider identifier outside supported byte length")
        return raw

    def process_result_value(self, value, dialect):
        return None if value is None else bytes(value).decode("utf-8")


class _ControlRow(SQLModelSerializable):
    tenant_id: int
    revision: int = 1
    create_time: datetime = Field(default_factory=_now)


class KnowledgeProviderInstance(_ControlRow, table=True):
    __tablename__ = "knowledge_provider_instance"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uk_kpi_tenant_id"),)

    id: int | None = Field(default=None, primary_key=True)
    provider_key: str = Field(max_length=48)
    endpoint: str = Field(max_length=512, repr=False, exclude=True)
    credential_ref: str = Field(max_length=256, repr=False, exclude=True)
    remote_scope_id: str = Field(sa_column=Column(OpaqueId(), nullable=False))
    capability_revision: int = 0
    state: str = Field(default="unverified", max_length=32)


class KnowledgeProviderGeneration(_ControlRow, table=True):
    __tablename__ = "knowledge_provider_generation"
    __table_args__ = (
        UniqueConstraint("tenant_id", "space_id", "generation", name="uk_kpg_space_gen"),
        # A remote library must not become the content store of another space.
        UniqueConstraint("tenant_id", "provider_instance_id", "remote_scope_id", "remote_kb_id", name="uk_kpg_remote"),
        ForeignKeyConstraint(
            ["tenant_id", "provider_instance_id"],
            ["knowledge_provider_instance.tenant_id", "knowledge_provider_instance.id"],
            name="fk_kpg_instance",
        ),
        CheckConstraint("generation > 0", name="ck_kpg_positive_gen"),
    )

    id: int | None = Field(default=None, primary_key=True)
    space_id: int
    generation: int
    provider_instance_id: int
    remote_scope_id: str = Field(sa_column=Column(OpaqueId(), nullable=False))
    remote_kb_id: str = Field(sa_column=Column(OpaqueId(), nullable=False))
    embedding_fingerprint: str | None = Field(default=None, max_length=64)
    content_revision: int = 0
    state: str = Field(default="provisioning", max_length=32)


def _generation_fk(column: str, name: str):
    return ForeignKeyConstraint(
        ["tenant_id", "space_id", column],
        [
            "knowledge_provider_generation.tenant_id",
            "knowledge_provider_generation.space_id",
            "knowledge_provider_generation.generation",
        ],
        name=name,
    )


class KnowledgeProviderBinding(_ControlRow, table=True):
    __tablename__ = "knowledge_provider_binding"
    __table_args__ = (
        UniqueConstraint("tenant_id", "space_id", name="uk_kpb_space"),
        _generation_fk("active_generation", "fk_kpb_active_gen"),
    )

    id: int | None = Field(default=None, primary_key=True)
    space_id: int
    provider_key: str = Field(max_length=48)
    active_generation: int | None = None  # NULL for explicitly native or not yet provisioned
    state: str = Field(default="provisioning", max_length=32)
    pending_write_operation_id: str | None = Field(default=None, max_length=36)
    wiki_target_revision: int = 0
    wiki_applied_revision: int = 0


class KnowledgeProviderMapping(_ControlRow, table=True):
    """Generation FK fixes the tenant/instance/scope/library of each remote ID."""

    __tablename__ = "knowledge_provider_mapping"
    __table_args__ = (
        _generation_fk("generation", "fk_kpm_gen"),
        UniqueConstraint(
            "tenant_id", "space_id", "generation", "resource_type", "remote_object_id", name="uk_kpm_remote"
        ),
        UniqueConstraint(
            "tenant_id", "space_id", "generation", "resource_type", "local_resource_id", name="uk_kpm_local"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    space_id: int
    generation: int
    resource_type: str = Field(max_length=32)
    local_resource_id: int  # physical file_id for a file version, directory_id for a directory
    logical_document_id: int | None = None
    version_id: int | None = None
    remote_object_id: str = Field(sa_column=Column(OpaqueId(), nullable=False))
    lifecycle_state: str = Field(default="pending", max_length=32)
    operation_epoch: int = 1
    ready_revision: int | None = None
    tombstoned_at: datetime | None = None


class KnowledgeProviderTagRef(_ControlRow, table=True):
    __tablename__ = "knowledge_provider_tag_ref"
    __table_args__ = (
        _generation_fk("generation", "fk_kpt_gen"),
        UniqueConstraint("tenant_id", "space_id", "generation", "remote_tag_id", name="uk_kpt_remote"),
        CheckConstraint("tag_ref_id BETWEEN 1 AND 9007199254740991", name="ck_kpt_safe_ref"),
    )

    # App-assigned: MySQL disallows CHECK on an AUTO_INCREMENT column. The
    # repository retries a rare PK collision, never looks up a tag by name.
    tag_ref_id: int = Field(
        default_factory=lambda: randbelow(2**53 - 1) + 1,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=False),
    )
    space_id: int
    generation: int
    remote_tag_id: str = Field(sa_column=Column(OpaqueId(), nullable=False))
    state: str = Field(default="active", max_length=32)


class KnowledgeProviderOperation(_ControlRow, table=True):
    __tablename__ = "knowledge_provider_operation"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "request_key", name="uk_kpo_request"),
        UniqueConstraint("tenant_id", "operation_id", name="uk_kpo_tenant_op"),
        Index("ix_kpo_due", "tenant_id", "state", "next_attempt_at", "operation_id"),
        Index("ix_kpo_lease", "tenant_id", "state", "lease_until", "operation_id"),
        ForeignKeyConstraint(
            ["tenant_id", "provider_instance_id"],
            ["knowledge_provider_instance.tenant_id", "knowledge_provider_instance.id"],
            name="fk_kpo_instance",
        ),
    )

    operation_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    kind: str = Field(max_length=48)
    request_key: str = Field(sa_column=Column(OpaqueId(), nullable=False))
    request_hash: str = Field(max_length=64)
    actor_user_id: int
    provider_instance_id: int
    remote_scope_id: str = Field(sa_column=Column(OpaqueId(), nullable=False))
    remote_kb_id: str = Field(sa_column=Column(OpaqueId(), nullable=False))
    space_id: int | None = None  # preallocated remote library can precede local space creation
    generation: int
    operation_epoch: int
    # Trusted, frozen control IDs/revisions only, never request bodies or responses.
    target_manifest: list[dict] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    expected_revision: int | None = None
    capability_revision: int
    remote_task_id: str | None = Field(default=None, sa_column=Column(OpaqueId(), nullable=True))
    state: str = Field(default="pending", max_length=32)
    phase: str = Field(max_length=48)
    attempt: int = 0
    next_attempt_at: datetime | None = Field(default_factory=_now)
    lease_token: str | None = Field(default=None, max_length=36)
    lease_until: datetime | None = None
    last_error_code: str | None = Field(default=None, max_length=64)


class KnowledgeProviderQuota(_ControlRow, table=True):
    """One charge per subject, accounting kind and local version, not per generation."""

    __tablename__ = "knowledge_provider_quota"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "subject_type",
            "subject_id",
            "accounting_kind",
            "space_id",
            "version_id",
            name="uk_kpq_version",
        ),
        Index("ix_kpq_subject", "tenant_id", "subject_type", "subject_id", "state"),
        ForeignKeyConstraint(
            ["tenant_id", "operation_id"],
            ["knowledge_provider_operation.tenant_id", "knowledge_provider_operation.operation_id"],
            name="fk_kpq_operation",
        ),
        CheckConstraint("byte_count >= 0", name="ck_kpq_bytes"),
    )

    id: int | None = Field(default=None, primary_key=True)
    operation_id: str = Field(max_length=36)
    space_id: int
    version_id: int
    subject_type: str = Field(max_length=32)
    subject_id: int
    accounting_kind: str = Field(max_length=32)
    state: str = Field(default="reserved", max_length=32)
    byte_count: int = Field(sa_column=Column(BigInteger, nullable=False))
    receipt_checksum: str | None = Field(default=None, max_length=128)
