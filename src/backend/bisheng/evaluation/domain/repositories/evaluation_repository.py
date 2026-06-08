from typing import List

from sqlalchemy import and_, func
from sqlmodel import select

from bisheng.core.database import get_sync_db_session
from bisheng.evaluation.domain.models.evaluation import Evaluation, ExecType


class EvaluationRepository:
    @classmethod
    def get_my_evaluations(cls, user_id: int, page: int, limit: int) -> tuple[List[Evaluation], int]:
        with get_sync_db_session() as session:
            statement = select(Evaluation).where(
                Evaluation.is_delete == 0, Evaluation.user_id == user_id,
                Evaluation.exec_type != ExecType.FLOW.value)
            count_statement = session.query(func.count(Evaluation.id)).where(
                Evaluation.is_delete == 0, Evaluation.user_id == user_id,
                Evaluation.exec_type != ExecType.FLOW.value)
            statement = statement.offset((page - 1) * limit).limit(limit).order_by(
                Evaluation.update_time.desc())
            return session.exec(statement).all(), session.exec(count_statement).scalar()

    @classmethod
    def delete_evaluation(cls, data: Evaluation) -> Evaluation:
        with get_sync_db_session() as session:
            data.is_delete = 1
            session.add(data)
            session.commit()
            return data

    @classmethod
    def get_user_one_evaluation(cls, user_id: int, evaluation_id: int) -> Evaluation:
        with get_sync_db_session() as session:
            statement = select(Evaluation).where(
                and_(Evaluation.id == evaluation_id, Evaluation.user_id == user_id))
            return session.exec(statement).first()

    @classmethod
    def get_one_evaluation(cls, evaluation_id: int) -> Evaluation:
        with get_sync_db_session() as session:
            return session.exec(select(Evaluation).where(Evaluation.id == evaluation_id)).first()

    @classmethod
    def update_evaluation(cls, evaluation: Evaluation) -> Evaluation:
        with get_sync_db_session() as session:
            session.add(evaluation)
            session.commit()
            session.refresh(evaluation)
            return evaluation
