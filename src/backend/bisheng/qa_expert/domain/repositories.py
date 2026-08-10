"""Expert QA Repositories - 数据访问层"""


from sqlalchemy import Integer, cast, desc, func, update
from sqlmodel import and_, or_, select

from bisheng.core.database import get_async_db_session  # 确保导入了异步方法
from bisheng.database.models.department import Department
from bisheng.database.models.qa_expert import (
    Answer,
    AnswerVote,
    Comment,
    Expert,
    QANotification,
    Question,
    QuestionVote,
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

    async def get_by_id(self, expert_id: int) -> Expert | None:
        """根据ID获取专家"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.id == expert_id)
            result = await session.exec(stmt)
            return result.first()

    async def get_by_user_name(self, name: str, user_id: int) -> Expert | None:
        """根据用户名称获取专家"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(and_(Expert.expert_name == name, Expert.user_id == user_id))
            result = await session.exec(stmt)
            return result.first()

    async def get_by_user_id(self, user_id: int) -> Expert | None:
        """根据用户ID获取专家"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.user_id == user_id)
            result = await session.exec(stmt)
            return result.first()

    async def list_all(
        self,
        keyword: str | None = None,
        department_id: str | None = None,
        job_family: str | None = None,
        job_category: str | None = None,
        position: str | None = None,
        major: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int | None = 20,
        answer_desc: bool | None = None,
        adoption_desc: bool | None = None,
        vote_desc: bool | None = None,
    ) -> tuple[list[Expert], int]:
        """列表查询专家"""
        async with get_async_db_session() as session:
            # 1. 构建基础查询条件（复用条件，保证 count 和 data 一致）
            base_stmt = select(Expert)

            if keyword:
                normalized_keyword = keyword.strip()
                base_stmt = base_stmt.outerjoin(
                    Department,
                    cast(Expert.depart_ment, Integer) == Department.id,
                )
                base_stmt = base_stmt.where(
                    or_(
                        Expert.expert_name.ilike(f"%{normalized_keyword}%"),
                        Expert.introduction.ilike(f"%{normalized_keyword}%"),
                        Department.name.ilike(f"%{normalized_keyword}%"),
                        Department.short_name.ilike(f"%{normalized_keyword}%"),
                    )
                )

            exact_filters = (
                (Expert.depart_ment, department_id),
                (Expert.job_family, job_family),
                (Expert.job_category, job_category),
                (Expert.position, position),
                (Expert.major, major),
            )
            for column, value in exact_filters:
                if value and value.strip():
                    base_stmt = base_stmt.where(func.trim(column) == value.strip())

            # 2. 执行计数查询（应用了相同的筛选条件）
            count_stmt = select(func.count()).select_from(base_stmt.subquery())
            count_result = await session.execute(count_stmt)
            total = count_result.scalar() or 0

            # 3. 执行排序和分页查询。部门名称排序在 Service 完成，因为专家表只保存部门 ID。
            order_clauses: list = []
            if answer_desc is not None:
                order_clauses.append(Expert.answer_count.desc() if answer_desc else Expert.answer_count.asc())
            if adoption_desc is not None:
                order_clauses.append(Expert.adoption_count.desc() if adoption_desc else Expert.adoption_count.asc())
            if vote_desc is not None:
                order_clauses.append(Expert.vote_count.desc() if vote_desc else Expert.vote_count.asc())

            if not order_clauses:
                expert_score = Expert.answer_count + Expert.adoption_count * 5 + Expert.vote_count * 2
                sort_expressions = {
                    "expert_name": func.lower(Expert.expert_name),
                    "job_family": func.lower(func.coalesce(Expert.job_family, "")),
                    "job_category": func.lower(func.coalesce(Expert.job_category, "")),
                    "position": func.lower(func.coalesce(Expert.position, "")),
                    "major": func.lower(func.coalesce(Expert.major, "")),
                    "expert_score": expert_score,
                    "created_at": Expert.created_at,
                }
                sort_expression = sort_expressions.get(sort_by, Expert.created_at)
                order_clauses.append(sort_expression.asc() if sort_order == "asc" else sort_expression.desc())

            order_clauses.append(Expert.id.asc())
            data_stmt = base_stmt.order_by(*order_clauses)
            if skip:
                data_stmt = data_stmt.offset(skip)
            if limit is not None:
                data_stmt = data_stmt.limit(limit)
            result = await session.exec(data_stmt)
            experts = result.all()

            return experts, total

    async def list_filter_options(self) -> dict[str, list[str]]:
        """返回专家职业字段的去重筛选项。"""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(
                    Expert.depart_ment,
                    Expert.job_family,
                    Expert.job_category,
                    Expert.position,
                    Expert.major,
                )
            )
            options = {
                "department_ids": set(),
                "job_families": set(),
                "job_categories": set(),
                "positions": set(),
                "majors": set(),
            }
            for department_id, job_family, job_category, position, major in result.all():
                for key, value in (
                    ("department_ids", department_id),
                    ("job_families", job_family),
                    ("job_categories", job_category),
                    ("positions", position),
                    ("majors", major),
                ):
                    normalized = str(value or "").strip()
                    if normalized:
                        options[key].add(normalized)
            return {key: sorted(values, key=str.casefold) for key, values in options.items()}

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

    async def increment_adoption_count(self, expert_id: int, count: int = 1):
        """原子性增加专家采纳采纳数量"""
        async with get_async_db_session() as session:
            stmt = update(Expert).where(Expert.id == expert_id).values(adoption_count=Expert.adoption_count + count)
            await session.exec(stmt)
            await session.commit()

    async def update(self, expert_id: int, **kwargs) -> Expert | None:
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

    async def get_expertinfo(self, expert_name: str):
        """原子性增加专家的回答数量"""
        async with get_async_db_session() as session:
            stmt = select(Expert).where(Expert.expert_name == expert_name)
            result = await session.exec(stmt)
            return result.first()

    async def get_expertinfo_userid(self, user_id: int):
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

    async def get_by_id(self, question_id: int) -> Question | None:
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
        business_domain: str | None = None,
        status: int | None = 0,
        sort_by: str = "latest",
        user_id: int | None = None,  # 我提问的
        skip: int = 0,
        limit: int = 20,
        expert_id: int | None = None,  # 邀请我的专家ID
    ) -> tuple[list[Question], int]:
        """列表查询问题"""
        async with get_async_db_session() as session:
            stmt = select(Question)

            if business_domain:
                stmt = stmt.where(Question.business_domain == business_domain)

            if status in (1, 2):
                # 状态为 1 (未解决) 或 2 (已解决) 时，直接按问题状态过滤
                stmt = stmt.where(Question.status == status - 1)
            elif status == 3:
                # 状态为 3 (我提问的) 时，按提问人 ID 过滤
                if user_id is not None:
                    stmt = stmt.where(Question.user_id == user_id)
            elif status == 4:
                # 状态为 4 (邀请我的) 时，按被邀请的专家 ID 过滤
                if expert_id is not None:
                    expert_id_str = str(expert_id)
                    stmt = stmt.where(
                        or_(
                            Question.invited_experts == expert_id_str,
                            Question.invited_experts.like(f"{expert_id_str};%"),
                            Question.invited_experts.like(f"%;{expert_id_str};%"),
                            Question.invited_experts.like(f"%;{expert_id_str}"),
                        )
                    )

            # 排序相关的过滤条件需要在计算总数之前应用
            if sort_by == "unanswered":
                stmt = stmt.where(Question.answer_count == 0)

            subquery = stmt.subquery()
            count_stmt = select(func.count()).select_from(subquery)
            total = await session.exec(count_stmt) or 0

            # 排序
            if sort_by == "hot":
                stmt = stmt.order_by(desc(Question.view_count), desc(Question.created_at))
            elif sort_by == "unanswered":
                stmt = stmt.order_by(desc(Question.created_at))
            else:
                stmt = stmt.order_by(desc(Question.created_at))

            stmt = stmt.offset(skip).limit(limit)

            result = await session.exec(stmt)
            return result.all(), total

    async def update(self, question_id: int, **kwargs) -> Question | None:
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

    async def get_business_domains(self) -> list[str]:
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

    async def get_answer_count_by_domain(self) -> list[dict]:
        async with get_async_db_session() as session:
            # 从统计问题回答数量，按业务域分组改成统计问题数量，按业务域分组
            stmt = select(
                Question.business_domain,
                func.count(Question.id).label("question_count"),
            ).group_by(Question.business_domain)
            result = (await session.exec(stmt)).all()
            return [{"business_domain": row.business_domain, "answer_count": row.question_count} for row in result]


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
                round(solved_questions / total_questions, RESOLUTION_RATE_PRECISION) if total_questions else 0.0
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

    async def get_by_id(self, answer_id: int) -> Answer | None:
        """根据ID获取回答"""
        async with get_async_db_session() as session:
            stmt = select(Answer).where(Answer.id == answer_id)
            result = await session.exec(stmt)
            return result.first()

    async def get_by_expertname(self, expert_name: str, question_id: int) -> Answer | None:
        """根据专家名称获取回答"""
        async with get_async_db_session() as session:
            stmt = select(Answer).where(and_(Answer.expert_name == expert_name, Answer.question_id == question_id))
            result = await session.exec(stmt)

            return result.first()

    async def get_by_question_id(
        self, question_id: int, skip: int = 0, limit: int = 100, sort_by: str | None = None
    ) -> tuple[list[Answer], int]:
        """获取问题的所有回答"""
        async with get_async_db_session() as session:
            stmt = select(Answer, func.count().over().label("total")).where(
                and_(Answer.question_id == question_id, Answer.status != 3)
            )
            if sort_by:
                if sort_by == "top":
                    stmt = stmt.order_by(desc(Answer.vote_count), desc(Answer.created_at))
                elif sort_by == "latest":
                    stmt = stmt.order_by(desc(Answer.created_at))
            stmt = stmt.offset(skip).limit(limit)

            result = await session.exec(stmt)
            rows = result.all()  # 获取所有的 Row 对象

            if not rows:
                return [], 0

            # 从第一行中提取出总数，并从每行中提取出 Answer 实体
            total = rows[0].total
            answers = [row.Answer for row in rows]

            return answers, total

    async def update(self, answer_id: int, **kwargs) -> Answer | None:
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

    async def get_answer_vote_count(self, question_id: int) -> int:
        """获取回答的投票数"""
        async with get_async_db_session() as session:
            stmt = select(func.coalesce(func.sum(Answer.vote_count), 0).label("total_vote_count")).where(
                and_(Answer.question_id == question_id, Answer.status != 3)
            )
            result = await session.exec(stmt)
            return result.first() or 0


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
        self, answer_id: int, question_id: int | None = None, skip: int = 0, limit: int = 100
    ) -> tuple[list[Comment], int]:
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

    async def add_question_vote(self, user_id: int, question_id: int) -> QuestionVote | None:
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

    async def add_answer_vote(self, user_id: int, answer_id: int, vote_type: str = "helpful") -> AnswerVote | None:
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
    ) -> tuple[list[QANotification], int]:
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
