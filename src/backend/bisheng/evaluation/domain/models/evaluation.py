from datetime import datetime
from enum import Enum
from typing import Dict, Optional

from sqlalchemy import Column, DateTime, Integer, Text, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType, UPDATE_TIME_SERVER_DEFAULT


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
    file_path: str = Field(default='', description='Doc. minio address')
    exec_type: str = Field(description='Execute subject categories: assistant/workflow/flow')
    unique_id: str = Field(index=True, description='Unique id of the executing entity')
    version: Optional[int] = Field(default=None, description='Version of workflow or skill id')
    status: int = Field(index=True, default=1,
                        description='Task status: 1 running 2 failed 3 success')
    prompt: str = Field(default='', sa_column=Column(Text), description='Evaluation instruction text')
    result_file_path: str = Field(default='', description='Assessment result minio address')
    result_score: Optional[Dict | str] = Field(default=None, sa_column=Column(JsonType),
                                                description='Final assessment score')
    description: str = Field(default='', sa_column=Column(Text), description='Error description')
    is_delete: int = Field(default=0, description='whether delete')
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class Evaluation(EvaluationBase, table=True):
    __tablename__ = 'evaluation'
    id: int = Field(default=None, primary_key=True, unique=True)
