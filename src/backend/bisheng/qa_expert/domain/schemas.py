"""
Expert QA Pydantic Schemas - 请求/响应数据模型
"""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

TEXT_ENCODING = "utf-8"
TEXT_DECODE_ERRORS = "replace"
BYTE_ORDER_BIG_ENDIAN = "big"
BOOLEAN_TRUE_TEXT_VALUES = {"1", "true", "t", "yes", "y", "on"}
BOOLEAN_FALSE_TEXT_VALUES = {"0", "false", "f", "no", "n", "off", ""}
BOOLEAN_TRUE_BYTES_VALUES = {b"\x01", b"1"}
BOOLEAN_FALSE_BYTES_VALUES = {b"\x00", b"", b"0"}


def _decode_db_text(value: Any) -> Optional[str]:
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


class ExpertCreateRequest(BaseModel):
    """创建专家 - 请求"""

    expert_name: str = Field(..., description="专家名称")
    introduction: Optional[str] = Field(None, description="专家介绍")
    depart_ment: Optional[str] = Field(default=[], description="所属业务域")
    user_id: Optional[int] = Field(None, description="关联用户ID（可选）")


class ExpertUpdateRequest(BaseModel):
    """更新专家 - 请求"""

    expert_name: Optional[str] = None
    introduction: Optional[str] = None
    depart_ment: Optional[str] = None


class ExpertResponse(BaseModel):
    """专家 - 响应"""

    id: int
    user_id: int
    expert_name: str
    introduction: Optional[str]
    level: str
    business_domains: List[str]
    verified: bool
    answer_count: int
    adoption_count: int
    helpful_count: int
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== 问题 Schemas ====================


class QuestionCreateRequest(BaseModel):
    """发起提问 - 请求"""

    title: str = Field(..., min_length=0, max_length=100, description="问题标题")
    description: str = Field(..., min_length=0, description="问题描述")
    business_domain: str = Field(..., description="所属业务域")

    attachments: Optional[str] = Field(default=None, description="附件列表")
    related_docs: Optional[str] = Field(default=None, description="关联文档ID")

    invited_experts: Optional[str] = Field(default=None, description="邀请专家ID，多个用分号;分割")
    experts_names: Optional[str] = Field(default=None, description="邀请专家名称，多个用分号;分割")

    image_url: Optional[str] = Field(default=None, max_length=1024, schema_extra={"comment": "图片URL"})

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

    title: Optional[str] = None
    description: Optional[str] = None
    business_domain: Optional[str] = None
    attachments: Optional[List[str]] = None
    related_docs: Optional[List[int]] = None
    invited_experts: Optional[List[int]] = None

    @field_validator("invited_experts")
    @classmethod
    def validate_experts(cls, v):
        if v and len(v) > 3:
            raise ValueError("最多只能邀请 3 位专家")
        return v


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
    attachments: List[str]
    related_docs: List[int]
    invited_experts: List[int]
    adopted_answer_id: Optional[int]
    vote_count: int
    answer_count: int
    view_count: int
    created_at: datetime
    updated_at: datetime

    # 展开的关系数据（可选）
    answers: Optional[List["AnswerDetailResponse"]] = None
    expert_status: Optional[dict] = None  # 专家回复状态

    class Config:
        from_attributes = True


# ==================== 回答 Schemas ====================


class AnswerCreateRequest(BaseModel):
    """发布回答 - 请求"""

    question_id: int = Field(..., description="问题ID")
    content: str = Field(..., min_length=1, description="回答内容")
    attachments: Optional[str] = Field(default=None, description="附件列表")
    related_docs: Optional[str] = Field(default=None, description="关联文档ID")
    images_url: Optional[str] = Field(default=None, description="图片URL")


class AnswerUpdateRequest(BaseModel):
    """更新回答 - 请求"""

    content: Optional[str] = None
    attachments: Optional[List[str]] = None
    related_docs: Optional[List[int]] = None


class AnswerDetailResponse(BaseModel):
    """回答详情 - 响应"""

    id: int
    question_id: int
    user_id: int
    expert_id: Optional[int]
    content: str
    status: str
    attachments: List[str]
    related_docs: List[int]
    vote_count: int
    comment_count: int
    created_at: datetime
    updated_at: datetime

    # 专家信息（如果是专家回答）
    expert_info: Optional[ExpertResponse] = None

    # 评论列表（可选）
    comments: Optional[List["CommentDetailResponse"]] = None

    class Config:
        from_attributes = True


# ==================== 评论/追问 Schemas ====================


class CommentCreateRequest(BaseModel):
    """发布评论/追问 - 请求"""

    answer_id: int = Field(..., description="回答ID")
    content: str = Field(..., description="评论内容")
    is_follow_up: bool = Field(default=False, description="是否为追问")
    question_id: Optional[int] = Field(None, description="问题ID（仅追问时需要）")


class GetCommentsRequest(BaseModel):
    """获取评论/追问 - 请求"""

    answer_id: int = Field(..., ge=0, description="Answer ID. Use 0 to query question follow-ups.")
    question_id: Optional[int] = Field(None, ge=0, description="Required when answer_id is 0.")
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
    user_name: Optional[str] = None
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

    comments: List[CommentDetailResponse]
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

    domain: Optional[str] = Field(None, description="业务域")
    status: Optional[str] = Field(None, description="状态: unsolved/solved/closed")
    sort_by: str = Field(default="latest", description="排序: latest/hottest/unanswered")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    my_questions: bool = Field(default=False, description="仅显示我提问的")
    invitations: bool = Field(default=False, description="仅显示邀请我的")


# ==================== 专家列表查询 ====================


class ExpertListQuery(BaseModel):
    """专家列表查询条件"""

    business_domain: Optional[str] = None
    level: Optional[str] = None
    keyword: Optional[str] = None
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

    questions: List[QuestionSimpleResponse]
    total: int
    business_domains: List[str]  # 所有业务域
    stats: QuestionStatsResponse
