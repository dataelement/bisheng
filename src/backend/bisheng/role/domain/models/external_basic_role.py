"""角色领域保存自动基础模板, 删除角色不删除来源墓碑。"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, CheckConstraint, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class RoleExternalBasicRole(SQLModelSerializable, table=True):
    __tablename__ = "role_external_basic_role"
    __table_args__ = (
        UniqueConstraint("role_id", name="uq_ext_basic_role"),
        CheckConstraint("fence >= 0 AND applied_fence >= 0 AND applied_fence <= fence", name="ck_ext_role_fence"),
    )
    connection_id: str = Field(primary_key=True, max_length=64)
    tenant_id: int = Field(primary_key=True, index=True, sa_type=BigInteger)
    # 不设级联外键, 保留被删除角色的 ID 和阻断证据。
    role_id: int | None = Field(default=None, sa_type=BigInteger)
    template_revision: int = Field(default=1, sa_type=BigInteger)
    local_policy_revision: int = Field(default=1, sa_type=BigInteger)
    menu_digest: str | None = Field(default=None, max_length=64)
    local_blocked: bool = False
    state: str = Field(default="PENDING", max_length=32, index=True)
    operation_id: str | None = Field(default=None, max_length=36)
    payload_digest: str | None = Field(default=None, max_length=64)
    fence: int = Field(default=0, sa_type=BigInteger)
    applied_fence: int = Field(default=0, sa_type=BigInteger)
    applied_operation_id: str | None = Field(default=None, max_length=36)
    applied_template_revision: int | None = Field(default=None, sa_type=BigInteger)
    reason_code: str | None = Field(default=None, max_length=64)
    create_time: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    update_time: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
