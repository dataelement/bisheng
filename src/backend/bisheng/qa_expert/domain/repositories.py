"""Expert QA Repositories - 数据访问层"""

from typing import Optional, List
from sqlmodel import select, func, and_, or_, desc
from sqlalchemy import Column, DateTime, Integer, String, delete, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from bisheng.core.database import get_async_db_session  # 确保导入了异步方法
from bisheng.database.models.qa_expert import (
    Expert,
    Question,
    Answer,
    Comment,
    QuestionVote,
    AnswerVote,
    CommentVote,
    QANotification,
)


RESOLUTION_RATE_PRECISION = 4


class ExpertRepository:
    """专家仓储"""

    async def create(self, expert: Expert) -> Expert:
        """创建专家"""
        async with get_async_db_session() as session:
            session.expire_on_commit = False
            session.add(expert)
            await session.commit()
            await session.flush(expert)
            return expert

    async def get_by_id(self, expert_id: int) -> Optional[Expert]:
        """根据ID获取专家"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.id == expert_id)
            result = await session.exec(stmt)
            return result.first()

    async def get_by_user_name(self, name: str) -> Optional[Expert]:
        """根据用户名称获取专家"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.expert_name == name)
            result = await session.exec(stmt)
            return result.first()

    async def get_by_user_id(self, user_id: int) -> Optional[Expert]:
        """根据用户ID获取专家"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.user_id == user_id)
            result = await session.exec(stmt)
            return result.first()

    async def list_all(
        self, business_domain: Optional[str] = None, keyword: Optional[str] = None, skip: int = 0, limit: int = 20
    ) -> tuple[List[Expert], int]:
        """列表查询专家"""
        async with get_async_db_session() as session:
            # 1. 构建基础查询条件（复用条件，保证 count 和 data 一致）
            base_stmt = select(Expert)

            if keyword:
                base_stmt = base_stmt.where(
                    or_(Expert.expert_name.ilike(f"%{keyword}%"), Expert.introduction.ilike(f"%{keyword}%"))
                )

            # 2. 执行计数查询（应用了相同的筛选条件）
            count_stmt = select(func.count()).select_from(base_stmt.subquery())
            count_result = await session.execute(count_stmt)
            total = count_result.scalar() or 0

            # 3. 执行分页查询
            data_stmt = base_stmt.offset(skip).limit(limit).order_by(desc(Expert.created_at))
            result = await session.exec(data_stmt)
            experts = result.all()

            return experts, total

    async def increment_answer_count(self, expert_id: int, count: int = 1):
        """原子性增加专家的回答数量"""
        async with get_async_db_session() as session:
            stmt = update(Expert).where(Expert.id == expert_id).values(answer_count=Expert.answer_count + count)

            await session.exec(stmt)
            await session.commit()

    async def increment_vote_count(self, expert_id: int, count: int = 1):
        """原子性增加专家的回答数量"""
        async with get_async_db_session() as session:
            stmt = update(Expert).where(Expert.id == expert_id).values(vote_count=Expert.vote_count + count)
            await session.exec(stmt)
            await session.commit()
            
    async def  vote_count_userid(self, user_id: int, count: int = 1):
        """原子性增加专家的回答数量"""
        async with get_async_db_session() as session:
            stmt = update(Expert).where(Expert.user_id == user_id).values(vote_count=Expert.vote_count + count)
            await session.exec(stmt)
            await session.commit()

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
            await session.commit()
            await session.flush(expert)
            return expert

    async def delete(self, expert_id: int) -> bool:
        """删除专家"""
        async with get_async_db_session() as session:
            expert = await self.get_by_id(expert_id)
            if not expert:
                return False
            await session.delete(expert)
            await session.commit()
            await session.flush()
            return True

    async def  get_expertinfo(self, expert_name: str):
        """原子性增加专家的回答数量"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.expert_name == expert_name)
            result = await session.exec(stmt)
            return result.first()
        
    async def  get_expertinfo_userid(self, user_id: int):
        """获取专家userid"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.user_id == user_id)
            result = await session.exec(stmt)
            return result.first()

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
            result = await session.exec(stmt)
            return result.first()
        
    async def delete(self, question_id: int) -> bool:
        """删除问题"""
        async with get_async_db_session() as session:
            question = await self.get_by_id(question_id)
            if not question:
                return False
            await session.delete(question)
            await session.commit()
            await session.flush()
            return True

    async def list_all(
        self,
        business_domain: Optional[str] = None,
        status: Optional[str] = None,
        sort_by: str = "latest",
        user_id: Optional[int] = None,  # 我提问的
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[Question], int]:
        """列表查询问题"""
        async with get_async_db_session() as session:
            stmt = select(Question)

            if business_domain:
                stmt = stmt.where(Question.business_domain == business_domain)
            if user_id:
                stmt = stmt.where(Question.user_id == user_id)
            if status in (1, 2):
                # 状态为 1 (未解决) 或 2 (已解决) 时，直接按问题状态过滤
                stmt = stmt.where(Question.status == status)
            elif status == 3:
                # 状态为 3 (我提问的) 时，按提问人 ID 过滤
                if user_id is not None:
                    stmt = stmt.where(Question.user_id == user_id)

            elif status == 4:
                # 状态为 4 (邀请我的) 时，按被邀请的专家 ID 过滤
                if user_id is not None:
                    stmt = stmt.where(Question.invited_experts.contains(user_id))

            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = await session.exec(count_stmt) or 0

            # 排序
            if sort_by == "hot":
                stmt = stmt.order_by(desc(Question.view_count), desc(Question.created_at))
            elif sort_by == "unanswered":
                stmt = stmt.where(Question.answer_count == 0).order_by(desc(Question.created_at))
            else:
                stmt = stmt.order_by(desc(Question.created_at))

            stmt = stmt.offset(skip).limit(limit)

            result = await session.exec(stmt)
            return result.all(), total

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
            result = await session.exec(stmt)
            return result.scalars().all()

    async def get_stats(self) -> dict:
        """获取问题统计"""
        async with get_async_db_session() as session:
            total_stmt = select(func.count()).select_from(Question)
            total = (await session.exec(total_stmt)).scalars().first() or 0

            unsolved_stmt = select(func.count()).select_from(Question).where(Question.status == "unsolved")
            unsolved = (await session.exec(unsolved_stmt)).scalars().first() or 0

            solved_stmt = select(func.count()).select_from(Question).where(Question.status == "solved")
            solved = (await session.exec(solved_stmt)).scalars().first() or 0

            closed_stmt = select(func.count()).select_from(Question).where(Question.status == "closed")
            closed = (await session.exec(closed_stmt)).scalars().first() or 0

            return {"total": total, "unsolved": unsolved, "solved": solved, "closed": closed}


class QAExpertStatsRepository:
    """Repository for Expert QA overview statistics."""

    async def get_overview_stats(self) -> dict[str, int | float]:
        """Return question, expert, answer counts and resolution rate."""
        async with get_async_db_session() as session:
            question_stats_stmt = select(
                func.count(Question.id).label("total_questions"),
                func.count(Question.adopted_answer_id).label("solved_questions"),
            )
            question_stats = (await session.exec(question_stats_stmt)).one()
            total_questions = int(question_stats.total_questions or 0)
            solved_questions = int(question_stats.solved_questions or 0)

            expert_count_stmt = select(func.count(Expert.id))
            total_experts = int((await session.exec(expert_count_stmt)).one() or 0)

            answer_count_stmt = select(func.count(Answer.id))
            total_answers = int((await session.exec(answer_count_stmt)).one() or 0)

            resolution_rate = (
                round(solved_questions / total_questions, RESOLUTION_RATE_PRECISION)
                if total_questions
                else 0.0
            )

            return {
                "total_questions": total_questions,
                "total_experts": total_experts,
                "total_answers": total_answers,
                "solved_questions": solved_questions,
                "resolution_rate": resolution_rate,
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
            result = await session.exec(stmt)
            return result.first()

    async def get_by_expertname(self, expert_name: str,question_id: int) -> Optional[Answer]:
        """根据专家名称获取回答"""
        async with get_async_db_session() as session:
            stmt = select(Answer).where(Answer.expert_name == expert_name and Answer.question_id == question_id)
            result = await session.exec(stmt)
            
            return result.first()


    async def get_by_question_id(self, question_id: int, skip: int = 0, limit: int = 100) -> tuple[List[Answer], int]:
        """获取问题的所有回答"""
        async with get_async_db_session() as session:
            stmt = (
                select(Answer, func.count().over().label("total"))
                .where(Answer.question_id == question_id)
                .order_by(Answer.status == 1, desc(Answer.vote_count), desc(Answer.created_at))
                .offset(skip)
                .limit(limit)
            )

            result = await session.exec(stmt)
            rows = result.all()  # 获取所有的 Row 对象

            if not rows:
                return [], 0

            # 从第一行中提取出总数，并从每行中提取出 Answer 实体
            total = rows[0].total
            answers = [row.Answer for row in rows]

            return answers, total

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
        self, answer_id: int, 
        question_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Comment], int]:
        """获取回答的所有评论"""
        if answer_id == 0 and not question_id:
            raise ValueError("当 answer_id 为 0 时，必须提供 question_id")

        async with get_async_db_session() as session:
            # 2. 动态构建基础查询条件
            base_where_clause = Comment.question_id == question_id if answer_id == 0 else Comment.answer_id == answer_id

            count_stmt = select(func.count()).select_from(Comment).where(base_where_clause)
            count_result = await session.exec(count_stmt)
            total = count_result.first() or 0

            stmt = select(Comment).where(base_where_clause).order_by(desc(Comment.created_at)).offset(skip).limit(limit)
            result = await session.exec(stmt)

            return result.all(), total


class VoteRepository:
    """投票仓储"""

    async def add_question_vote(self, user_id: int, question_id: int) -> Optional[QuestionVote]:
        """给问题点赞"""
        async with get_async_db_session() as session:
            # 检查是否已点赞
            stmt = select(QuestionVote).where(
                and_(QuestionVote.user_id == user_id, QuestionVote.question_id == question_id)
            )
            existing = (await session.exec(stmt)).first()
            if existing:
                return existing  # 已点赞

            vote = QuestionVote(user_id=user_id, question_id=question_id)
            session.add(vote)
            await session.commit()
            await session.flush()
            return vote

    async def remove_question_vote(self, user_id: int, question_id: int) -> bool:
        """取消问题点赞"""
        async with get_async_db_session() as session:
            stmt = select(QuestionVote).where(
                and_(QuestionVote.user_id == user_id, QuestionVote.question_id == question_id)
            )
            vote = (await session.exec(stmt)).scalars().first()
            if not vote:
                return False
            await session.delete(vote)
            return True

    async def add_answer_vote(self, user_id: int, answer_id: int, vote_type: str = "helpful") -> Optional[AnswerVote]:
        """给回答点赞"""
        async with get_async_db_session() as session:
            stmt = select(AnswerVote).where(and_(AnswerVote.user_id == user_id, AnswerVote.answer_id == answer_id))
            existing = (await session.exec(stmt)).first()
            if existing:
                return existing

            vote = AnswerVote(user_id=user_id, answer_id=answer_id, vote_type=vote_type)
            session.add(vote)
            await session.commit()
            await session.flush()
            return vote

    async def remove_answer_vote(self, user_id: int, answer_id: int) -> bool:
        """取消回答点赞"""
        async with get_async_db_session() as session:
            stmt = select(AnswerVote).where(and_(AnswerVote.user_id == user_id, AnswerVote.answer_id == answer_id))
            vote = (await session.exec(stmt)).scalars().first()
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
        self, user_id: int, unread_only: bool = False, skip: int = 0, limit: int = 20
    ) -> tuple[List[QANotification], int]:
        """获取用户通知"""
        async with get_async_db_session() as session:
            stmt = select(QANotification).where(QANotification.recipient_id == user_id)
            if unread_only:
                stmt = stmt.where(QANotification.read == False)

            count_result = await session.execute(
                select(func.count()).select_from(QANotification).where(QANotification.recipient_id == user_id)
            )
            total = count_result.scalars().first() or 0

            stmt = stmt.order_by(desc(QANotification.created_at)).offset(skip).limit(limit)
            result = await session.exec(stmt)
            return result.scalars().all(), total

    async def mark_as_read(self, notification_id: int) -> bool:
        """标记为已读"""
        async with get_async_db_session() as session:
            stmt = select(QANotification).where(QANotification.id == notification_id)
            notification = (await session.exec(stmt)).scalars().first()
            if not notification:
                return False
            notification.read = True
            session.add(notification)
            await session.flush()
            return True



