"""
Expert QA Services - 业务逻辑层
核心流程：
- 专家管理：指定、更新、删除
- 提问流程：创建、邀请、发布
- 回答流程：发布、采纳
- 互动流程：评论、投票、通知
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from bisheng.database.models.qa_expert import (
    Expert,
    Question,
    Answer,
    Comment,
    QANotification
)
from bisheng.qa_expert.domain.schemas import (
    ExpertCreateRequest,
    ExpertUpdateRequest,
    QuestionCreateRequest,
    AnswerCreateRequest,
    CommentCreateRequest,
    AdoptAnswerRequest
)
from bisheng.qa_expert.domain.repositories import (
    ExpertRepository,
    QuestionRepository,
    AnswerRepository,
    CommentRepository,
    VoteRepository,
    NotificationRepository,
    DraftRepository
)
from bisheng.common.errcode.base import BaseErrorCode


# ==================== 错误定义 ====================
class ExpertNotFoundError(BaseErrorCode):
    """专家不存在"""
    Code = 10901
    Msg = "Expert not found"

class QuestionNotFoundError(BaseErrorCode):
    """问题不存在"""
    Code = 10902
    Msg = "Question not found"

class AnswerNotFoundError(BaseErrorCode):
    """回答不存在"""
    Code = 10903
    Msg = "Answer not found"

class InvalidInvitationError(BaseErrorCode):
    """无效的邀请"""
    Code = 10904
    Msg = "Invalid expert invitation"

class PermissionDeniedError(BaseErrorCode):
    """权限不足"""
    Code = 10905
    Msg = "Permission denied"


# ==================== 专家服务 ====================
class ExpertService:
    """专家业务逻辑"""
    def __init__(self):
        self.repository = ExpertRepository()

    async def create_expert(
        self,
        request: ExpertCreateRequest
    ) -> Expert:
        """创建专家（后台管理员操作）"""
        # 检查是否已是专家
        existing = await self.repository.get_by_user_name(request.expert_name)
        if existing:
            raise InvalidInvitationError(message=f"Expert {request.expert_name} is already exists")
        
        expert = Expert(
            expert_name=request.expert_name,
            introduction=request.introduction,
            depart_ment=request.depart_ment,
            user_id=request.user_id
        )
        return await self.repository.create(expert)

    async def update_expert(
        self,
        expert_id: int,
        request: ExpertUpdateRequest
    ) -> Expert:
        """更新专家信息"""
        expert = await self.repository.get_by_id(expert_id)
        if not expert:
            raise ExpertNotFoundError()
        
        update_data = request.dict(exclude_unset=True)
        return await self.repository.update(expert_id, **update_data)

    async def list_experts(
        self,
        keyword: Optional[str] = None,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[List[Expert], int]:
        """列表查询专家"""
        return await self.repository.list_all(
            keyword=keyword,
            skip=skip,
            limit=limit
        )

    async def delete_expert(self, expert_id: int) -> bool:
        """删除专家"""
        return await self.repository.delete(expert_id)


# ==================== 问题服务 ====================
class QuestionService:
    """问题业务逻辑"""
    def __init__(self):
        self.repository = QuestionRepository()
        self.expert_repo = ExpertRepository()
        self.answer_repo = AnswerRepository()
        self.notification_repo = NotificationRepository()

    async def create_question(
        self,
        user_id: int,
        request: QuestionCreateRequest,
        user_name: str
    ) -> Question:
        """创建问题"""
        question = Question(
            user_id=user_id,
            title=request.title,
            description=request.description,
            business_domain=request.business_domain,
            attachments=request.attachments,
            related_docs=request.related_docs,
            invited_experts=request.invited_experts,
            experts_names=request.experts_names,
            image_url=request.image_url,
            created_by=user_name
        )
        
        question = await self.repository.create(question)
        
        # 发送邀请通知
        # await self._send_invitation_notifications(
        #     question.id,
        #     user_id,
        #     request.invited_experts,
        # )
        
        logger.info(f"Question created: {question.id} by user {user_id}")
        return question

    async def list_questions(
        self,
        business_domain: Optional[str] = None,
        status: Optional[str] = None,
        sort_by: str = "latest",
        user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[List[Question], int]:
        """列表查询问题"""
        return await self.repository.list_all(
            business_domain=business_domain,
            status=status,
            sort_by=sort_by,
            user_id=user_id,
            skip=skip,
            limit=limit
        )

    async def get_question_detail(
        self,
        question_id: int,
        user_id: Optional[int] = None
    ) -> Question:
        """获取问题详情"""
        question = await self.repository.get_by_id(question_id)
        if not question:
            raise QuestionNotFoundError()
        
        # 增加浏览数
        question.view_count += 1
        await self.repository.update(question_id, view_count=question.view_count)
        return question

    async def adopt_answer(
        self,
        question_id: int,
        answer_id: int,
        operator_id: int
    ) -> Question:
        """采纳最佳回答"""
        question = await self.repository.get_by_id(question_id)
        if not question:
            raise QuestionNotFoundError()
        
        # 只有提问者可以采纳
        if question.user_id != operator_id:
            raise PermissionDeniedError(message="Only question author can adopt answer")
        
        answer = await self.answer_repo.get_by_id(answer_id)
        if not answer:
            raise AnswerNotFoundError()
        
        if answer.question_id != question_id:
            raise InvalidInvitationError(message="Answer does not belong to this question")
        
        # 更新问题状态
        question.adopted_answer_id = answer_id
        question.status = "solved"
        await self.repository.update(question_id, adopted_answer_id=answer_id, status="solved")
        
        # 更新回答状态
        answer.status = "adopted"
        await self.answer_repo.update(answer_id, status="adopted")
        
        # 发送采纳通知
        await self._send_adoption_notification(
            question.id,
            question.user_id,
            answer.user_id,
        )
        
        logger.info(f"Answer {answer_id} adopted for question {question_id}")
        return question

    async def get_business_domains(self) -> List[str]:
        """获取所有业务域"""
        # 修复了原代码中的错误引用 (self -> self.repository)
        return await self.repository.get_business_domains()

    async def get_stats(self) -> dict:
        """获取问题统计"""
        return await self.repository.get_stats()

    async def _send_invitation_notifications(
        self,
        question_id: int,
        sender_id: int,
        expert_ids: List[int],
    ):
        """发送邀请通知给专家"""
        for expert_id in expert_ids:
            notification = QANotification(
                recipient_id=expert_id,
                sender_id=sender_id,
                notification_type="invited",
                question_id=question_id,
                content=f"You are invited to answer a question",
                # tenant_id=tenant_id
            )
            await self.notification_repo.create(notification)

    async def _send_adoption_notification(
        self,
        question_id: int,
        questioner_id: int,
        answerer_id: int,
    ):
        """发送采纳通知"""
        notification = QANotification(
            recipient_id=answerer_id,
            sender_id=questioner_id,
            notification_type="adopted",
            question_id=question_id,
            content="Your answer was adopted as the best answer",
            # tenant_id=tenant_id
        )
        await self.notification_repo.create(notification)


# ==================== 回答服务 ====================
class AnswerService:
    """回答业务逻辑"""
    def __init__(self):
        self.repository = AnswerRepository()
        self.question_repo = QuestionRepository()
        self.expert_repo = ExpertRepository()
        self.notification_repo = NotificationRepository()


    async def create_answer(
        self,
        user_id: int,
        request: AnswerCreateRequest,
    ) -> Answer:
        """发布回答"""
        question = await self.question_repo.get_by_id(request.question_id)
        if not question:
            raise QuestionNotFoundError()
        
        # 检查是否为专家
        expert = await self.expert_repo.get_by_user_id(user_id)
        if not expert:
            raise ExpertNotFoundError(message="Only verified experts can answer questions")
    
        answer = Answer(
            question_id=request.question_id,
            expert_id=expert.id, 
            content=request.content,
            attachments=request.attachments,
            related_docs=request.related_docs,
            image_url=request.image_url,
            expert_name=expert.expert_name
        )
        
        answer = await self.repository.create(answer)
        
        # 更新问题的回答计数
        question.answer_count += 1
        await self.question_repo.update(request.question_id, answer_count=question.answer_count)
        
        
        await self.expert_repo.increment_answer_count(expert.id, count=1)
        
        # 发送回答通知给提问者
        # await self._send_answer_notification(
        #     question.id,
        #     user_id,
        #     question.user_id,
        # )
        
        logger.info(f"Answer created: {answer.id} for question {request.question_id}")
        return answer

    async def get_answers(
        self,
        question_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Answer], int]:
        """获取问题的回答列表"""
        return await self.repository.get_by_question_id(question_id, skip=skip, limit=limit)

    async def update_answer(
        self,
        answer_id: int,
        operator_id: int,
        content: Optional[str] = None,
        attachments: Optional[List[str]] = None,
        related_docs: Optional[List[int]] = None
    ) -> Answer:
        """更新回答"""
        answer = await self.repository.get_by_id(answer_id)
        if not answer:
            raise AnswerNotFoundError()
        
        # 只有回答者可以编辑
        if answer.user_id != operator_id:
            raise PermissionDeniedError(message="Only answer author can edit")
        
        update_data = {}
        if content is not None:
            update_data["content"] = content
        if attachments is not None:
            update_data["attachments"] = attachments
        if related_docs is not None:
            update_data["related_docs"] = related_docs
        
        return await self.repository.update(answer_id, **update_data)

    async def delete_answer(
        self,
        answer_id: int,
        operator_id: int
    ) -> bool:
        """删除回答"""
        answer = await self.repository.get_by_id(answer_id)
        if not answer:
            raise AnswerNotFoundError()
        
        # 只有回答者可以删除
        if answer.user_id != operator_id:
            raise PermissionDeniedError(message="Only answer author can delete")
        
        return await self.repository.delete(answer_id)

    async def _send_answer_notification(
        self,
        question_id: int,
        answerer_id: int,
        questioner_id: int,
    ):
        """发送回答通知"""
        notification = QANotification(
            recipient_id=questioner_id,
            sender_id=answerer_id,
            notification_type="answered",
            question_id=question_id,
            content="Someone answered your question",
            # tenant_id=tenant_id
        )
        await self.notification_repo.create(notification)


# ==================== 评论服务 ====================
class CommentService:
    """评论业务逻辑"""
    def __init__(self):
        self.repository = CommentRepository()
        self.answer_repo = AnswerRepository()
        self.notification_repo = NotificationRepository()

    async def create_comment(
        self,
        user_id: int,
        request: CommentCreateRequest
    ) -> Comment:
        """发布评论"""
        answer = await self.answer_repo.get_by_id(request.answer_id)
        if not answer:
            raise AnswerNotFoundError()
        
        comment = Comment(
            answer_id=request.answer_id,
            user_id=user_id,
            content=request.content,
            is_follow_up=request.is_follow_up,
        )
        
        comment = await self.repository.create(comment)
        
        # 更新回答的评论计数
        answer.comment_count += 1
        await self.answer_repo.update(request.answer_id, comment_count=answer.comment_count)
        
        # 发送评论通知
        # await self._send_comment_notification(
        #     answer.question_id,
        #     user_id,
        #     answer.user_id,
        # )
        
        return comment

    async def get_comments(
        self,
        answer_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Comment], int]:
        """获取回答的评论"""
        return await self.repository.get_by_answer_id(answer_id, skip=skip, limit=limit)

    async def _send_comment_notification(
        self,
        question_id: int,
        commenter_id: int,
        answerer_id: int,
    ):
        """发送评论通知"""
        notification = QANotification(
            recipient_id=answerer_id,
            sender_id=commenter_id,
            notification_type="commented",
            question_id=question_id,
            content="Someone commented on your answer",
            # tenant_id=tenant_id
        )
        await self.notification_repo.create(notification)


# ==================== 投票服务 ====================
class VoteService:
    """投票业务逻辑"""
    def __init__(self):
        self.repository = VoteRepository()
        self.question_repo = QuestionRepository()
        self.answer_repo = AnswerRepository()
        self.expert_repo = ExpertRepository()

    async def vote_question(
        self,
        user_id: int,
        question_id: int
    ) -> bool:
        """给问题点赞"""
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise QuestionNotFoundError()
        
        vote = await self.repository.add_question_vote(user_id, question_id)
        if vote:
            question.vote_count += 1
            await self.question_repo.update(question_id, vote_count=question.vote_count)
            return True
        return False

    async def vote_answer(
        self,
        user_id: int,
        answer_id: int
    ) -> bool:
        """给回答点赞（有用）"""
        answer = await self.answer_repo.get_by_id(answer_id)
        if not answer:
            raise AnswerNotFoundError()
        
        vote = await self.repository.add_answer_vote(user_id, answer_id)
        if vote:
            answer.vote_count += 1
            await self.answer_repo.update(answer_id, vote_count=answer.vote_count)
            
            await self.expert_repo.increment_vote_count(answer.expert_id, count=1)
            
            
            return True
        return False