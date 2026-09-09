"""F062 user policy persistence model."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig, model_configs_payload, validate_model_configs


class ModelConfigsType(TypeDecorator):
    """Keep business configuration typed while using the shared dual-database JSON adapter."""

    impl = JsonType
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return model_configs_payload(value)

    def process_result_value(self, value, dialect):
        return validate_model_configs(value)


class DshUserPolicy(SQLModelSerializable, table=True):
    """Current user policy; immutable history belongs to DshAdminOperation."""

    __tablename__ = "dsh_user_policy"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_dsh_policy_user"),
        CheckConstraint("version >= 0 AND quota_epoch >= 1", name="ck_dsh_policy_counters"),
        CheckConstraint("quota_sync_state IN ('PENDING','READY','FROZEN')", name="ck_dsh_policy_sync"),
    )
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
    model_configs: list[DshModelQuotaConfig] = Field(
        default_factory=list, sa_column=Column(ModelConfigsType, nullable=False)
    )

    @property
    def allowed_model_ids(self) -> list[int]:
        return [item.model_id for item in self.model_configs]

    @property
    def monthly_token_limit(self) -> int:
        """Informational total; admission must enforce the selected model's own allowance."""
        return sum(item.monthly_token_limit for item in self.model_configs)

    version: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    quota_sync_state: str = Field(
        default="PENDING", sa_column=Column(String(16), nullable=False, server_default=text("'PENDING'"))
    )
    quota_epoch: int = Field(default=1, sa_column=Column(BigInteger, nullable=False, server_default=text("1")))
    updated_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    pending_operation_id: str | None = Field(default=None, sa_column=Column(String(36), nullable=True))
