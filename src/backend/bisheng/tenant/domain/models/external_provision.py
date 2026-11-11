"""租户领域的外部开通回执; 不按名称认领已有租户。"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import LargeText


class TenantExternalProvision(SQLModelSerializable, table=True):
    __tablename__ = "tenant_external_provision"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_tenant_id", name="uq_ext_tenant_source"),
        UniqueConstraint("local_tenant_id", name="uq_ext_tenant_local"),
        CheckConstraint("fence >= 0 AND applied_fence >= 0 AND applied_fence <= fence", name="ck_ext_tenant_fence"),
    )
    source_key: str = Field(primary_key=True, max_length=64)
    tenant_id: int = Field(default=1, index=True, sa_type=BigInteger)
    connection_id: str = Field(max_length=64, index=True)
    issuer: str = Field(sa_column=Column(LargeText, nullable=False))
    issuer_digest: str = Field(max_length=64)
    external_tenant_id: str = Field(max_length=64)
    local_tenant_id: int | None = Field(default=None, sa_type=BigInteger)
    anchor_department_id: int | None = Field(default=None, sa_type=BigInteger)
    mapping_origin: str = Field(default="auto", max_length=16)
    source_batch_id: str | None = Field(default=None, max_length=36)
    source_revision: str | None = Field(default=None, max_length=64)
    policy_revision: int = Field(default=1, sa_type=BigInteger)
    local_policy_revision: int = Field(default=1, sa_type=BigInteger)
    local_blocked: bool = False
    state: str = Field(default="PENDING", max_length=32, index=True)
    operation_id: str | None = Field(default=None, max_length=36)
    payload_digest: str | None = Field(default=None, max_length=64)
    fence: int = Field(default=0, sa_type=BigInteger)
    applied_fence: int = Field(default=0, sa_type=BigInteger)
    applied_operation_id: str | None = Field(default=None, max_length=36)
    reason_code: str | None = Field(default=None, max_length=64)
    create_time: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    update_time: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
