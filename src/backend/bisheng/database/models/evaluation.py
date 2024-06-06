from datetime import datetime
from typing import Any, List, Optional, Tuple

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, Text, and_, text
from sqlmodel import Field, select
from uuid import UUID


class EvaluationBase(SQLModelSerializable):
    user_id: int = Field(default=None, index=True)
    file_name: str = Field(default='', description='上传的文件名')
    file_path: str = Field(default='', description='文件 minio 地址')
    exec_type: str = Field(default='', description='执行主体类别。助手还是技能')
    unique_id: str = Field(index=True, description='助手或技能唯一ID')
    version: Optional[int] = Field(default=None, description='技能的版本ID')
    status: int = Field(index=True, default=1, description='任务执行状态。1:执行中 2: 执行失败 3:执行成功')
    prompt: str = Field(default='', sa_column=Column(Text), description='评测指令文本')
    result_file_path: str = Field(default='', description='评测结果的 minio 地址')
    result_score: str = Field(default='', description='最终评测分数')
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
    def query_by_id(cls, id: int) -> Evaluation:
        with session_getter() as session:
            return session.get(Evaluation, id)
