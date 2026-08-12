"""积分接口的请求与响应模式。"""

from datetime import datetime

from pydantic import BaseModel, Field


class PointAdjustRequest(BaseModel):
    """管理员手动调分请求。"""

    user_id: int
    delta: int
    remark: str = Field(min_length=5, max_length=100)


class PointDeductRequest(BaseModel):
    """按扣减规则执行积分扣减。"""

    user_id: int
    rule_code: str
    biz_type: str | None = None
    biz_id: str | None = None
    remark: str | None = None


class PointRuleRequest(BaseModel):
    """创建或更新积分规则的可变字段。"""

    rule_code: str | None = None
    rule_type: str | None = None
    name: str | None = None
    score_expr: dict | None = None
    daily_cap: int | None = None
    beneficiary: str | None = None
    status: str | None = None
    remark: str | None = None
    sort_order: int | None = None


class PointCopyItem(BaseModel):
    """单条说明文案。"""

    copy_key: str
    content: str
    sort_order: int = 0


class PointCopiesUpdateRequest(BaseModel):
    """批量更新说明文案。"""

    items: list[PointCopyItem]


class PointLogResponse(BaseModel):
    """前台流水展示字段。"""

    id: int
    title: str
    delta: int
    balance_after: int
    direction: str
    rule_code: str | None
    source: str
    remark: str | None
    occurred_at: datetime | None


class PointSummaryResponse(BaseModel):
    """我的积分摘要。"""

    balance: int
    month_earned: int
    month_deducted: int
    dept_rank: int | None = None
    global_rank: int | None = None
    global_rank_display: str = "-"
    rank_refreshed_at: datetime | None = None


class PointOverviewResponse(BaseModel):
    """运营概览三绝对数。"""

    total_issued: int
    total_balance: int
    total_violation_deducted: int


class PointAdminUserItem(BaseModel):
    """管理端用户积分列表行。"""

    user_id: int
    user_name: str = ""
    dept_name: str = "—"
    balance: int
    month_score: int = 0


class PointAdminUserDetail(BaseModel):
    """管理端用户积分详情（弹窗：概况 + 时间范围内流水）。"""

    user_id: int
    user_name: str = ""
    dept_name: str = "—"
    role_label: str = "普通用户"
    balance: int = 0
    month_earned: int = 0
    month_deducted: int = 0
    logs: list[PointLogResponse] = Field(default_factory=list)
    logs_total: int = 0


class PointAuditLogItem(BaseModel):
    """管理端操作/审计流水行。"""

    id: int
    user_id: int
    user_name: str = ""
    title: str
    delta: int
    balance_after: int
    direction: str
    rule_code: str | None = None
    source: str
    operator_id: int | None = None
    remark: str | None = None
    occurred_at: datetime | None = None


class PointRuleResponse(BaseModel):
    """规则列表项。"""

    id: int
    rule_code: str
    rule_type: str
    name: str
    score_expr: dict
    daily_cap: int | None
    beneficiary: str | None
    beneficiary_options: list[str] = Field(default_factory=list)
    status: str
    remark: str | None
    sort_order: int


class PointLeaderboardItem(BaseModel):
    """排行榜条目。"""

    rank: int
    user_id: int
    user_name: str = ""
    dept_name: str = ""
    balance: int
    period_score: int


class PointLeaderboardResponse(BaseModel):
    """排行榜响应。"""

    period: str
    refreshed_at: datetime | None
    items: list[PointLeaderboardItem]


class DepartmentOrgLevelItem(BaseModel):
    """部门组织四级标签只读项。"""

    id: int
    dept_id: str | None = None
    name: str | None = None
    parent_id: int | None = None
    path: str | None = None
    org_level: str | None = None


class SetCompanyRootRequest(BaseModel):
    """指定公司根请求；confirm 预留给二次确认 UI。"""

    confirm: bool = True


class SetCompanyRootResponse(BaseModel):
    """公司根级联打标结果。"""

    company_id: int
    labeled_count: int
    levels: dict[str, int]


class ClearCompanyRootResponse(BaseModel):
    """取消公司根并清空组织层级标签的结果。"""

    cleared_count: int
