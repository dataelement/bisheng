from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from bisheng.database.models.base import SQLModelSerializable
from sqlmodel import Column, DateTime, Field, text


# Finetune任务的预置训练集
class PresetTrainBase(SQLModelSerializable):
    id: str = Field(default=None, primary_key=True, description='预置训练文件唯一ID')
    url: str = Field(default='', description='minIo上的文件链接')
    name: str = Field(default='', index=True, description='上传的文件名字')
    user_id: str = Field(default='', index=True, description='创建人ID')
    user_name: str = Field(default='', index=True, description='创建人姓名')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class PresetTrain(PresetTrainBase, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)
