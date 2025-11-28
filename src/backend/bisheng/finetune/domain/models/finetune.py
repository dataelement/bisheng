from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import field_validator, BaseModel, model_validator
from sqlalchemy import Select
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import JSON, Column, DateTime, Field, func, select, text, update, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.utils import generate_uuid


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
    train_data: Optional[List[Dict]] = Field(default=None, sa_column=Column(JSON), description='个人训练数据集信息')
    preset_data: Optional[List[Dict]] = Field(default=None, sa_column=Column(JSON), description='预置训练数据集信息')
    status: int = Field(default=FinetuneStatus.TRAINING.value, index=True, description='训练任务的状态')
    reason: Optional[str] = Field(default='', sa_column=Column(LONGTEXT), description='任务失败原因')
    log_path: Optional[str] = Field(default='', max_length=512, description='训练日志在minio上的路径')
    report: Optional[Dict] = Field(default=None, sa_column=Column(JSON), description='训练任务的评估报告数据')
    user_id: int = Field(default=None, index=True, description='创建人ID')
    user_name: str = Field(default=None, description='创建人姓名')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
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

    @model_validator(mode='before')
    @classmethod
    def validate_all(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        extra_params = values.get('extra_params', None)
        if extra_params is None or not isinstance(extra_params, dict):
            raise ValueError('Finetune.extra_params must be a valid json')

        train_data = values.get('train_data', None)
        cls.validate_train(train_data)

        preset_data = values.get('preset_data', None)
        cls.validate_train(preset_data)
        return values


class Finetune(FinetuneBase, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True, unique=True)


class FinetuneList(BaseModel):
    server: Optional[int] = Field(None, description='关联的RT服务ID')
    server_name: Optional[str] = Field(None, description='关联的RT服务名称')
    status: Optional[List[int]] = Field(None, description='训练任务的状态列表')
    model_name: Optional[str] = Field(None, description='模型名称, 模糊搜索')
    page: Optional[int] = Field(default=1, description='页码')
    limit: Optional[int] = Field(default=10, description='每页条数')
    user_id: Optional[int] = Field(None, description='用户ID')

    def get_select_statement(self) -> (Select, Select):
        """Generate the select and count statements based on the filters."""
        statement = select(Finetune)
        count_statement = select(func.count(Finetune.id))
        if self.server:
            statement = statement.where(Finetune.server == self.server)
            count_statement = count_statement.where(Finetune.server == self.server)
        if self.server_name:
            statement = statement.where(Finetune.server_name == self.server_name)
            count_statement = count_statement.where(Finetune.server_name == self.server_name)
        if self.status:
            statement = statement.where(col(Finetune.status).in_(self.status))
            count_statement = count_statement.where(col(Finetune.status).in_(self.status))
        if self.model_name:
            statement = statement.where(col(Finetune.model_name).like(f'%{self.model_name}%'))
            count_statement = count_statement.where(col(Finetune.model_name).like(f'%{self.model_name}%'))
        if self.user_id:
            statement = statement.where(Finetune.user_id == self.user_id)
            count_statement = count_statement.where(Finetune.user_id == self.user_id)
        if self.page and self.limit:
            offset = (self.page - 1) * self.limit
            statement = statement.offset(offset).limit(self.limit).order_by(col(Finetune.create_time).desc())
        return statement, count_statement


class FinetuneChangeModelName(BaseModel):
    id: str = Field(description='训练任务唯一ID')
    model_name: str


class FinetuneExtraParams(BaseModel):
    gpus: str = Field(..., description='需要使用的GPU卡号')
    val_ratio: float = Field(0.1, ge=0, le=1, description='验证集占比')
    per_device_train_batch_size: int = Field(1, description='批处理的大小')
    learning_rate: float = Field(0.00005, ge=0, le=1, description='学习率')
    num_train_epochs: int = Field(3, gt=0, description='迭代轮数')
    max_seq_len: int = Field(8192, gt=0, description='最大序列长度')
    cpu_load: str = Field('false', description='是否cpu载入')

    @field_validator('per_device_train_batch_size', mode='before')
    @classmethod
    def validate_batch_size(cls, v: str):
        try:
            batch_size = int(v)
            if batch_size != 1:
                if batch_size % 2 != 0:
                    raise ValueError('per_device_train_batch_size must be 1 or even number')
            return batch_size
        except Exception as e:
            raise ValueError(f'per_device_train_batch_size must be an integer {e}')

    @field_validator('gpus', mode='before')
    @classmethod
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
    async def insert_one(cls, data: Finetune) -> Finetune:
        async with get_async_db_session() as session:
            session.add(data)
            await session.commit()
            await session.refresh(data)
        return data

    @classmethod
    async def update_job(cls, finetune: Finetune) -> Finetune:
        if not finetune.id:
            raise ValueError('Finetune.id must not be empty when update')
        async with get_async_db_session() as session:
            session.add(finetune)
            await session.commit()
            await session.refresh(finetune)
        return finetune

    @classmethod
    async def find_job(cls, job_id: str) -> Finetune | None:
        async with get_async_db_session() as session:
            statement = select(Finetune).where(Finetune.id == job_id)
            return (await session.exec(statement)).first()

    @classmethod
    async def find_job_by_model_name(cls, model_name: str) -> Finetune | None:
        async with get_async_db_session() as session:
            statement = select(Finetune).where(Finetune.model_name == model_name)
            return (await session.exec(statement)).first()

    @classmethod
    async def find_job_by_model_id(cls, model_id: int) -> Finetune | None:
        async with get_async_db_session() as session:
            statement = select(Finetune).where(Finetune.model_id == model_id)
            return (await session.exec(statement)).first()

    @classmethod
    async def change_status(cls, job_id: str, old_status: int, status: int) -> bool:
        update_statement = update(Finetune).where(col(Finetune.id) == job_id,
                                                  col(Finetune.status) == old_status).values(status=status)
        async with get_async_db_session() as session:
            update_ret = await session.exec(update_statement)
            await session.commit()
            return update_ret.rowcount != 0

    @classmethod
    async def delete_job(cls, job: Finetune) -> bool:
        if not job or not job.id:
            raise ValueError('Finetune job to delete must not be None, and id must not be empty')
        async with get_async_db_session() as session:
            await session.delete(job)
            await session.commit()
            return True

    @classmethod
    async def find_jobs(cls, finetune_list: FinetuneList) -> (List[Finetune], int):
        select_statement, count_statement = finetune_list.get_select_statement()
        async with get_async_db_session() as session:
            return (await session.exec(select_statement)).all(), await session.scalar(count_statement)

    @classmethod
    async def get_server_filters(cls) -> List[str]:
        async with get_async_db_session() as session:
            statement = select(Finetune.server_name).distinct()
            return (await session.exec(statement)).all()
