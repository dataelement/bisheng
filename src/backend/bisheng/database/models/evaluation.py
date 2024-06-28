from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, Text, text, func, and_, JSON
from sqlmodel import Field, select


class ExecType(Enum):
    FLOW = 'flow'
    ASSISTANT = 'assistant'


class EvaluationTaskStatus(Enum):
    running = 1
    failed = 2
    success = 3


class EvaluationBase(SQLModelSerializable):
    user_id: int = Field(default=None, index=True)
    file_name: str = Field(default='', description='上传的文件名')
    file_path: str = Field(default='', description='文件 minio 地址')
    exec_type: str = Field(description='执行主体类别。助手或技能 flow 和 assistant')
    unique_id: str = Field(index=True, description='助手或技能唯一ID')
    version: Optional[int] = Field(default=None, description='技能的版本ID')
    status: int = Field(index=True, default=1, description='任务执行状态。1:执行中 2: 执行失败 3:执行成功')
    prompt: str = Field(default='', sa_column=Column(Text), description='评测指令文本')
    result_file_path: str = Field(default='', description='评测结果的 minio 地址')
    result_score: Optional[Dict] = Field(sa_column=Column(JSON), default=None, description='最终评测分数')
    is_delete: int = Field(default=0, description='是否删除')
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Evaluation(EvaluationBase, table=True):
    id: int = Field(default=None, primary_key=True, unique=True)


class EvaluationRead(EvaluationBase):
    id: int
    user_name: Optional[str]


class EvaluationCreate(EvaluationBase):
    pass


class EvaluationDao(EvaluationBase):
    @classmethod
    def get_my_evaluations(cls, user_id: int, page: int, limit: int) -> (List[Evaluation], int):
        with session_getter() as session:
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
        with session_getter() as session:
            data.is_delete = 1
            session.add(data)
            session.commit()
            return data

    @classmethod
    def get_user_one_evaluation(cls, user_id: int, evaluation_id: int) -> Evaluation:
        with session_getter() as session:
            statement = select(Evaluation).where(and_(Evaluation.id == evaluation_id, Evaluation.user_id == user_id))
            return session.exec(statement).first()

    @classmethod
    def get_one_evaluation(cls, evaluation_id: int) -> Evaluation:
        with session_getter() as session:
            statement = select(Evaluation).where(Evaluation.id == evaluation_id)
            return session.exec(statement).first()

    @classmethod
    def update_evaluation(cls, evaluation: Evaluation) -> Evaluation:
        with session_getter() as session:
            session.add(evaluation)
            session.commit()
            session.refresh(evaluation)
            return evaluation
