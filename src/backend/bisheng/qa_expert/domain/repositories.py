""" Expert QA Repositories - 数据访问层 """
from typing import Optional, List
from sqlmodel import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from bisheng.core.database import get_async_db_session # 确保导入了异步方法
from bisheng.database.models.qa_expert import (
    Expert,
    Question,
    Answer,
    Comment,
    QuestionVote,
    AnswerVote,
    CommentVote,
    QANotification,
    QuestionDraft
)


class ExpertRepository:
    """专家仓储"""

    async def create(self, expert: Expert) -> Expert:
        """创建专家"""
        async with get_async_db_session() as session:
            session.expire_on_commit = False
            session.add(expert)
            await session.flush()
            return expert

    async def get_by_id(self, expert_id: int) -> Optional[Expert]:
        """根据ID获取专家"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.id == expert_id)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_by_user_id(self, user_id: int) -> Optional[Expert]:
        """根据用户ID获取专家"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.user_id == user_id)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def list_all(
        self,
        business_domain: Optional[str] = None,
        level: Optional[str] = None,
        keyword: Optional[str] = None,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[List[Expert], int]:
        """列表查询专家"""
        async with get_async_db_session() as session:
            stmt = select(Expert)
            
            if business_domain:
                # JSON 字段包含查询（需根据数据库类型调整）
                stmt = stmt.where(Expert.business_domains.astext.contains(business_domain))
            if level:
                stmt = stmt.where(Expert.level == level)
            if keyword:
                stmt = stmt.where(
                    or_(
                        Expert.expert_name.ilike(f"%{keyword}%"),
                        Expert.introduction.ilike(f"%{keyword}%")
                    )
                )

            # 计数
            count_stmt = select(func.count()).select_from(Expert)
            count_result = await session.execute(count_stmt)
            total = count_result.scalars().first() or 0

            # 分页
            stmt = stmt.offset(skip).limit(limit).order_by(desc(Expert.created_at))
            result = await session.execute(stmt)
            return result.scalars().all(), total

    async def update(self, expert_id: int, **kwargs) -> Optional[Expert]:
        """更新专家"""
        async with get_async_db_session() as session:
            expert = await self.get_by_id(expert_id)
            if not expert:
                return None
            for key, value in kwargs.items():
                if hasattr(expert, key):
                    setattr(expert, key, value)
            session.add(expert)
            await session.flush()
            return expert

    async def delete(self, expert_id: int) -> bool:
        """删除专家"""
        async with get_async_db_session() as session:
            expert = await self.get_by_id(expert_id)
            if not expert:
                return False
            await session.delete(expert)
            return True


class QuestionRepository:
    """问题仓储"""

    async def create(self, question: Question) -> Question:
        """创建问题"""
        async with get_async_db_session() as session:
            session.expire_on_commit = False
            session.add(question)
            await session.commit()
            await session.refresh(question)
            return question

    async def get_by_id(self, question_id: int) -> Optional[Question]:
        """根据ID获取问题"""
        async with get_async_db_session() as session:
            stmt = select(Question).where(Question.id == question_id)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def list_all(
        self,
        business_domain: Optional[str] = None,
        status: Optional[str] = None,
        sort_by: str = "latest",
        user_id: Optional[int] = None, # 我提问的
        skip: int = 0,
        limit: int = 20
    ) -> tuple[List[Question], int]:
        """列表查询问题"""
        async with get_async_db_session() as session:
            stmt = select(Question)
            
            if business_domain:
                stmt = stmt.where(Question.business_domain == business_domain)
            if status:
                stmt = stmt.where(Question.status == status)
            if user_id:
                stmt = stmt.where(Question.user_id == user_id)

            # 计数
            count_result = await session.execute(select(func.count()).select_from(Question))
            total = count_result.scalars().first() or 0

            # 排序
            if sort_by == "hot":
                stmt = stmt.order_by(desc(Question.view_count), desc(Question.created_at))
            elif sort_by == "unanswered":
                stmt = stmt.where(Question.answer_count == 0).order_by(desc(Question.created_at))
            else: # latest
                stmt = stmt.order_by(desc(Question.created_at))

            # 分页
            stmt = stmt.offset(skip).limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all(), total

    async def update(self, question_id: int, **kwargs) -> Optional[Question]:
        """更新问题"""
        async with get_async_db_session() as session:
            session.expire_on_commit = False
            question = await self.get_by_id(question_id)
            if not question:
                return None
            for key, value in kwargs.items():
                if hasattr(question, key):
                    setattr(question, key, value)
                    
            session.add(question)
            await session.commit()   
            await session.refresh(question)        
            return question

    async def get_business_domains(self) -> List[str]:
        """获取所有业务域"""
        async with get_async_db_session() as session:
            stmt = select(func.distinct(Question.business_domain))
            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_stats(self) -> dict:
        """获取问题统计"""
        async with get_async_db_session() as session:
            total_stmt = select(func.count()).select_from(Question)
            total = (await session.execute(total_stmt)).scalars().first() or 0

            unsolved_stmt = select(func.count()).select_from(Question).where(
                Question.status == "unsolved"
            )
            unsolved = (await session.execute(unsolved_stmt)).scalars().first() or 0

            solved_stmt = select(func.count()).select_from(Question).where(
                Question.status == "solved"
            )
            solved = (await session.execute(solved_stmt)).scalars().first() or 0

            closed_stmt = select(func.count()).select_from(Question).where(
                Question.status == "closed"
            )
            closed = (await session.execute(closed_stmt)).scalars().first() or 0

            return {
                "total": total,
                "unsolved": unsolved,
                "solved": solved,
                "closed": closed
            }


class AnswerRepository:
    """回答仓储"""

    async def create(self, answer: Answer) -> Answer:
        """创建回答"""
        async with get_async_db_session() as session:
            session.add(answer)
            await session.commit()
            await session.flush(answer)
            return answer

    async def get_by_id(self, answer_id: int) -> Optional[Answer]:
        """根据ID获取回答"""
        async with get_async_db_session() as session:
            stmt = select(Answer).where(Answer.id == answer_id)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_by_question_id(
        self,
        question_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Answer], int]:
        """获取问题的所有回答"""
        async with get_async_db_session() as session:
            stmt = select(Answer).where(Answer.question_id == question_id)
            
            count_result = await session.execute(
                select(func.count()).select_from(Answer).where(Answer.question_id == question_id)
            )
            total = count_result.scalars().first() or 0

            # 采纳的回答优先显示
            stmt = stmt.order_by(
                Answer.status == "adopted", # True (1) 排前面
                desc(Answer.vote_count),
                desc(Answer.created_at)
            ).offset(skip).limit(limit)
            
            result = await session.execute(stmt)
            return result.scalars().all(), total

    async def update(self, answer_id: int, **kwargs) -> Optional[Answer]:
        """更新回答"""
        async with get_async_db_session() as session:
            answer = await self.get_by_id(answer_id)
            if not answer:
                return None
            for key, value in kwargs.items():
                if hasattr(answer, key):
                    setattr(answer, key, value)
            session.add(answer)
            await session.commit()   
            await session.refresh(answer)  
            await session.flush()
            return answer

    async def delete(self, answer_id: int) -> bool:
        """删除回答"""
        async with get_async_db_session() as session:
            answer = await self.get_by_id(answer_id)
            if not answer:
                return False
            answer.status = "deleted"
            session.add(answer)
            await session.flush()
            return True


class CommentRepository:
    """评论仓储"""

    async def create(self, comment: Comment) -> Comment:
        """创建评论"""
        async with get_async_db_session() as session:
            session.add(comment)
            await session.commit()
            await session.flush(comment)
            return comment

    async def get_by_answer_id(
        self,
        answer_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Comment], int]:
        """获取回答的所有评论"""
        async with get_async_db_session() as session:
            stmt = select(Comment).where(Comment.answer_id == answer_id)
            
            count_result = await session.execute(
                select(func.count()).select_from(Comment).where(Comment.answer_id == answer_id)
            )
            total = count_result.scalars().first() or 0

            stmt = stmt.order_by(desc(Comment.created_at)).offset(skip).limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all(), total


class VoteRepository:
    """投票仓储"""

    async def add_question_vote(
        self,
        user_id: int,
        question_id: int
    ) -> Optional[QuestionVote]:
        """给问题点赞"""
        async with get_async_db_session() as session:
            # 检查是否已点赞
            stmt = select(QuestionVote).where(
                and_(
                    QuestionVote.user_id == user_id,
                    QuestionVote.question_id == question_id
                )
            )
            existing = (await session.execute(stmt)).scalars().first()
            if existing:
                return None # 已点赞

            vote = QuestionVote(user_id=user_id, question_id=question_id)
            session.add(vote)
            await session.commit()
            await session.flush()
            return vote

    async def remove_question_vote(
        self,
        user_id: int,
        question_id: int
    ) -> bool:
        """取消问题点赞"""
        async with get_async_db_session() as session:
            stmt = select(QuestionVote).where(
                and_(
                    QuestionVote.user_id == user_id,
                    QuestionVote.question_id == question_id
                )
            )
            vote = (await session.execute(stmt)).scalars().first()
            if not vote:
                return False
            await session.delete(vote)
            return True

    async def add_answer_vote(
        self,
        user_id: int,
        answer_id: int,
        vote_type: str = "helpful"
    ) -> Optional[AnswerVote]:
        """给回答点赞"""
        async with get_async_db_session() as session:
            stmt = select(AnswerVote).where(
                and_(
                    AnswerVote.user_id == user_id,
                    AnswerVote.answer_id == answer_id
                )
            )
            existing = (await session.execute(stmt)).scalars().first()
            if existing:
                return None

            vote = AnswerVote(user_id=user_id, answer_id=answer_id, vote_type=vote_type)
            session.add(vote)
            await session.flush()
            return vote

    async def remove_answer_vote(
        self,
        user_id: int,
        answer_id: int
    ) -> bool:
        """取消回答点赞"""
        async with get_async_db_session() as session:
            stmt = select(AnswerVote).where(
                and_(
                    AnswerVote.user_id == user_id,
                    AnswerVote.answer_id == answer_id
                )
            )
            vote = (await session.execute(stmt)).scalars().first()
            if not vote:
                return False
            await session.delete(vote)
            return True


class NotificationRepository:
    """通知仓储"""

    async def create(self, notification: QANotification) -> QANotification:
        """创建通知"""
        async with get_async_db_session() as session:
            session.add(notification)
            await session.flush()
            return notification

    async def get_user_notifications(
        self,
        user_id: int,
        unread_only: bool = False,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[List[QANotification], int]:
        """获取用户通知"""
        async with get_async_db_session() as session:
            stmt = select(QANotification).where(QANotification.recipient_id == user_id)
            if unread_only:
                stmt = stmt.where(QANotification.read == False)

            count_result = await session.execute(
                select(func.count()).select_from(QANotification).where(
                    QANotification.recipient_id == user_id
                )
            )
            total = count_result.scalars().first() or 0

            stmt = stmt.order_by(desc(QANotification.created_at)).offset(skip).limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all(), total

    async def mark_as_read(self, notification_id: int) -> bool:
        """标记为已读"""
        async with get_async_db_session() as session:
            stmt = select(QANotification).where(QANotification.id == notification_id)
            notification = (await session.execute(stmt)).scalars().first()
            if not notification:
                return False
            notification.read = True
            session.add(notification)
            await session.flush()
            return True


class DraftRepository:
    """问题草稿仓储"""

    async def create_or_update(
        self,
        user_id: int,
        **kwargs
    ) -> QuestionDraft:
        """创建或更新草稿"""
        async with get_async_db_session() as session:
            # 查找现有草稿
            stmt = select(QuestionDraft).where(QuestionDraft.user_id == user_id)
            existing = (await session.execute(stmt)).scalars().first()
            
            if existing:
                for key, value in kwargs.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                session.add(existing)
            else:
                draft = QuestionDraft(user_id=user_id, **kwargs)
                session.add(draft)
                existing = draft
                
            await session.flush()
            return existing

    async def get_draft(self, user_id: int) -> Optional[QuestionDraft]:
        """获取用户的草稿"""
        async with get_async_db_session() as session:
            stmt = select(QuestionDraft).where(QuestionDraft.user_id == user_id)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def delete_draft(self, user_id: int) -> bool:
        """删除草稿"""
        async with get_async_db_session() as session:
            draft = await self.get_draft(user_id)
            if not draft:
                return False
            await session.delete(draft)
            return True