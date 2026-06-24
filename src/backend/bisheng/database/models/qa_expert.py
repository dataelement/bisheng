"""
Expert QA Database Models - SQLModel ORM

遵循 BiSheng 的 SQLModel + SQLAlchemy 2.0 规范
"""

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, Column, String
from bisheng.core.database.dialect_helpers import JsonType

if TYPE_CHECKING:
    from bisheng.database.models.user_link import User


# ==================== 专家表 ====================

class Expert(SQLModel, table=True):
    """专家表"""
    __tablename__ = "qa_expert"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    expert_name: str = Field(index=True)
    introduction: Optional[str] = None
    depart_ment: Optional[str] = Field(
        default=None,
        description="所属部门，JSON 格式"
    )
    major: Optional[str] = Field(
        default=None,
        description="所属专业"
    )
    
    # 统计字段
    answer_count: int = Field(default=0)
    adoption_count: int = Field(default=0)
    vote_count: int = Field(default=0)
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    



# ==================== 问题表 ====================

class Question(SQLModel, table=True):
    """问题表"""
    __tablename__ = "qa_question"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    title: str = Field(index=True)
    description: str
    business_domain: str = Field(index=True)
    status: int = Field(default=0, index=True)  # 0: 未解决, 1: 已解决, 2: 已关闭
    attachments: Optional[str] = Field(default=None, description="附件列表")
    related_docs: Optional[str] = Field(default=None, description="关联文档 ID 列表")
    invited_experts: Optional[str] = Field(default=None, description="被邀请的专家 ID 列表")
    
    experts_names: Optional[str] = Field(default=None, description="邀请专家名称，多个用分号;分割")
    image_url: Optional[str] = Field(default=None, max_length=1024, schema_extra={"comment": "图片URL"})

    # 采纳的最佳回答
    adopted_answer_id: Optional[int] = None
    # 统计字段
    vote_count: int = Field(default=0)
    answer_count: int = Field(default=0, index=True)
    view_count: int = Field(default=0)
    comment_count: int = Field(default=0)
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = Field(default=None, description="创建人")
    
 



# ==================== 回答表 ====================

class Answer(SQLModel, table=True):
    """回答表"""
    __tablename__ = "qa_answer"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(index=True)
    expert_id: Optional[int] = Field(default=None, index=True)
    expert_name: Optional[str] = Field(default=None, description="回答者名称（专家可选）")
    content: str
    status: int = Field(default=1, index=True)  # 1: normal, 2: adopted, 3: deleted
    # 附件和关联文档
    attachments: Optional[str] = Field(
        default=None,
        description="附件列表"
    )
    related_docs: Optional[str] = Field(
        default=None,
    
        description="关联文档 ID 列表"
    )
    images_url: Optional[str] = Field(
        default=None,
       
        description="图片URL列表"
    )
    # 统计字段
    vote_count: int = Field(default=0)
    comment_count: int = Field(default=0)
    adopted: Optional[bool] = Field(default=False, index=True)  # 是否被采纳  
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
  



# ==================== 评论/追问表 ====================

class Comment(SQLModel, table=True):
    """评论/追问表"""
    __tablename__ = "qa_comment"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    answer_id: int = Field(index=True)
    question_id: int = Field(index=True)
    user_id: int = Field(index=True)
    user_name: Optional[str] = Field(default=None, description="评论者名称")
    content: str
    is_follow_up: bool = Field(default=False)  # True 为追问，False 为评论
    # 统计字段
    vote_count: int = Field(default=0)
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    

# ==================== 投票表 ====================

class QuestionVote(SQLModel, table=True):
    """问题投票（赞）记录"""
    __tablename__ = "qa_question_vote"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    question_id: int = Field(index=True)
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    



class AnswerVote(SQLModel, table=True):
    """回答投票（赞/有用）记录"""
    __tablename__ = "qa_answer_vote"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    answer_id: int = Field(index=True)
    vote_type: str = Field(default="helpful")  # helpful 有用，support 支持
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    



class CommentVote(SQLModel, table=True):
    """评论投票（赞）记录"""
    __tablename__ = "qa_comment_vote"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    comment_id: int = Field(index=True)
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    



# ==================== 通知表 ====================

class QANotification(SQLModel, table=True):
    """专家问答站内消息"""
    __tablename__ = "qa_notification"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    recipient_id: int = Field(index=True)
    sender_id: int = Field(index=True)
    notification_type: str = Field(index=True)  # invited, answered, commented, adopted
    question_id: int = Field(index=True)
    answer_id: Optional[int] = Field(default=None)
    content: str
    read: bool = Field(default=False, index=True)
    
    # 多租户字段
    tenant_id: int = Field(default=1, index=True)
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    

