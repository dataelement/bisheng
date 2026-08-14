"""
Expert QA Pydantic Schemas - 请求/响应数据模型
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from bisheng.qa_expert.domain.rich_text import sanitize_question_description

TEXT_ENCODING = "utf-8"
TEXT_DECODE_ERRORS = "replace"
BYTE_ORDER_BIG_ENDIAN = "big"
BOOLEAN_TRUE_TEXT_VALUES = {"1", "true", "t", "yes", "y", "on"}
BOOLEAN_FALSE_TEXT_VALUES = {"0", "false", "f", "no", "n", "off", ""}
BOOLEAN_TRUE_BYTES_VALUES = {b"\x01", b"1"}
BOOLEAN_FALSE_BYTES_VALUES = {b"\x00", b"", b"0"}


def _decode_db_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode(TEXT_ENCODING, errors=TEXT_DECODE_ERRORS)
    return str(value)


def _coerce_db_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bytes):
        text_value = _decode_db_text(value)
        if text_value and text_value.strip().lstrip("+-").isdigit():
            return int(text_value)
        return int.from_bytes(value, byteorder=BYTE_ORDER_BIG_ENDIAN)
    return int(value)


def _coerce_db_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, bytes):
        normalized_bytes = value.strip()
        if normalized_bytes in BOOLEAN_TRUE_BYTES_VALUES:
            return True
        if normalized_bytes in BOOLEAN_FALSE_BYTES_VALUES:
            return False
        decoded_value = _decode_db_text(normalized_bytes)
        normalized_text = decoded_value.strip().lower() if decoded_value is not None else ""
        if normalized_text in BOOLEAN_TRUE_TEXT_VALUES:
            return True
        if normalized_text in BOOLEAN_FALSE_TEXT_VALUES:
            return False
        return int.from_bytes(normalized_bytes, byteorder=BYTE_ORDER_BIG_ENDIAN) != 0
    if isinstance(value, str):
        normalized_text = value.strip().lower()
        if normalized_text in BOOLEAN_TRUE_TEXT_VALUES:
            return True
        if normalized_text in BOOLEAN_FALSE_TEXT_VALUES:
            return False
    if isinstance(value, int):
        return value != 0
    return bool(value)


# ==================== 专家 Schemas ====================


class ModerateDeleteRequest(BaseModel):
    """平台超管违规删除问题/回答/评论；可选按 R* 扣分。"""

    target_type: str = Field(..., description="question | answer | comment")
    target_id: int = Field(..., ge=1)
    # 空/省略 = 只删除不扣分
    rule_code: str | None = Field(default=None, max_length=32)
    remark: str | None = Field(default=None, max_length=200)

    @field_validator("target_type")
    @classmethod
    def _validate_target_type(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"question", "answer", "comment"}:
            raise ValueError("target_type must be question, answer or comment")
        return normalized

    @field_validator("rule_code")
    @classmethod
    def _normalize_rule_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None


class ExpertCreateRequest(BaseModel):
    """创建专家 - 请求"""

    expert_name: str = Field(..., description="专家名称")
    introduction: str | None = Field(None, description="专家介绍")
    depart_ment: str | None = Field(default=[], description="所属部门")
    user_id: int | None = Field(None, description="关联用户ID（可选）")
    major: str | None = Field(None, description="所属专业")
    position: str | None = Field(None, description="所属岗位")
    job_family: str | None = Field(None, description="所属岗位族")
    job_category: str | None = Field(None, description="所属岗位分类")
    wechat_user_id: str | None =  Field(None, description="绑定企业微信用户id")


class ExpertUpdateRequest(BaseModel):
    """更新专家 - 请求"""

    expert_name: str | None = None
    introduction: str | None = None
    depart_ment: str | None = None
    major: str | None = Field(None, description="所属专业")
    position: str | None = Field(None, description="所属岗位")
    job_family: str | None = Field(None, description="所属岗位族")
    job_category: str | None = Field(None, description="所属岗位分类")
    wechat_user_id: str | None =  Field(None, description="绑定企业微信用户id")


class ExpertResponse(BaseModel):
    """专家 - 响应"""

    id: int
    user_id: int
    expert_name: str
    introduction: str | None
    depart_ment: str | None = None
    department_id: int | str | None = None
    position: str | None = None
    job_family: str | None = None
    job_category: str | None = None
    major: str | None = None
    level: str
    business_domains: list[str]
    verified: bool
    answer_count: int
    adoption_count: int
    vote_count: int = 0
    expert_score: int = 0
    helpful_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== 问题 Schemas ====================
class QuestionCheckRequest(BaseModel):
    """检查问题 - 请求"""

    check_text: str = Field(..., min_length=0, max_length=10000, description="问题文本")


class QuestionCreateRequest(BaseModel):
    """发起提问 - 请求"""

    title: str = Field(..., min_length=0, max_length=100, description="问题标题")
    description: str = Field(..., min_length=0, description="问题描述")
    business_domain: str = Field(..., description="所属业务域")

    attachments: str | None = Field(default=None, description="附件列表")
    related_docs: str | None = Field(default=None, description="关联文档ID")

    invited_experts: str | None = Field(default=None, description="邀请专家ID，多个用分号;分割")
    experts_names: str | None = Field(default=None, description="邀请专家名称，多个用分号;分割")

    image_url: str | None = Field(default=None, max_length=1024, schema_extra={"comment": "图片URL"})
    file_url: str | None = Field(default=None, max_length=1024, schema_extra={"comment": "文件URL"})
    file_name: str | None = Field(default=None, max_length=512, schema_extra={"comment": "文件名"})

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, value: str) -> str:
        return sanitize_question_description(value)

    @field_validator("invited_experts", mode="before")
    @classmethod
    def validate_experts(cls, v):
        if v is None or str(v).strip() == "":
            return None
        if not isinstance(v, str):
            raise ValueError("invited_experts 必须是字符串格式")
        expert_ids = [id_str.strip() for id_str in v.split(";") if id_str.strip()]
        if len(expert_ids) > 10:
            raise ValueError("最多只能邀请 10 位专家")

        if not all(item.isdigit() for item in expert_ids):
            raise ValueError("专家ID必须为纯数字")
        return v


class QuestionUpdateRequest(BaseModel):
    """更新问题 - 请求"""

    title: str | None = None
    description: str | None = None
    business_domain: str | None = None
    attachments: str | None = Field(default=None, description="附件列表")
    related_docs: str | None = Field(default=None, description="关联文档ID")
    invited_experts: str | None = Field(default=None, description="邀请专家ID，多个用分号;分割")
    experts_names: str | None = Field(default=None, description="邀请专家名称，多个用分号;分割")
    image_url: str | None = Field(default=None, max_length=1024, description="图片URL")
    file_url: str | None = Field(default=None, max_length=1024, description="文件URL")
    file_name: str | None = Field(default=None, max_length=512, description="文件名")
    status: int | str | None = Field(default=None, description="状态: unsolved/solved/closed/pending")
    created_by: str | None = Field(default=None, description="创建人")

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, value: str | None) -> str | None:
        return sanitize_question_description(value) if value is not None else None

    @field_validator("invited_experts", mode="before")
    @classmethod
    def validate_experts(cls, v):
        if v is None or str(v).strip() == "":
            return None
        if not isinstance(v, str):
            raise ValueError("invited_experts 必须是字符串格式")
        expert_ids = [id_str.strip() for id_str in v.split(";") if id_str.strip()]
        if len(expert_ids) > 10:
            raise ValueError("最多只能邀请 10 位专家")
        if not all(item.isdigit() for item in expert_ids):
            raise ValueError("专家ID必须为纯数字")
        return v

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v):
        if v is None:
            return None
        mapping = {
            "unsolved": 0,
            "solved": 1,
            "closed": 2,
            "pending": 3,
        }
        if isinstance(v, int):
            if v not in mapping.values():
                raise ValueError("status 必须是 0/1/2/3")
            return v
        if isinstance(v, str):
            if v not in mapping:
                raise ValueError("status 必须是 unsolved/solved/closed/pending")
            return mapping[v]
        raise ValueError("status 类型错误")


class QuestionSimpleResponse(BaseModel):
    """问题简略信息 - 响应"""

    id: int
    title: str
    business_domain: str
    status: str
    vote_count: int
    answer_count: int
    view_count: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class QuestionDetailResponse(BaseModel):
    """问题详情 - 响应"""

    id: int
    title: str
    description: str
    business_domain: str
    status: str
    user_id: int
    anonymous: bool
    attachments: str | None = Field(default=None, description="分号分隔的附件URL或业务ID")
    related_docs: str | None = None
    invited_experts: str | None = None
    experts_names: str | None = Field(default=None, description="邀请专家名称，多个用分号;分割")
    adopted_answer_id: int | None
    image_url: str | None = Field(default=None, description="图片URL")
    file_url: str | None = Field(default=None, description="文件URL")
    file_name: str | None = Field(default=None, description="文件名")
    vote_count: int
    answer_count: int
    view_count: int
    created_at: datetime
    updated_at: datetime

    # 展开的关系数据（可选）
    answers: list["AnswerDetailResponse"] | None = None
    expert_status: dict | None = None  # 专家回复状态

    class Config:
        from_attributes = True


# ==================== 回答 Schemas ====================


class AnswerCreateRequest(BaseModel):
    """发布回答 - 请求"""

    question_id: int = Field(..., description="问题ID")
    content: str = Field(..., min_length=1, description="回答内容")
    attachments: str | None = Field(default=None, description="附件列表")
    related_docs: str | None = Field(default=None, description="关联文档ID")
    images_url: str | None = Field(default=None, description="图片URL")


class AnswerUpdateRequest(BaseModel):
    """更新回答 - 请求"""

    content: str | None = None
    attachments: str | None = Field(default=None, description="分号分隔的附件URL或业务ID")
    related_docs: str | None = None
    images_url: str | None = Field(default=None, description="分号分隔的图片URL")


class AnswerDetailResponse(BaseModel):
    """回答详情 - 响应"""

    id: int
    question_id: int
    user_id: int
    expert_id: int | None
    content: str
    status: str
    attachments: str | None = Field(default=None, description="分号分隔的附件URL或业务ID")
    related_docs: str | None = None
    images_url: str | None = Field(default=None, description="分号分隔的图片URL")
    vote_count: int
    comment_count: int
    created_at: datetime
    updated_at: datetime

    # 专家信息（如果是专家回答）
    expert_info: ExpertResponse | None = None

    # 评论列表（可选）
    comments: list["CommentDetailResponse"] | None = None

    class Config:
        from_attributes = True


# ==================== 评论/追问 Schemas ====================


class CommentCreateRequest(BaseModel):
    """发布评论/追问 - 请求"""

    answer_id: int = Field(..., description="回答ID")
    content: str = Field(..., description="评论内容")
    is_follow_up: bool = Field(default=False, description="是否为追问")
    question_id: int | None = Field(None, description="问题ID（仅追问时需要）")


class GetCommentsRequest(BaseModel):
    """获取评论/追问 - 请求"""

    answer_id: int = Field(..., ge=0, description="Answer ID. Use 0 to query question follow-ups.")
    question_id: int | None = Field(None, ge=0, description="Required when answer_id is 0.")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_comment_target(self):
        """Require question_id when querying follow-up comments by question."""
        if self.answer_id == 0 and self.question_id is None:
            raise ValueError("question_id is required when answer_id is 0")
        return self


class CommentDetailResponse(BaseModel):
    """评论详情 - 响应"""

    id: int
    answer_id: int
    question_id: int
    user_id: int
    user_name: str | None = None
    content: str
    is_follow_up: bool
    vote_count: int
    created_at: datetime

    @classmethod
    def from_comment(cls, comment: Any) -> "CommentDetailResponse":
        """Build a JSON-safe response DTO from a database comment entity."""
        return cls(
            id=_coerce_db_int(getattr(comment, "id", None)),
            answer_id=_coerce_db_int(getattr(comment, "answer_id", None)),
            question_id=_coerce_db_int(getattr(comment, "question_id", None)),
            user_id=_coerce_db_int(getattr(comment, "user_id", None)),
            user_name=_decode_db_text(getattr(comment, "user_name", None)),
            content=_decode_db_text(getattr(comment, "content", None)) or "",
            is_follow_up=_coerce_db_bool(getattr(comment, "is_follow_up", False)),
            vote_count=_coerce_db_int(getattr(comment, "vote_count", None)),
            created_at=comment.created_at,
        )

    class Config:
        from_attributes = True


class CommentPageData(BaseModel):
    """Comment list page response."""

    comments: list[CommentDetailResponse]
    total: int


# ==================== 投票 Schemas ====================


class VoteRequest(BaseModel):
    """投票 - 请求"""

    target_type: str = Field(..., description="目标类型: question/answer/comment")
    target_id: int = Field(..., description="目标ID")


# ==================== 采纳 Schemas ====================


class AdoptAnswerRequest(BaseModel):
    """采纳回答 - 请求"""

    answer_id: int = Field(..., description="回答ID")


# ==================== 通知 Schemas ====================


class QANotificationResponse(BaseModel):
    """通知 - 响应"""

    id: int
    notification_type: str
    content: str
    read: bool
    question_id: int
    sender_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== 问题列表查询 ====================


class QuestionListQuery(BaseModel):
    """问题列表查询条件"""

    domain: str | None = Field(None, description="业务域")
    status: int | None = Field(0, description="状态: unsolved/solved/closed")
    sort_by: str = Field(default="latest", description="排序: latest/hottest/unanswered")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    my_questions: bool = Field(default=False, description="仅显示我提问的")
    invitations: bool = Field(default=False, description="仅显示邀请我的")


# ==================== 专家列表查询 ====================


class ExpertListQuery(BaseModel):
    """专家列表查询条件"""

    business_domain: str | None = None
    level: str | None = None
    keyword: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


# ==================== 统计信息 ====================


class QuestionStatsResponse(BaseModel):
    """问题统计"""

    total_questions: int
    unsolved_count: int
    solved_count: int
    closed_count: int


class ExpertStatsResponse(BaseModel):
    """专家统计"""

    total_experts: int
    verified_experts: int
    total_answers: int
    total_adoptions: int


class QAExpertStatsResponse(BaseModel):
    """Expert QA overview statistics."""

    total_questions: int = Field(..., description="问题总数")
    total_experts: int = Field(..., description="专家总数")
    total_answers: int = Field(..., description="回答总数")
    solved_questions: int = Field(..., description="已解决问题数")
    resolution_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="解决率，已解决问题数 / 问题总数",
    )


# ==================== 页面数据 ====================


class QuestionPageData(BaseModel):
    """问题列表页面数据"""

    questions: list[QuestionSimpleResponse]
    total: int
    business_domains: list[str]  # 所有业务域
    stats: QuestionStatsResponse
