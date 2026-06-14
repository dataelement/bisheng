"""
Expert QA Pydantic Schemas - 请求/响应数据模型
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


# ==================== 专家 Schemas ====================

class ExpertCreateRequest(BaseModel):
    """创建专家 - 请求"""
    user_id: int = Field(..., description="用户ID")
    expert_name: str = Field(..., description="专家名称")
    introduction: Optional[str] = Field(None, description="专家介绍")
    level: str = Field(default="junior", description="专家等级: senior/intermediate/junior")
    business_domains: List[str] = Field(default=[], description="所属业务域")


class ExpertUpdateRequest(BaseModel):
    """更新专家 - 请求"""
    expert_name: Optional[str] = None
    introduction: Optional[str] = None
    level: Optional[str] = None
    business_domains: Optional[List[str]] = None


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
    title: str = Field(..., min_length=10, max_length=100, description="问题标题")
    description: str = Field(..., min_length=20, description="问题描述")
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
    related_docs:Optional[str] = Field(default=None, description="关联文档ID")
    image_url:Optional[str] = Field(default=None, description="图片URL")

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
    content: str = Field(...,  description="评论内容")
    is_follow_up: bool = Field(default=False, description="是否为追问")


class CommentDetailResponse(BaseModel):
    """评论详情 - 响应"""
    id: int
    answer_id: int
    user_id: int
    content: str
    is_follow_up: bool
    vote_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


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
    business_domain: Optional[str] = Field(None, description="业务域")
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


# ==================== 问题草稿 ====================

class DraftCreateRequest(BaseModel):
    """保存草稿 - 请求"""
    title: Optional[str] = None
    description: Optional[str] = None
    business_domain: Optional[str] = None
    attachments: List[str] = Field(default=[])
    related_docs: List[int] = Field(default=[])
    invited_experts: List[int] = Field(default=[])
    anonymous: bool = Field(default=False)


class DraftResponse(BaseModel):
    """草稿 - 响应"""
    id: int
    title: Optional[str]
    description: Optional[str]
    business_domain: Optional[str]
    attachments: List[str]
    related_docs: List[int]
    invited_experts: List[int]
    anonymous: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ==================== 页面数据 ====================

class QuestionPageData(BaseModel):
    """问题列表页面数据"""
    questions: List[QuestionSimpleResponse]
    total: int
    business_domains: List[str]  # 所有业务域
    stats: QuestionStatsResponse
