"""用户领域拥有的外部身份投影栅栏。不改变既有账号表。"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import LargeText


def projection_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class UserExternalIdentityProjection(SQLModelSerializable, table=True):
    __tablename__ = "user_external_identity_projection"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_ext_projection_user"),
        CheckConstraint(
            "fence >= 0 AND applied_fence >= 0 AND applied_fence <= fence", name="ck_user_ext_projection_fence"
        ),
    )
    identity_key: str = Field(primary_key=True, max_length=64)
    tenant_id: int = Field(default=1, index=True, sa_type=BigInteger)
    issuer: str = Field(sa_column=Column(LargeText, nullable=False))
    subject: str = Field(max_length=128)
    external_tenant_id: str = Field(max_length=64)
    member_id: str = Field(max_length=64)
    user_id: int | None = Field(default=None, foreign_key="user.user_id")
    fence: int = Field(default=0, sa_type=BigInteger)
    operation_id: str | None = Field(default=None, max_length=36)
    source_revision: str | None = Field(default=None, max_length=64)
    payload_digest: str | None = Field(default=None, max_length=64)
    applied_fence: int = Field(default=0, sa_type=BigInteger)
    applied_operation_id: str | None = Field(default=None, max_length=36)
    applied_source_revision: str | None = Field(default=None, max_length=64)
    create_time: datetime = Field(default_factory=projection_now)
    update_time: datetime = Field(default_factory=projection_now)
