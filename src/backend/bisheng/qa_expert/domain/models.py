"""
Expert QA Domain Models - 专家问答领域模型

遵循 DDD 规范，定义专家问答系统的核心业务模型
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List


class QuestionStatus(str, Enum):
    """问题状态"""
    UNSOLVED = "unsolved"          # 未解决
    SOLVED = "solved"              # 已解决
    CLOSED = "closed"              # 已关闭


class AnswerStatus(str, Enum):
    """回答状态"""
    NORMAL = "normal"              # 正常
    ADOPTED = "adopted"            # 已采纳
    DELETED = "deleted"            # 已删除


class NotificationType(str, Enum):
    """消息类型"""
    INVITED = "invited"            # 被邀请回答
    ANSWERED = "answered"          # 问题被回答
    COMMENTED = "commented"        # 回答被评论
    ADOPTED = "adopted"            # 回答被采纳


class ExpertLevel(str, Enum):
    """专家等级"""
    SENIOR = "senior"              # 高级专家
    INTERMEDIATE = "intermediate"  # 中级专家
    JUNIOR = "junior"              # 初级专家


# ==================== 专家领域对象 ====================

class Expert:
    """专家聚合根"""
    
    def __init__(
        self,
        user_id: int,
        expert_name: str,
        introduction: Optional[str] = None,
        level: ExpertLevel = ExpertLevel.JUNIOR,
        business_domains: Optional[List[str]] = None,
        verified: bool = False
    ):
        self.user_id = user_id
        self.expert_name = expert_name
        self.introduction = introduction
        self.level = level
        self.business_domains = business_domains or []
        self.verified = verified
        self.answer_count = 0
        self.adoption_count = 0
        self.helpful_count = 0
        self.created_at = datetime.utcnow()
    
    def update_stats(self, answers: int = 0, adoptions: int = 0, helpful: int = 0):
        """更新专家统计数据"""
        self.answer_count += answers
        self.adoption_count += adoptions
        self.helpful_count += helpful


# ==================== 问题领域对象 ====================

class Question:
    """问题聚合根"""
    
    def __init__(
        self,
        user_id: int,
        title: str,
        description: str,
        business_domain: str,
        attachments: Optional[List[str]] = None,
        related_docs: Optional[List[int]] = None,
        invited_experts: Optional[List[int]] = None,
        anonymous: bool = False
    ):
        self.user_id = user_id
        self.title = title
        self.description = description
        self.business_domain = business_domain
        self.status = QuestionStatus.UNSOLVED
        self.attachments = attachments or []
        self.related_docs = related_docs or []
        self.invited_experts = invited_experts or []
        self.anonymous = anonymous
        
        # 统计字段
        self.vote_count = 0
        self.answer_count = 0
        self.view_count = 0
        self.adopted_answer_id: Optional[int] = None
        
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def invite_expert(self, expert_id: int):
        """邀请专家"""
        if len(self.invited_experts) >= 3:
            raise ValueError("最多只能邀请 3 位专家")
        if expert_id not in self.invited_experts:
            self.invited_experts.append(expert_id)
    
    def adopt_answer(self, answer_id: int):
        """采纳最佳回答"""
        if self.status == QuestionStatus.SOLVED:
            raise ValueError("问题已有最佳回答，不能重复采纳")
        self.adopted_answer_id = answer_id
        self.status = QuestionStatus.SOLVED
        self.updated_at = datetime.utcnow()
    
    def add_vote(self):
        """增加赞数"""
        self.vote_count += 1
    
    def increment_view_count(self):
        """增加浏览数"""
        self.view_count += 1


# ==================== 回答领域对象 ====================

class Answer:
    """回答聚合根"""
    
    def __init__(
        self,
        question_id: int,
        user_id: int,
        content: str,
        attachments: Optional[List[str]] = None,
        related_docs: Optional[List[int]] = None
    ):
        self.question_id = question_id
        self.user_id = user_id
        self.content = content
        self.attachments = attachments or []
        self.related_docs = related_docs or []
        self.status = AnswerStatus.NORMAL
        
        # 统计字段
        self.vote_count = 0
        self.comment_count = 0
        
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def adopt(self):
        """采纳此回答"""
        self.status = AnswerStatus.ADOPTED
        self.updated_at = datetime.utcnow()
    
    def add_vote(self):
        """增加有用数"""
        self.vote_count += 1
    
    def delete(self):
        """删除回答"""
        self.status = AnswerStatus.DELETED


# ==================== 评论/追问领域对象 ====================

class Comment:
    """评论/追问聚合根"""
    
    def __init__(
        self,
        answer_id: int,
        user_id: int,
        content: str,
        is_follow_up: bool = False
    ):
        self.answer_id = answer_id
        self.user_id = user_id
        self.content = content
        self.is_follow_up = is_follow_up  # True 为追问，False 为评论
        self.vote_count = 0
        self.created_at = datetime.utcnow()
    
    def add_vote(self):
        """增加赞数"""
        self.vote_count += 1


# ==================== 投票领域对象 ====================

class Vote:
    """投票（赞）记录"""
    
    def __init__(
        self,
        user_id: int,
        target_type: str,  # "question", "answer", "comment"
        target_id: int
    ):
        self.user_id = user_id
        self.target_type = target_type
        self.target_id = target_id
        self.created_at = datetime.utcnow()


# ==================== 通知领域对象 ====================

class Notification:
    """站内消息通知"""
    
    def __init__(
        self,
        recipient_id: int,
        sender_id: int,
        notification_type: NotificationType,
        related_question_id: int,
        content: str
    ):
        self.recipient_id = recipient_id
        self.sender_id = sender_id
        self.notification_type = notification_type
        self.related_question_id = related_question_id
        self.content = content
        self.read = False
        self.created_at = datetime.utcnow()
    
    def mark_as_read(self):
        """标记为已读"""
        self.read = True
