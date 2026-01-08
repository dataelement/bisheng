from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict

from sqlalchemy import Column, DateTime, Text, text, func, and_, JSON
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session


class ExecType(Enum):
    FLOW = 'flow'
    ASSISTANT = 'assistant'
    WORKFLOW = 'workflow'


class EvaluationTaskStatus(Enum):
    running = 1
    failed = 2
    success = 3


class EvaluationBase(SQLModelSerializable):
    user_id: int = Field(default=None, index=True)
    file_name: str = Field(default='', description='Uploaded filename')
    file_path: str = Field(default='', description='Doc. minio <g id="Bold">Address:</g>')
    exec_type: str = Field(description='Execute subject categories. Assistants, Skills, Workflows, ReferenceExecTypeEnum')
    unique_id: str = Field(index=True, description='Unique to the executing entityID')
    version: Optional[int] = Field(default=None, description='Version of workflow or skillID')
    status: int = Field(index=True, default=1, description='Task Execution Status: 1:Executing "{0}" 2: execute fail 3:execute success')
    prompt: str = Field(default='', sa_column=Column(Text), description='Evaluation Instruction Text')
    result_file_path: str = Field(default='', description='of the assessment results minio <g id="Bold">Address:</g>')
    result_score: Optional[Dict | str] = Field(default=None, sa_column=Column(JSON), description='Final Assessment Score')
    description: str = Field(default='', sa_column=Column(Text), description='Error description information')
    is_delete: int = Field(default=0, description='whether delete')
    create_time: Optional[datetime] = Field(default=None,
                                            sa_column=Column(DateTime, nullable=False,
                                                             server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Evaluation(EvaluationBase, table=True):
    id: int = Field(default=None, primary_key=True, unique=True)


class EvaluationRead(EvaluationBase):
    id: int
    user_name: Optional[str] = None


class EvaluationCreate(EvaluationBase):
    pass


class EvaluationDao(EvaluationBase):
    @classmethod
    def get_my_evaluations(cls, user_id: int, page: int, limit: int) -> (List[Evaluation], int):
        with get_sync_db_session() as session:
            statement = select(Evaluation).where(and_(Evaluation.is_delete == 0, Evaluation.user_id == user_id))
            count_statement = session.query(func.count(
                Evaluation.id)).where(and_(Evaluation.is_delete == 0, Evaluation.user_id == user_id))
            statement = statement.offset(
                (page - 1) * limit
            ).limit(limit).order_by(
                Evaluation.update_time.desc()
            )
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
            statement = select(Evaluation).where(and_(Evaluation.id == evaluation_id, Evaluation.user_id == user_id))
            return session.exec(statement).first()

    @classmethod
    def get_one_evaluation(cls, evaluation_id: int) -> Evaluation:
        with get_sync_db_session() as session:
            statement = select(Evaluation).where(Evaluation.id == evaluation_id)
            return session.exec(statement).first()

    @classmethod
    def update_evaluation(cls, evaluation: Evaluation) -> Evaluation:
        with get_sync_db_session() as session:
            session.add(evaluation)
            session.commit()
            session.refresh(evaluation)
            return evaluation
