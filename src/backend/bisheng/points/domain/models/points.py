"""积分模块 ORM 模型：流水只追加，余额与流水在同一事务维护。"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType, LargeText, UPDATE_TIME_SERVER_DEFAULT


class UserPointAccount(SQLModelSerializable, table=True):
    """用户积分账户的读模型；允许余额为负数。"""

    __tablename__ = "user_point_account"
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    tenant_id: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    balance: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    lifetime_earned: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    lifetime_deducted: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    version: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    create_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    update_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uk_upa_tenant_user"), Index("ix_upa_tenant_balance", "tenant_id", "balance"))


class UserPointLog(SQLModelSerializable, table=True):
    """不可变积分账本流水；纠错只能通过追加反向流水完成。"""

    __tablename__ = "user_point_log"
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    tenant_id: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    delta: int = Field(sa_column=Column(Integer, nullable=False))
    balance_after: int = Field(sa_column=Column(Integer, nullable=False))
    direction: str = Field(sa_column=Column(String(16), nullable=False))
    rule_code: str | None = Field(default=None, sa_column=Column(String(32)))
    title: str = Field(sa_column=Column(String(64), nullable=False))
    source: str = Field(sa_column=Column(String(32), nullable=False))
    biz_type: str | None = Field(default=None, sa_column=Column(String(32)))
    biz_id: str | None = Field(default=None, sa_column=Column(String(64)))
    idempotency_key: str = Field(sa_column=Column(String(128), nullable=False))
    operator_id: int | None = Field(default=None, sa_column=Column(Integer))
    remark: str | None = Field(default=None, sa_column=Column(String(200)))
    score_snapshot: int | None = Field(default=None, sa_column=Column(Integer))
    beneficiary_role: str | None = Field(default=None, sa_column=Column(String(32)))
    occurred_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    create_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uk_upl_tenant_idem"), Index("ix_upl_user_time", "tenant_id", "user_id", "occurred_at", "id"), Index("ix_upl_tenant_dir_time", "tenant_id", "direction", "occurred_at"))


class PointRule(SQLModelSerializable, table=True):
    """租户积分规则；规则不能物理删除，只能停用。"""

    __tablename__ = "point_rule"
    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    tenant_id: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    rule_code: str = Field(sa_column=Column(String(16), nullable=False))
    rule_type: str = Field(sa_column=Column(String(32), nullable=False))
    name: str = Field(sa_column=Column(String(40), nullable=False))
    score_expr: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    daily_cap: int | None = Field(default=None, sa_column=Column(Integer))
    beneficiary: str | None = Field(default=None, sa_column=Column(String(32)))
    status: str = Field(default="enabled", sa_column=Column(String(16), nullable=False, server_default=text("'enabled'")))
    remark: str | None = Field(default=None, sa_column=Column(String(200)))
    sort_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    create_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    update_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))
    __table_args__ = (UniqueConstraint("tenant_id", "rule_code", name="uk_pr_tenant_code"),)


class PointCopy(SQLModelSerializable, table=True):
    """前台规则页的可配置说明文案。"""
    __tablename__ = "point_copy"
    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    tenant_id: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    copy_key: str = Field(sa_column=Column(String(64), nullable=False))
    content: str = Field(sa_column=Column(LargeText, nullable=False))
    sort_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    create_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    update_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))
    __table_args__ = (UniqueConstraint("tenant_id", "copy_key", name="uk_pc_tenant_key"),)


class PointRankSnapshot(SQLModelSerializable, table=True):
    """小时刷新后的排行榜快照。"""
    __tablename__ = "point_rank_snapshot"
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    tenant_id: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    period: str = Field(sa_column=Column(String(16), nullable=False))
    scope: str = Field(sa_column=Column(String(16), nullable=False))
    scope_id: int | None = Field(default=None, sa_column=Column(Integer))
    period_key: str = Field(sa_column=Column(String(16), nullable=False))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    rank_no: int = Field(sa_column=Column(Integer, nullable=False))
    period_score: int = Field(sa_column=Column(Integer, nullable=False))
    balance: int = Field(sa_column=Column(Integer, nullable=False))
    dept_id: int | None = Field(default=None, sa_column=Column(Integer))
    refreshed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    create_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))


class PointFavoriteTierAward(SQLModelSerializable, table=True):
    """记录 G3 已发最高档，防止取消收藏后重复发放。"""
    __tablename__ = "point_favorite_tier_award"
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    tenant_id: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    file_id: int = Field(sa_column=Column(Integer, nullable=False))
    highest_tier: int = Field(sa_column=Column(Integer, nullable=False))
    points_granted_total: int = Field(sa_column=Column(Integer, nullable=False))
    create_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    update_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))
    __table_args__ = (UniqueConstraint("tenant_id", "file_id", name="uk_pfta_tenant_file"),)


class PointSyncOutbox(SQLModelSerializable, table=True):
    """积分流水的外部同步发件箱；外部失败不阻塞记账。"""
    __tablename__ = "point_sync_outbox"
    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    tenant_id: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    log_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    payload: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    status: str = Field(default="pending", sa_column=Column(String(16), nullable=False, server_default=text("'pending'")))
    retry_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    next_retry_at: datetime | None = Field(default=None, sa_column=Column(DateTime))
    last_error: str | None = Field(default=None, sa_column=Column(LargeText))
    sent_at: datetime | None = Field(default=None, sa_column=Column(DateTime))
    create_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    update_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))
