"""积分模块 ORM 模型：流水只追加，余额与流水在同一事务维护。

库表字段均带中文 COMMENT，便于 DBA / 运营直接读库理解语义。
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType, LargeText


class UserPointAccount(SQLModelSerializable, table=True):
    """用户积分账户的读模型；允许余额为负数。"""

    __tablename__ = "user_point_account"
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False, server_default=text("1"), comment="租户ID"
        ),
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, comment="用户ID")
    )
    balance: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="当前积分余额（可为负）"
        ),
    )
    lifetime_earned: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="累计获得积分"
        ),
    )
    lifetime_deducted: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="累计扣减积分（绝对值合计）"
        ),
    )
    version: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="乐观锁版本号"
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
            comment="更新时间",
        ),
    )
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uk_upa_tenant_user"),
        Index("ix_upa_tenant_balance", "tenant_id", "balance"),
    )


class UserPointLog(SQLModelSerializable, table=True):
    """不可变积分账本流水；纠错只能通过追加反向流水完成。"""

    __tablename__ = "user_point_log"
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False, server_default=text("1"), comment="租户ID"
        ),
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, comment="用户ID")
    )
    delta: int = Field(
        sa_column=Column(Integer, nullable=False, comment="本次变动分值（正为获得，负为扣减）")
    )
    balance_after: int = Field(
        sa_column=Column(Integer, nullable=False, comment="变动后余额")
    )
    direction: str = Field(
        sa_column=Column(
            String(16), nullable=False, comment="变动方向：earn/deduct 等"
        )
    )
    rule_code: str | None = Field(
        default=None,
        sa_column=Column(String(32), comment="规则编码，如 G1/R1/M1"),
    )
    title: str = Field(
        sa_column=Column(String(64), nullable=False, comment="流水标题（展示用）")
    )
    source: str = Field(
        sa_column=Column(
            String(32),
            nullable=False,
            comment="来源：auto/admin_adjust/monthly_reward 等",
        )
    )
    biz_type: str | None = Field(
        default=None,
        sa_column=Column(String(32), comment="业务类型，如 answer/qa_question"),
    )
    biz_id: str | None = Field(
        default=None,
        sa_column=Column(String(64), comment="业务主键（字符串）"),
    )
    idempotency_key: str = Field(
        sa_column=Column(String(128), nullable=False, comment="幂等键，租户内唯一")
    )
    operator_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, comment="操作人用户ID（人工调分/扣分时）"),
    )
    remark: str | None = Field(
        default=None,
        sa_column=Column(String(200), comment="备注/原因"),
    )
    score_snapshot: int | None = Field(
        default=None,
        sa_column=Column(Integer, comment="记账时规则分值快照"),
    )
    beneficiary_role: str | None = Field(
        default=None,
        sa_column=Column(String(32), comment="受益人角色，如 answerer/uploader"),
    )
    occurred_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="业务发生时间（榜单/日 cap 统计窗口用）",
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="记录写入时间",
        ),
    )
    # ix_upl_tenant_dir_time 末列带 delta：运营概览的 SUM(delta) 可走纯索引扫描免回表。
    # ix_upl_source_time：管理端审计列表按 source 过滤 + occurred_at 倒序分页。
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uk_upl_tenant_idem"),
        Index("ix_upl_user_time", "tenant_id", "user_id", "occurred_at", "id"),
        Index("ix_upl_tenant_dir_time", "tenant_id", "direction", "occurred_at", "delta"),
        Index("ix_upl_source_time", "tenant_id", "source", "occurred_at", "id"),
    )


class PointRule(SQLModelSerializable, table=True):
    """租户积分规则；规则不能物理删除，只能停用。"""

    __tablename__ = "point_rule"
    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False, server_default=text("1"), comment="租户ID"
        ),
    )
    rule_code: str = Field(
        sa_column=Column(String(16), nullable=False, comment="规则编码，如 G1/R1/M1")
    )
    rule_type: str = Field(
        sa_column=Column(
            String(32),
            nullable=False,
            comment="规则类型：earn/deduct/admin_reward",
        )
    )
    name: str = Field(
        sa_column=Column(String(40), nullable=False, comment="规则名称")
    )
    score_expr: dict = Field(
        default_factory=dict,
        sa_column=Column(JsonType, nullable=False, comment="分值表达式 JSON"),
    )
    daily_cap: int | None = Field(
        default=None,
        sa_column=Column(Integer, comment="每日上限；空表示不限制"),
    )
    beneficiary: str | None = Field(
        default=None,
        sa_column=Column(String(32), comment="默认受益人角色"),
    )
    status: str = Field(
        default="enabled",
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=text("'enabled'"),
            comment="状态：enabled/disabled",
        ),
    )
    remark: str | None = Field(
        default=None,
        sa_column=Column(String(200), comment="备注"),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="排序权重，越小越靠前"
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
            comment="更新时间",
        ),
    )
    __table_args__ = (UniqueConstraint("tenant_id", "rule_code", name="uk_pr_tenant_code"),)


class PointCopy(SQLModelSerializable, table=True):
    """前台规则页的可配置说明文案。"""

    __tablename__ = "point_copy"
    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False, server_default=text("1"), comment="租户ID"
        ),
    )
    copy_key: str = Field(
        sa_column=Column(String(64), nullable=False, comment="文案键，如 guide")
    )
    content: str = Field(
        sa_column=Column(LargeText, nullable=False, comment="文案内容（富文本/纯文本）")
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="排序权重"
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
            comment="更新时间",
        ),
    )
    __table_args__ = (UniqueConstraint("tenant_id", "copy_key", name="uk_pc_tenant_key"),)


class PointRankSnapshot(SQLModelSerializable, table=True):
    """小时刷新后的排行榜快照。"""

    __tablename__ = "point_rank_snapshot"
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False, server_default=text("1"), comment="租户ID"
        ),
    )
    period: str = Field(
        sa_column=Column(
            String(16), nullable=False, comment="周期类型：month/year/all"
        )
    )
    scope: str = Field(
        sa_column=Column(
            String(16), nullable=False, comment="榜单范围：global（公司）/dept（部门桶）"
        )
    )
    scope_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, comment="范围ID：公司部门ID或部门桶ID"),
    )
    period_key: str = Field(
        sa_column=Column(
            String(16),
            nullable=False,
            comment="周期键：YYYY-MM / YYYY / all",
        )
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, comment="用户ID")
    )
    rank_no: int = Field(
        sa_column=Column(Integer, nullable=False, comment="名次（同分稠密并列）")
    )
    period_score: int = Field(
        sa_column=Column(Integer, nullable=False, comment="周期内积分净变动（all 为终身获得）")
    )
    balance: int = Field(
        sa_column=Column(Integer, nullable=False, comment="快照时账户余额")
    )
    dept_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, comment="用户所属部门桶ID（展示用）"),
    )
    refreshed_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="本批快照刷新时间",
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
    )
    # 榜单每小时整桶重建，读/写/删都按 (period, scope, period_key, scope_id) 定位同一个桶。
    __table_args__ = (
        Index(
            "ix_prs_bucket",
            "tenant_id",
            "period",
            "scope",
            "period_key",
            "scope_id",
            "rank_no",
        ),
        Index(
            "ix_prs_user",
            "tenant_id",
            "period",
            "period_key",
            "user_id",
            "scope",
            "scope_id",
        ),
        Index("ix_prs_refresh", "tenant_id", "period", "period_key", "refreshed_at"),
    )


class PointFavoriteTierAward(SQLModelSerializable, table=True):
    """记录 G3 已发最高档，防止取消收藏后重复发放。"""

    __tablename__ = "point_favorite_tier_award"
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False, server_default=text("1"), comment="租户ID"
        ),
    )
    file_id: int = Field(
        sa_column=Column(Integer, nullable=False, comment="知识文件ID")
    )
    highest_tier: int = Field(
        sa_column=Column(Integer, nullable=False, comment="已发放的最高阶梯档位")
    )
    points_granted_total: int = Field(
        sa_column=Column(Integer, nullable=False, comment="该文件累计已发 G3 积分")
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
            comment="更新时间",
        ),
    )
    __table_args__ = (UniqueConstraint("tenant_id", "file_id", name="uk_pfta_tenant_file"),)


class PointPendingDeduct(SQLModelSerializable, table=True):
    """违规删内容后扣分失败的补扣队列；幂等键与正式流水一致，可安全重试。"""

    __tablename__ = "point_pending_deduct"
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False, server_default=text("1"), comment="租户ID"
        ),
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, comment="待扣分用户ID")
    )
    rule_code: str = Field(
        sa_column=Column(String(32), nullable=False, comment="扣减规则编码，如 R1")
    )
    biz_type: str = Field(
        sa_column=Column(
            String(32), nullable=False, comment="业务类型，如 qa_question/qa_answer"
        )
    )
    biz_id: str = Field(
        sa_column=Column(String(64), nullable=False, comment="业务主键")
    )
    idempotency_key: str = Field(
        sa_column=Column(String(128), nullable=False, comment="幂等键，与正式扣分一致")
    )
    operator_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, comment="发起违规删除的操作人ID"),
    )
    remark: str | None = Field(
        default=None,
        sa_column=Column(String(200), comment="扣减原因备注"),
    )
    # pending / done / dead
    status: str = Field(
        default="pending",
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=text("'pending'"),
            comment="状态：pending/done/dead",
        ),
    )
    retry_count: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="已重试次数"
        ),
    )
    next_retry_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, comment="下次重试时间"),
    )
    last_error: str | None = Field(
        default=None,
        sa_column=Column(LargeText, comment="最近一次失败错误信息"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
            comment="更新时间",
        ),
    )
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uk_ppd_tenant_idem"),
        Index("ix_ppd_due", "status", "next_retry_at", "id"),
    )


class PointSyncOutbox(SQLModelSerializable, table=True):
    """积分流水的外部同步发件箱；外部失败不阻塞记账。"""

    __tablename__ = "point_sync_outbox"
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False, server_default=text("1"), comment="租户ID"
        ),
    )
    log_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, comment="关联 user_point_log.id")
    )
    payload: dict = Field(
        default_factory=dict,
        sa_column=Column(JsonType, nullable=False, comment="同步载荷 JSON"),
    )
    status: str = Field(
        default="pending",
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=text("'pending'"),
            comment="状态：pending/sent/dead 等",
        ),
    )
    retry_count: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="已重试次数"
        ),
    )
    next_retry_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, comment="下次重试时间"),
    )
    last_error: str | None = Field(
        default=None,
        sa_column=Column(LargeText, comment="最近一次失败错误信息"),
    )
    sent_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, comment="成功发送时间"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
            comment="更新时间",
        ),
    )
