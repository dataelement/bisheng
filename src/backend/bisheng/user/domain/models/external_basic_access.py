"""用户领域的自动角色关系及撤销栅栏, 不替代人工授权。"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, CheckConstraint, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class UserExternalBasicAccess(SQLModelSerializable, table=True):
    __tablename__ = "user_external_basic_access"
    __table_args__ = (
        UniqueConstraint("connection_id", "user_id", name="uq_ext_basic_access_user"),
        CheckConstraint("fence >= 0 AND applied_fence >= 0 AND applied_fence <= fence", name="ck_ext_access_fence"),
    )
    connection_id: str = Field(primary_key=True, max_length=64)
    identity_key: str = Field(primary_key=True, max_length=64)
    tenant_id: int = Field(index=True, sa_type=BigInteger)
    user_id: int | None = Field(default=None, sa_type=BigInteger)
    role_id: int | None = Field(default=None, sa_type=BigInteger)
    user_projection_operation_id: str | None = Field(default=None, max_length=36)
    user_projection_fence: int = Field(default=0, sa_type=BigInteger)
    user_projection_revision: str | None = Field(default=None, max_length=64)
    template_revision: int | None = Field(default=None, sa_type=BigInteger)
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
