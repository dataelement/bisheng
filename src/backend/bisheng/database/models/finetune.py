from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from pydantic import BaseModel, validator
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import JSON, Column, DateTime, Field, func, select, text, update


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
    server_name: str = Field(default='', index=True, description='RT服务名称')
    rt_endpoint: str = Field(default='', description='RT服务地址')
    sft_endpoint: str = Field(default='', description='FT服务地址')
    base_model: int = Field(default=0, index=True, description='基础模型ID')
    base_model_name: str = Field(max_length=50, description='基础模型名称')
    root_model_name: str = Field(default='', description='根基础模型名称，即最初始的模型名称')
    model_id: int = Field(default=0, index=True, description='已发布的训练模型ID')
    model_name: str = Field(index=True, max_length=50, description='训练模型的名称')
    method: str = Field(default=TrainMethod.FULL.value, nullable=False, max_length=20, description='训练方法')
    extra_params: Dict = Field(sa_column=Column(JSON), description='训练任务所需的额外参数')
    train_data: Optional[List[Dict]] = Field(sa_column=Column(JSON), description='个人训练数据集信息')
    preset_data: Optional[List[Dict]] = Field(sa_column=Column(JSON), description='预置训练数据集信息')
    status: int = Field(default=FinetuneStatus.TRAINING.value, index=True, description='训练任务的状态')
    reason: Optional[str] = Field(default='', sa_column=Column(LONGTEXT), description='任务失败原因')
    log_path: Optional[str] = Field(default='', max_length=512, description='训练日志在minio上的路径')
    report: Optional[Dict] = Field(sa_column=Column(JSON), description='训练任务的评估报告数据')
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


class FinetuneList(BaseModel):
    server: Optional[int] = Field(description='关联的RT服务ID')
    server_name: Optional[str] = Field(description='关联的RT服务名称')
    status: Optional[List[int]] = Field(description='训练任务的状态')
    model_name: Optional[str] = Field(description='模型名称, 模糊搜索')
    page: Optional[int] = Field(default=1, description='页码')
    limit: Optional[int] = Field(default=10, description='每页条数')


class FinetuneChangeModelName(BaseModel):
    id: UUID = Field(description='训练任务唯一ID')
    model_name: str


class FinetuneExtraParams(BaseModel):
    gpus: str = Field(..., description='需要使用的GPU卡号')
    val_ratio: float = Field(0.1, ge=0, le=1, description='验证集占比')
    per_device_train_batch_size: int = Field(1, description='批处理的大小')
    learning_rate: float = Field(0.00005, ge=0, le=1, description='学习率')
    num_train_epochs: int = Field(3, gt=0, description='迭代轮数')
    max_seq_len: int = Field(8192, gt=0, description='最大序列长度')
    cpu_load: str = Field('false', description='是否cpu载入')

    @validator('per_device_train_batch_size')
    def validate_batch_size(cls, v: str):
        try:
            batch_size = int(v)
            if batch_size != 1:
                if batch_size % 2 != 0:
                    raise ValueError('per_device_train_batch_size must be 1 or even number')
            return batch_size
        except Exception as e:
            raise ValueError(f'per_device_train_batch_size must be an integer {e}')

    @validator('gpus')
    def validate_gpus(cls, v: str):
        try:
            gpu_list = v.split(',')
            gpus = ''
            for one in gpu_list:
                if not one:
                    continue
                if not one.isdigit():
                    raise ValueError('gpus number must be integer')
                gpus += one + ','
            gpus = gpus[:-1]
            if not gpus:
                raise ValueError('gpus must not be empty')
            return gpus
        except Exception as e:
            raise ValueError(f'gpus must be an str {e}')


class FinetuneDao(FinetuneBase):

    @classmethod
    def insert_one(cls, data: Finetune) -> Finetune:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
        return data

    @classmethod
    def update_job(cls, finetune: Finetune) -> Finetune:
        with session_getter() as session:
            session.add(finetune)
            session.commit()
            session.refresh(finetune)
        return finetune

    @classmethod
    def find_job(cls, job_id: UUID) -> Finetune | None:
        with session_getter() as session:
            statement = select(Finetune).where(Finetune.id == job_id)
            return session.exec(statement).first()

    @classmethod
    def find_job_by_model_name(cls, model_name: str) -> Finetune | None:
        with session_getter() as session:
            statement = select(Finetune).where(Finetune.model_name == model_name)
            return session.exec(statement).first()

    @classmethod
    def find_job_by_model_id(cls, model_id: int) -> Finetune | None:
        with session_getter() as session:
            statement = select(Finetune).where(Finetune.model_id == model_id)
            return session.exec(statement).first()

    @classmethod
    def change_status(cls, job_id: UUID, old_status: int, status: int) -> bool:
        with session_getter() as session:
            update_statement = update(Finetune).where(
                Finetune.id == job_id, Finetune.status == old_status).values(status=status)
            update_ret = session.exec(update_statement)
            session.commit()
            return update_ret.rowcount != 0

    @classmethod
    def delete_job(cls, job: Finetune) -> bool:
        with session_getter() as session:
            session.delete(job)
            session.commit()
            return True

    @classmethod
    def find_jobs(cls, finetune_list: FinetuneList) -> (List[Finetune], int):
        offset = (finetune_list.page - 1) * finetune_list.limit
        with session_getter() as session:
            statement = select(Finetune)
            count_statement = session.query(func.count(Finetune.id))
            if finetune_list.server:
                statement = statement.where(Finetune.server == finetune_list.server)
                count_statement = count_statement.filter(Finetune.server == finetune_list.server)
            if finetune_list.server_name:
                statement = statement.where(Finetune.server_name == finetune_list.server_name)
                count_statement = count_statement.filter(Finetune.server_name == finetune_list.server_name)
            if finetune_list.status:
                statement = statement.where(Finetune.status.in_(finetune_list.status))
                count_statement = count_statement.filter(Finetune.status.in_(finetune_list.status))
            if finetune_list.model_name:
                statement = statement.where(Finetune.model_name.like(f'%{finetune_list.model_name}%'))
                count_statement = count_statement.filter(Finetune.model_name.like(f'%{finetune_list.model_name}%'))
            statement = statement.offset(offset).limit(finetune_list.limit).order_by(Finetune.create_time.desc())
            all_jobs = session.exec(statement).all()
            return all_jobs, count_statement.scalar()

    @classmethod
    def get_server_filters(cls) -> List[str]:
        with session_getter() as session:
            statement = select(Finetune.server_name).distinct()
            result = session.exec(statement).all()
            return result
