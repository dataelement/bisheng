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

from bisheng.database.models.qa_expert import Expert, Question, Answer, Comment, QANotification
from bisheng.tenant.domain.services.inbox_helper import send_inbox_notice
from bisheng.qa_expert.domain.rich_text import question_description_to_plain_text
from bisheng.qa_expert.domain.schemas import (
    ExpertCreateRequest,
    ExpertUpdateRequest,
    QuestionCreateRequest,
    AnswerCreateRequest,
    CommentCreateRequest,
    AdoptAnswerRequest,
    QuestionUpdateRequest,
)
from bisheng.qa_expert.domain.repositories import (
    ExpertRepository,
    QuestionRepository,
    AnswerRepository,
    CommentRepository,
    VoteRepository,
    NotificationRepository,
    QAExpertStatsRepository,
)
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.database.models.department import DepartmentDao


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


class QAExpertStatsService:
    """Expert QA statistics service."""

    def __init__(self):
        self.repository = QAExpertStatsRepository()

    async def get_overview_stats(self) -> dict[str, int | float]:
        """Get Expert QA overview statistics."""
        return await self.repository.get_overview_stats()


# ==================== 专家服务 ====================
class ExpertService:
    """专家业务逻辑"""

    def __init__(self):
        self.repository = ExpertRepository()

    async def create_expert(self, request: ExpertCreateRequest) -> Expert:
        """创建专家（后台管理员操作）"""
        # 检查是否已是专家
        existing = await self.repository.get_by_user_name(request.expert_name)
        if existing:
            raise InvalidInvitationError(message=f"Expert {request.expert_name} is already exists")

        expert = Expert(
            expert_name=request.expert_name,
            introduction=request.introduction,
            depart_ment=request.depart_ment,
            user_id=request.user_id,
            major = request.major,
            position = request.position,
            job_family = request.job_family,
            job_category = request.job_category,
        )
        temp_expert = await self.repository.create(expert)
        depart = DepartmentDao.get_by_id(temp_expert.depart_ment)
        if depart:
            temp_expert.depart_ment = depart.name
        else:
            temp_expert.depart_ment = None
        return temp_expert

    async def update_expert(self, expert_id: int, request: ExpertUpdateRequest) -> Expert:
        """更新专家信息"""
        expert = await self.repository.get_by_id(expert_id)
        if not expert:
            raise ExpertNotFoundError()

        update_data = request.dict(exclude_unset=True)
        return await self.repository.update(expert_id, **update_data)

    async def list_experts(
        self, keyword: Optional[str] = None, skip: int = 0, limit: int = 20
    ) -> tuple[List[Expert], int]:
        """列表查询专家"""
        experts, total = await self.repository.list_all(keyword=keyword, skip=skip, limit=limit)
        for expert in experts:
            department = DepartmentDao.get_by_id(expert.depart_ment)
            if department:
                expert.depart_ment = department.name
            else:
                expert.depart_ment = None
        return experts, total

    async def delete_expert(self, expert_id: int) -> bool:
        """删除专家"""
        return await self.repository.delete(expert_id)
    
    
    async def get_expertinfo(self, expert_name: str) -> Optional[Expert]:
        """获取专家信息"""
        expert = await self.repository.get_expertinfo(expert_name)
        if expert:
            department = DepartmentDao.get_by_id(expert.depart_ment)
            if department:
                expert.depart_ment = department.name
            else:
                expert.depart_ment = None
        return expert
    
        
    async def get_expertinfobyid(self, user_id: int) -> bool:
        """获取专家信息"""
        return await self.repository.get_expertinfo_userid(user_id)


# ==================== 问题服务 ====================
class QuestionService:
    """问题业务逻辑"""

    def __init__(self):
        self.repository = QuestionRepository()
        self.expert_repo = ExpertRepository()
        self.answer_repo = AnswerRepository()
        self.notification_repo = NotificationRepository()

    async def create_question(self, user_id: int, request: QuestionCreateRequest, user_name: str) -> Question:
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
            created_by=user_name,
        )

        question = await self.repository.create(question)
        # 发送邀请通知
        await self._send_expert_invitation_inbox_notice(question, user_id,user_name)
    
        logger.info(f"Question created: {question.id} by user {user_id}")
        return question

    async def list_questions(
        self,
        business_domain: Optional[str] = None,
        status: Optional[int] = 0,
        sort_by: str = "latest",
        user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[Question], int]:
        """列表查询问题"""
        expert_id = None
        if status == 4:
            # 状态为 4 (邀请我的) 时，按被邀请的专家 ID 过滤
            if user_id is not None:
                expert = await self.expert_repo.get_by_user_id(user_id)
                if not expert:
                    return [], 0
                expert_id = expert.id
        questions, total = await self.repository.list_all(
            business_domain=business_domain, status=status, sort_by=sort_by, user_id=user_id, skip=skip, limit=limit, expert_id=expert_id
        )
        if questions and len(questions) > 0:
            for question in questions:
                vote_count = await self.answer_repo.get_answer_vote_count(question.id)
                question.vote_count = vote_count
        return questions, total

    async def get_question_detail(self, question_id: int, user_id: Optional[int] = None) -> Question:
        """获取问题详情"""
        question = await self.repository.get_by_id(question_id)
        if not question:
            raise QuestionNotFoundError()

        # 增加浏览数
        question.view_count += 1
        await self.repository.update(question_id, view_count=question.view_count)
        return question


    async def adopt_answer(self, question_id: int, answer_id: int, operator_id: int) -> Question:
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
        question.status =1  # 已解决    
        await self.repository.update(question_id, adopted_answer_id=answer_id, status=1)

        # 更新回答状态
        answer.status = 1  # 已采纳
        await self.answer_repo.update(answer_id, status=1,adopted=True)
        # 增加采纳采纳数
        await self.expert_repo.increment_adoption_count(answer.expert_id, count=1)

        # 发送采纳通知
        await self._send_adoption_notification(
            question,
            answer
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
        question: Question,
        answer: Answer,
    ):
        """发送采纳通知到 inbox_message"""
        if not question or not answer:
            return

        from bisheng.core.database import get_async_db_session
        from bisheng.message.domain.models.inbox_message import MessageStatusEnum, MessageTypeEnum
        from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import InboxMessageReadRepositoryImpl
        from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import InboxMessageRepositoryImpl
        from bisheng.message.domain.services.message_service import MessageService

        content = [
            {
                "type": "user",
                "content": f"@{question.created_by}",
                "metadata": {"user_id": question.user_id},
            },
            {
                "type": "system_text",
                "content": "qa_answer_accepted",
            },
            {
                "type": "business_url",
                "content": f"--{question.title}",
                "metadata": {
                    "business_type": "qa_question",
                    "data": {"question_id": str(question.id), "answer_id": str(answer.id)},
                },
            },
            {
                "type": "tooltip_text",
                "content": (answer.content or "")[:50],
            },
        ]

        async with get_async_db_session() as session:
            service = MessageService(
                message_repository=InboxMessageRepositoryImpl(session),
                message_read_repository=InboxMessageReadRepositoryImpl(session),
            )
            await service.send_message(
                content=content,
                sender=question.user_id,
                message_type=MessageTypeEnum.NOTIFY,
                receiver=[answer.expert_id],
                status=MessageStatusEnum.APPROVED,
                action_code="qa_answer_accepted",
            )

    async def get_answer_count_by_domain(self) -> list[dict]:
        """获取每个业务域的回答数"""
        return await self.repository.get_answer_count_by_domain()
    
    async def delete_question(self, question_id: int) -> bool:
        """删除问题"""
        return await self.repository.delete(question_id)
    
    async def update_question(self, question_id: int, request: QuestionUpdateRequest) -> Question:
        """更新问题信息"""
        question = await self.repository.get_by_id(question_id)
        if not question:
            raise QuestionNotFoundError()

        update_data = request.model_dump(exclude_unset=True)
        new_question = await self.repository.update(question_id, **update_data)
        # 发送邀请通知
        # await self._send_expert_invitation_inbox_notice(new_question, user_id,user_name)
    
        # logger.info(f"Question updated: {new_question.id} by user {user_id}")
        return new_question
    
    async def _send_expert_invitation_inbox_notice(
        self,
        question: Question,
        sender_id: int,
        sender_name: str,
    ):
        expert_ids = [
            int(item)
            for item in (question.invited_experts or "").split(";")
            if item.strip().isdigit()
        ]
        if not expert_ids:
            return

        receiver_user_ids = []
        for expert_id in expert_ids:
            expert = await self.expert_repo.get_by_id(expert_id)
            if expert and expert.user_id != sender_id:
                receiver_user_ids.append(expert.user_id)

        receiver_user_ids = list(set(receiver_user_ids))
        if not receiver_user_ids:
            return

        from bisheng.core.database import get_async_db_session
        from bisheng.message.domain.models.inbox_message import MessageStatusEnum, MessageTypeEnum
        from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import InboxMessageReadRepositoryImpl
        from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import InboxMessageRepositoryImpl
        from bisheng.message.domain.services.message_service import MessageService

        content = [
            {
                "type": "user",
                "content": f"@{sender_name}",
                "metadata": {"user_id": sender_id},
            },
            {
                "type": "system_text",
                "content": "qa_expert_invited",
            },
            {
                "type": "business_url",
                "content": f"--{question.title}",
                "metadata": {
                    "business_type": "qa_question",
                    "data": {"question_id": str(question.id)},
                },
            },
            {
                "type": "tooltip_text",
                "content": question_description_to_plain_text(question.description)[:50],
            },
        ]

        async with get_async_db_session() as session:
            service = MessageService(
                message_repository=InboxMessageRepositoryImpl(session),
                message_read_repository=InboxMessageReadRepositoryImpl(session),
            )
            await service.send_message(
                content=content,
                sender=sender_id,
                message_type=MessageTypeEnum.NOTIFY,
                receiver=receiver_user_ids,
                status=MessageStatusEnum.APPROVED,
                action_code="qa_expert_invited",
            )


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
            images_url=request.images_url,
            expert_name=expert.expert_name,
        )

        answer = await self.repository.create(answer)

        # 更新问题的回答计数
        question.answer_count += 1
        await self.question_repo.update(request.question_id, answer_count=question.answer_count)

        await self.expert_repo.increment_answer_count(expert.id, count=1)

        # 发送回答通知给提问者
        await self._send_answer_notification(
             question,
             answer
        )

        logger.info(f"Answer created: {answer.id} for question {request.question_id}")
        return answer

    async def get_answers(self, question_id: int, skip: int = 0, limit: int = 100, sort_by: Optional[str] = None) -> tuple[List[Answer], int]:
        """获取问题的回答列表"""
        return await self.repository.get_by_question_id(question_id, skip=skip, limit=limit, sort_by=sort_by)


    async def get_by_expertname(self,  expert_name: str,question_id: int,) -> Optional[Answer]:
        """获取问题的回答列表"""
        return await self.repository.get_by_expertname(expert_name,question_id)



    async def update_answer(
        self,
        answer_id: int,
        operator_id: int,
        content: Optional[str] = None,
        attachments: Optional[List[str]] = None,
        related_docs: Optional[List[int]] = None,
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

    async def delete_answer(self, answer_id: int, operator_id: int) -> bool:
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
        question: Question,
        answer: Answer
    ):
        """发送回答通知到 inbox_message"""
        if not question:
            return

        from bisheng.core.database import get_async_db_session
        from bisheng.message.domain.models.inbox_message import MessageStatusEnum, MessageTypeEnum
        from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import InboxMessageReadRepositoryImpl
        from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import InboxMessageRepositoryImpl
        from bisheng.message.domain.services.message_service import MessageService

        content = [
            {
                "type": "user",
                "content": f"@{answer.expert_name}",
                "metadata": {"user_id": answer.expert_id},
            },
            {
                "type": "system_text",
                "content": "qa_expert_answered",
            },
            {
                "type": "business_url",
                "content": f"--{question.title}",
                "metadata": {
                    "business_type": "qa_question",
                    "data": {"question_id": str(question.id), "answer_id": str(answer.id)},
                },
            },
            {
                "type": "tooltip_text",
                "content": (answer.content or "")[:50],
            },
        ]

        async with get_async_db_session() as session:
            service = MessageService(
                message_repository=InboxMessageRepositoryImpl(session),
                message_read_repository=InboxMessageReadRepositoryImpl(session),
            )
            await service.send_message(
                content=content,
                sender=answer.expert_id,
                message_type=MessageTypeEnum.NOTIFY,
                receiver=[question.user_id],
                status=MessageStatusEnum.APPROVED,
                action_code="qa_expert_answered",
            )


# ==================== 评论服务 ====================
class CommentService:
    """评论业务逻辑"""

    def __init__(self):
        self.repository = CommentRepository()
        self.answer_repo = AnswerRepository()
        self.notification_repo = NotificationRepository()
        self.question_repo = QuestionRepository()

    async def create_comment(self, user_id: int, user_name: str, request: CommentCreateRequest) -> Comment:
        """发布评论"""
        comment = None
        if request.answer_id and request.answer_id != 0:
            answer = await self.answer_repo.get_by_id(request.answer_id)
            if not answer:
                raise AnswerNotFoundError()
            comment = Comment(
                answer_id=request.answer_id,
                question_id=answer.question_id,
                user_id=user_id,
                user_name=user_name,
                content=request.content,
                is_follow_up=request.is_follow_up,
            )

            answer.comment_count += 1
            await self.answer_repo.update(request.answer_id, comment_count=answer.comment_count)
            # 2. 统一执行创建操作
            comment = await self.repository.create(comment)
            # 3. 发送评论通知 (按需开启)
            await self._send_comment_notification(
                answer,
                comment,
            )
        else:
            if not request.question_id:
                raise ValueError("缺少问题ID，无法创建追问")
            question = await self.question_repo.get_by_id(request.question_id)
            if not question:
                raise QuestionNotFoundError()

            comment = Comment(
                answer_id=0,
                question_id=request.question_id,
                user_id=user_id,
                content=request.content,
                is_follow_up=True,
                user_name=user_name,
            )
            question.comment_count += 1
            await self.question_repo.update(request.question_id, comment_count=question.comment_count)
            # 2. 统一执行创建操作
            comment = await self.repository.create(comment)

        return comment

    async def get_comments(
        self, answer_id: Optional[int] = None,
        question_id: Optional[int] = None,
        skip: int = 0, 
        limit: int = 100
    ) -> tuple[List[Comment], int]:
        """获取回答的评论"""
        return await self.repository.get_by_answer_id(answer_id, question_id=question_id, skip=skip, limit=limit)

    async def _send_comment_notification(
        self,
        answer: Answer,
        comment: Comment,
    ):
        """发送评论通知到 inbox_message"""
        if not answer or not comment:
            return
        question = await self.question_repo.get_by_id(answer.question_id)
        if not question:
            return

        from bisheng.core.database import get_async_db_session
        from bisheng.message.domain.models.inbox_message import MessageStatusEnum, MessageTypeEnum
        from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import InboxMessageReadRepositoryImpl
        from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import InboxMessageRepositoryImpl
        from bisheng.message.domain.services.message_service import MessageService

        content = [
            {
                "type": "user",
                "content": f"@{comment.user_name}",
                "metadata": {"user_id": comment.user_id},
            },
            {
                "type": "system_text",
                "content": "qa_answer_commented",
            },
            {
                "type": "business_url",
                "content": f"--{question.title}",
                "metadata": {
                    "business_type": "qa_question",
                    "data": {
                        "question_id": str(question.id),
                        "answer_id": str(answer.id),
                        "comment_id": str(comment.id),
                    },
                },
            },
            {
                "type": "tooltip_text",
                "content": (comment.content or "")[:50],
            },
        ]

        async with get_async_db_session() as session:
            service = MessageService(
                message_repository=InboxMessageRepositoryImpl(session),
                message_read_repository=InboxMessageReadRepositoryImpl(session),
            )
            await service.send_message(
                content=content,
                sender=comment.user_id,
                message_type=MessageTypeEnum.NOTIFY,
                receiver=[answer.expert_id],
                status=MessageStatusEnum.APPROVED,
                action_code="qa_answer_commented",
            )


# ==================== 投票服务 ====================
class VoteService:
    """投票业务逻辑"""

    def __init__(self):
        self.repository = VoteRepository()
        self.question_repo = QuestionRepository()
        self.answer_repo = AnswerRepository()
        self.expert_repo = ExpertRepository()

    async def vote_question(self, user_id: int, question_id: int) -> bool:
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

    async def vote_answer(self, user_id: int, answer_id: int) -> bool:
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
