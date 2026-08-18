# ruff: noqa: RUF001, RUF002, RUF003
"""
Expert QA Database Models - SQLModel ORM

遵循 BiSheng 的 SQLModel + SQLAlchemy 2.0 规范
"""

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from bisheng.common.utils.beijing_time import now_beijing
from bisheng.core.database.dialect_helpers import LargeText

# ==================== 专家表 ====================


class Expert(SQLModel, table=True):
    """专家表"""

    __tablename__ = "qa_expert"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    user_id: int = Field(index=True)
    expert_name: str = Field(index=True)
    introduction: str | None = None
    depart_ment: str | None = Field(default=None, description="所属部门，JSON 格式")
    major: str | None = Field(default=None, description="所属专业")
    position: str | None = Field(default=None, description="所属岗位")
    job_family: str | None = Field(default=None, description="所属岗位族")
    job_category: str | None = Field(default=None, description="所属岗位分类")

    # 统计字段
    answer_count: int = Field(default=0)
    adoption_count: int = Field(default=0)
    vote_count: int = Field(default=0)
    # 1 有效 / 0 停用；历史行迁移默认有效
    status: int = Field(default=1, description="专家状态：1有效 0停用")

    # 时间戳
    created_at: datetime = Field(default_factory=now_beijing, index=True)
    updated_at: datetime = Field(default_factory=now_beijing)


# ==================== 问题表 ====================


class Question(SQLModel, table=True):
    """问题表"""

    __tablename__ = "qa_question"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    user_id: int = Field(index=True)
    title: str = Field(index=True)
    description: str
    business_domain: str = Field(index=True)
    status: int = Field(default=0, index=True)  # 0: 未解决, 1: 已解决, 2: 已关闭 3.待采纳
    question_type: str = Field(default="public", max_length=16, description="问题类型：directed/public")
    content_locked: int = Field(default=0, description="首个有效回答后内容锁定")
    asker_anonymous: int = Field(default=0, description="提问者是否匿名（公开/定向均可）")
    asker_reveal_on_public: int | None = Field(default=None, description="定向且匿名时：转公开后是否公开提问者姓名")
    adopt_count: int = Field(default=0, description="有效采纳条数（0–3）")
    resolved_at: datetime | None = Field(default=None, description="首次采纳成功时间")
    active_publish_request_id: int | None = Field(default=None, description="当前有效转公开申请ID（无则空）")
    attachments: str | None = Field(
        default=None,
        sa_column=Column(LargeText),
        description="分号分隔的持久化附件引用或业务 ID",
    )
    related_docs: str | None = Field(default=None, description="关联文档 ID 列表")
    invited_experts: str | None = Field(default=None, description="被邀请的专家 ID 列表")

    experts_names: str | None = Field(default=None, description="邀请专家名称，多个用分号;分割")
    image_url: str | None = Field(default=None, max_length=1024, schema_extra={"comment": "持久化图片引用"})
    file_url: str | None = Field(default=None, max_length=1024, schema_extra={"comment": "持久化附件引用"})
    file_name: str | None = Field(default=None, max_length=512, schema_extra={"comment": "文件名"})
    # 采纳的最佳回答
    adopted_answer_id: int | None = None
    # 统计字段
    vote_count: int = Field(default=0)
    answer_count: int = Field(default=0, index=True)
    view_count: int = Field(default=0)
    comment_count: int = Field(default=0)
    # 时间戳
    created_at: datetime = Field(default_factory=now_beijing, index=True)
    updated_at: datetime = Field(default_factory=now_beijing)
    created_by: str | None = Field(default=None, description="创建人")


# ==================== 回答表 ====================


class Answer(SQLModel, table=True):
    """回答表"""

    __tablename__ = "qa_answer"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    question_id: int = Field(index=True)
    expert_id: int | None = Field(default=None, index=True)
    user_id: int | None = Field(default=None, index=True, description="回答者用户ID")
    expert_name: str | None = Field(default=None, description="回答者名称（专家可选）")
    content: str
    status: int = Field(default=1, index=True)  # 1: normal, 2: adopted, 3: deleted
    anonymous: int = Field(default=0, description="本回答是否匿名（公开题）")
    reveal_on_public: int | None = Field(default=None, description="定向题：转公开后是否公开姓名")
    # 附件和关联文档
    attachments: str | None = Field(
        default=None,
        sa_column=Column(LargeText),
        description="分号分隔的持久化附件引用或业务 ID",
    )
    related_docs: str | None = Field(default=None, description="关联文档 ID 列表")
    images_url: str | None = Field(default=None, sa_column=Column(LargeText), description="分号分隔的持久化图片引用")
    # 统计字段
    vote_count: int = Field(default=0)
    comment_count: int = Field(default=0)
    adopted: bool | None = Field(default=False, index=True)  # 是否被采纳
    # 时间戳
    created_at: datetime = Field(default_factory=now_beijing, index=True)
    updated_at: datetime = Field(default_factory=now_beijing)


# ==================== 评论/追问表 ====================


class Comment(SQLModel, table=True):
    """评论/追问表"""

    __tablename__ = "qa_comment"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    answer_id: int = Field(index=True)
    question_id: int = Field(index=True)
    user_id: int = Field(index=True)
    user_name: str | None = Field(default=None, description="评论者名称")
    content: str
    is_follow_up: bool = Field(default=False)  # True 为追问，False 为评论
    anonymous: int = Field(default=0, description="评论是否匿名")
    reveal_on_public: int | None = Field(default=None, description="定向阶段预存：转公开后是否公开姓名")
    # 统计字段
    vote_count: int = Field(default=0)
    # 时间戳
    created_at: datetime = Field(default_factory=now_beijing, index=True)


# ==================== F083 正规化表（邀请 / 采纳 / 匿名 / 资格 / 转公开） ====================

QUESTION_TYPE_PUBLIC = "public"
QUESTION_TYPE_DIRECTED = "directed"
EXPERT_STATUS_ACTIVE = 1
EXPERT_STATUS_DISABLED = 0
ANSWER_STATUS_NORMAL = 1
ANSWER_STATUS_DELETED = 3
PUBLISH_STATUS_PENDING = "pending"
PUBLISH_DECISION_PENDING = "pending"


class QuestionInvite(SQLModel, table=True):
    """问题邀请的专家；取代 invited_experts 分号串作为真相源。"""

    __tablename__ = "qa_question_invite"
    __table_args__ = (UniqueConstraint("question_id", "expert_id", name="uk_qa_invite_q_expert"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    question_id: int = Field(index=True, description="问题ID")
    expert_id: int = Field(description="专家档案ID（qa_expert.id）")
    user_id: int = Field(index=True, description="专家对应用户ID")
    created_at: datetime = Field(default_factory=now_beijing, description="创建时间")


class AnswerAdopt(SQLModel, table=True):
    """问题采纳槽位（每题最多 3 条，每回答最多 1 次）。"""

    __tablename__ = "qa_answer_adopt"
    __table_args__ = (
        UniqueConstraint("answer_id", name="uk_qa_adopt_answer"),
        UniqueConstraint("question_id", "answer_id", name="uk_qa_adopt_q_answer"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    question_id: int = Field(index=True, description="问题ID")
    answer_id: int = Field(description="回答ID")
    expert_user_id: int = Field(description="被采纳回答者用户ID")
    adopted_by: int = Field(description="提问者用户ID")
    created_at: datetime = Field(default_factory=now_beijing, description="创建时间")


class AnonymousAlias(SQLModel, table=True):
    """题内稳定匿名别名；序号不因删内容回收。"""

    __tablename__ = "qa_anonymous_alias"
    __table_args__ = (
        UniqueConstraint("question_id", "user_id", name="uk_qa_alias_q_user"),
        UniqueConstraint("question_id", "alias_ord", name="uk_qa_alias_q_ord"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    question_id: int = Field(index=True, description="问题ID")
    user_id: int = Field(description="用户ID")
    alias_ord: int = Field(description="分配序号（从1起，不回收）")
    alias_label: str = Field(max_length=32, description="匿名展示名，如匿名同事A")
    created_at: datetime = Field(default_factory=now_beijing, description="创建时间")


class AnswerEligibility(SQLModel, table=True):
    """公开题首次采纳后的回答资格快照。"""

    __tablename__ = "qa_answer_eligibility"
    __table_args__ = (UniqueConstraint("question_id", "user_id", name="uk_qa_elig_q_user"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    question_id: int = Field(index=True, description="问题ID")
    user_id: int = Field(description="有资格专家用户ID")
    source: str = Field(max_length=32, description="资格来源：invited / pre_adopt_answer")
    created_at: datetime = Field(default_factory=now_beijing, description="创建时间")


class PublishRequest(SQLModel, table=True):
    """定向题转公开申请头。"""

    __tablename__ = "qa_publish_request"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    question_id: int = Field(index=True, description="问题ID")
    initiator_user_id: int = Field(description="发起人用户ID")
    status: str = Field(max_length=16, description="pending/approved/rejected/expired/ended")
    duration_days: int = Field(description="有效期天数：1/3/7")
    expire_at: datetime = Field(description="到期时间")
    extension_days: int = Field(default=0, description="已累计延期天数（≤3）")
    version: int = Field(default=0, description="乐观锁版本")
    created_at: datetime = Field(default_factory=now_beijing, description="创建时间")
    updated_at: datetime = Field(default_factory=now_beijing, description="更新时间")


class PublishApprover(SQLModel, table=True):
    """转公开申请的审批人及决策。"""

    __tablename__ = "qa_publish_approver"
    __table_args__ = (UniqueConstraint("request_id", "user_id", name="uk_qa_pub_appr"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(default=1, index=True, description="租户ID")
    request_id: int = Field(index=True, description="转公开申请ID")
    user_id: int = Field(index=True, description="审批人用户ID")
    role_in_request: str = Field(max_length=16, description="asker / answerer")
    decision: str = Field(max_length=32, description="pending/approved/rejected/default_approved")
    decided_at: datetime | None = Field(default=None, description="决策时间")
    created_at: datetime = Field(default_factory=now_beijing, description="创建时间")


# ==================== 投票表 ====================


class QuestionVote(SQLModel, table=True):
    """问题投票（赞）记录"""

    __tablename__ = "qa_question_vote"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    question_id: int = Field(index=True)

    # 时间戳
    created_at: datetime = Field(default_factory=now_beijing)


class AnswerVote(SQLModel, table=True):
    """回答投票（赞/有用）记录"""

    __tablename__ = "qa_answer_vote"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    answer_id: int = Field(index=True)
    vote_type: str = Field(default="helpful")  # helpful 有用，support 支持
    # 时间戳
    created_at: datetime = Field(default_factory=now_beijing)


class CommentVote(SQLModel, table=True):
    """评论投票（赞）记录"""

    __tablename__ = "qa_comment_vote"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    comment_id: int = Field(index=True)

    # 时间戳
    created_at: datetime = Field(default_factory=now_beijing)


# ==================== 通知表 ====================


class QANotification(SQLModel, table=True):
    """专家问答站内消息"""

    __tablename__ = "qa_notification"

    id: int | None = Field(default=None, primary_key=True)
    recipient_id: int = Field(index=True)
    sender_id: int = Field(index=True)
    notification_type: str = Field(index=True)  # invited, answered, commented, adopted
    question_id: int = Field(index=True)
    answer_id: int | None = Field(default=None)
    content: str
    read: bool = Field(default=False, index=True)

    # 多租户字段
    tenant_id: int = Field(default=1, index=True)

    # 时间戳
    created_at: datetime = Field(default_factory=now_beijing, index=True)
