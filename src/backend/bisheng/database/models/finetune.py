from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from pydantic import validator
from sqlmodel import JSON, TEXT, Column, DateTime, Field, select, text, update


class TrainMethod(Enum):
    FULL = 'full'
    FREEZE = 'freeze'
    LORA = 'lora'


class FinetuneStatus(Enum):
    # 训练中
    TRAINING = 1
    # 训练失败
    FAILED = 2
    # 任务中止
    CANCEL = 3
    # 训练成功
    SUCCESS = 4
    # 发布完成
    PUBLISHED = 5


class FinetuneBase(SQLModelSerializable):
    id: str = Field(default=None, nullable=False, primary_key=True, description='唯一ID')
    server: int = Field(default=0, index=True, description='关联的RT服务ID')
    base_model: int = Field(default=0, index=True, description='基础模型ID')
    model_id: int = Field(default=0, index=True, description='已发布的模型ID')
    model_name: str = Field(index=True, max_length=50, description='训练模型的名称')
    method: str = Field(default=TrainMethod.FULL.value, nullable=False, max_length=20, description='训练方法')
    extra_params: Dict = Field(sa_column=Column(JSON), description='训练任务所需的额外参数')
    train_data: Optional[Dict] = Field(sa_column=Column(JSON), description='个人训练数据集信息')
    preset_data: Optional[Dict] = Field(sa_column=Column(JSON), description='预置训练数据集信息')
    status: int = Field(default=FinetuneStatus.TRAINING.TRAINING, index=True, description='训练任务的状态')
    reason: str = Field(default='', sa_column=Column(TEXT), description='任务失败原因')
    user_id: int = Field(default=None, index=True, description='创建人ID')
    user_name: str = Field(default=None, description='创建人姓名')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    # 检查训练集数据格式
    @classmethod
    def validate_train(cls, v: Any):
        if v is None:
            return v
        if v is None or not isinstance(v, list):
            raise ValueError('Finetune.train_data must be a list')
        for one in v:
            if not (one.get('name', None) and one.get('url', None)):
                raise ValueError('Finetune.train_data each item must be {name:"",url:"",num:0}')
        return v

    @validator('extra_params')
    def validate_params(cls, v: Optional[Dict]):
        if v is None or not isinstance(v, dict):
            raise ValueError('Finetune.extra_params must be a valid json')
        return v

    @validator('train_data')
    def validate_train_data(cls, v: Optional[Dict]):
        return cls.validate_train(v)

    @validator('preset_data')
    def validate_preset_data(cls, v: Optional[Dict]):
        return cls.validate_train(v)


class Finetune(FinetuneBase, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)


class FinetuneDao(FinetuneBase):

    @classmethod
    def insert_one(cls, data: Finetune) -> Finetune:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
        return data

    @classmethod
    def find_job(cls, job_id: str) -> Finetune:
        with session_getter() as session:
            statement = select(Finetune).where(Finetune.id == job_id)
            ret = session.exec(statement).first()
        return ret

    @classmethod
    def change_status(cls, job_id: str, old_status: int, status: int) -> bool:
        with session_getter() as session:
            update_statement = update(Finetune).where(
                Finetune.id == job_id, Finetune.status == old_status).values(status=status)
            update_ret = session.exec(update_statement)
            return update_ret.rowcount != 0

    @classmethod
    def delete_job(cls, job: Finetune) -> bool:
        with session_getter() as session:
            session.delete(job)
            session.commit()
            return True

    @classmethod
    def update_job(cls, job: Finetune) -> bool:
        with session_getter() as session:
            session.add(job)
            session.commit()
            session.refresh(job)
            return True


class FinetuneCreate(FinetuneBase):
    id: UUID = Field(default_factory=uuid4)
    server: int
    base_model: int
    method: TrainMethod
