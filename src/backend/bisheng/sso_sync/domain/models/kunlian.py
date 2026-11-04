"""昆联集成控制面数据。本地业务用户与资源仍由原领域拥有。"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Column, String, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType, LargeText


def utc_now() -> datetime:
    """数据库统一存储无时区 UTC。避免方言隐式转换。"""
    return datetime.now(UTC).replace(tzinfo=None)


class KunlianControlRecord(SQLModelSerializable):
    tenant_id: int = Field(default=1, index=True, sa_type=BigInteger)
    create_time: datetime = Field(default_factory=utc_now)
    update_time: datetime = Field(default_factory=utc_now)


class KunlianConnectionState(KunlianControlRecord, table=True):
    __tablename__ = "kunlian_connection_state"
    connection_id: str = Field(primary_key=True, max_length=64)
    active_batch_id: str | None = Field(default=None, max_length=36)
    sync_fence: int = Field(default=0, sa_type=BigInteger)
    lease_owner: str | None = Field(default=None, max_length=64)
    lease_until: datetime | None = None
    enabled: bool = False
    policy_revision: int = Field(default=1, sa_type=BigInteger)
    sync_requested_version: int = Field(default=0, sa_type=BigInteger)
    sync_completed_version: int = Field(default=0, sa_type=BigInteger)
    sync_requested_at: datetime | None = None


class KunlianSyncBatch(KunlianControlRecord, table=True):
    __tablename__ = "kunlian_sync_batch"
    batch_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    connection_id: str = Field(foreign_key="kunlian_connection_state.connection_id", index=True)
    fence: int = Field(sa_type=BigInteger)
    status: str = Field(default="FETCHING", max_length=16)
    requested_version: int = Field(default=0, sa_type=BigInteger)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    counts: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    last_request_id: str | None = Field(default=None, max_length=128)
    cursor_ciphertext: str | None = Field(default=None, sa_column=Column(LargeText))
    key_version: str = Field(max_length=64)
    page_size: int = 20
    reason_code: str | None = Field(default=None, max_length=64)


class KunlianDirectoryTenant(KunlianControlRecord, table=True):
    __tablename__ = "kunlian_directory_tenant"
    batch_id: str = Field(primary_key=True, foreign_key="kunlian_sync_batch.batch_id", max_length=36)
    external_tenant_id: str = Field(primary_key=True, max_length=64)
    status: str = Field(max_length=32)
    version: str | None = Field(default=None, max_length=256)
    summary: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))


class KunlianDirectoryMember(KunlianControlRecord, table=True):
    __tablename__ = "kunlian_directory_member"
    __table_args__ = (UniqueConstraint("batch_id", "external_tenant_id", "subject", name="uq_kl_member_subject"),)
    batch_id: str = Field(primary_key=True, foreign_key="kunlian_sync_batch.batch_id", max_length=36)
    external_tenant_id: str = Field(primary_key=True, max_length=64)
    member_id: str = Field(primary_key=True, max_length=64)
    subject: str = Field(max_length=128)
    status: str = Field(max_length=32)
    deleted: bool = False
    member_version: str | None = Field(default=None, max_length=256)
    authorization_version: str | None = Field(default=None, max_length=256)
    summary: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))


class KunlianTenantBinding(KunlianControlRecord, table=True):
    __tablename__ = "kunlian_tenant_binding"
    __table_args__ = (UniqueConstraint("connection_id", "local_tenant_id", name="uq_kl_local_tenant"),)
    connection_id: str = Field(primary_key=True, foreign_key="kunlian_connection_state.connection_id", max_length=64)
    external_tenant_id: str = Field(primary_key=True, max_length=64)
    local_tenant_id: int = Field(sa_type=BigInteger)
    revision: int = Field(default=1, sa_type=BigInteger)
    enabled: bool = True
    materialized: bool = False


class KunlianIdentityBinding(KunlianControlRecord, table=True):
    __tablename__ = "kunlian_identity_binding"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_tenant_id", "member_id", name="uq_kl_identity_member"),
        UniqueConstraint("local_user_id", name="uq_kl_local_user"),
    )
    identity_key: str = Field(primary_key=True, max_length=64)
    connection_id: str = Field(foreign_key="kunlian_connection_state.connection_id", max_length=64, index=True)
    issuer: str = Field(sa_column=Column(LargeText, nullable=False))
    subject: str = Field(max_length=128)
    external_tenant_id: str = Field(max_length=64)
    member_id: str = Field(max_length=64)
    local_user_id: int | None = Field(default=None, sa_type=BigInteger)
    source_revision: str = Field(max_length=64)
    projected_revision: str | None = Field(default=None, max_length=64)
    admission_status: str = Field(default="UNKNOWN", max_length=32)
    projection_status: str = Field(default="PENDING", max_length=16)
    auth_epoch: int = Field(default=1, sa_type=BigInteger)
    local_override: bool = False


class KunlianWebSession(KunlianControlRecord, table=True):
    __tablename__ = "kunlian_web_session"
    session_hash: str = Field(primary_key=True, max_length=64)
    binding_id: str = Field(foreign_key="kunlian_identity_binding.identity_key", index=True, max_length=64)
    auth_epoch_at_issue: int = Field(sa_type=BigInteger)
    browser_binding_hash: str = Field(max_length=64)
    client_id: str = Field(max_length=128)
    sid: str = Field(max_length=128)
    workspace_id: str = Field(max_length=128)
    access_token_ciphertext: str = Field(sa_column=Column(LargeText, nullable=False))
    id_token_ciphertext: str = Field(sa_column=Column(LargeText, nullable=False))
    token_key_version: str = Field(max_length=64)
    access_token_expires_at: datetime
    hard_expires_at: datetime
    issued_at: datetime = Field(default_factory=utc_now)
    state: str = Field(default="ACTIVE", max_length=24)
    csrf_epoch: int = Field(default=1, sa_type=BigInteger)
    revoked_at: datetime | None = None


class KunlianHandoffReceipt(KunlianControlRecord, table=True):
    __tablename__ = "kunlian_handoff_receipt"
    handoff_id: str = Field(primary_key=True, max_length=64)
    connection_id: str = Field(foreign_key="kunlian_connection_state.connection_id", max_length=64)
    request_digest: str = Field(max_length=64)
    session_hash: str = Field(foreign_key="kunlian_web_session.session_hash", max_length=64)
    session_ref_ciphertext: str = Field(sa_column=Column(LargeText, nullable=False))
    signing_context: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    state: str = Field(default="ISSUED", max_length=16)
    expires_at: datetime
    logout_ticket_hash: str | None = Field(default=None, sa_column=Column(String(64), unique=True))
    logout_ticket_expires_at: datetime | None = None
    logout_ticket_consumed_at: datetime | None = None
