from typing import List
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime

from sqlalchemy import Column, DateTime, Text
from sqlmodel import Field
from sqlmodel import select
from sqlalchemy import JSON, Column, DateTime, Text, and_, func, or_, text
from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable


class TTSCacheBase(SQLModelSerializable):
    msg: str = Field(sa_column=Column(Text), description="原始文本")
    model_id: int = Field(index=True, description="模型ID")
    md5: str = Field(index=True, description="文本的MD5值")
    voice_url: str = Field(sa_column=Column(Text), description="生成的语音URL")
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class TTSCache(TTSCacheBase, table=True):
    __tablename__ = "tts_cache"

    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)


class TTSCacheDao(TTSCacheBase):
    @classmethod
    def insert_one(cls, data: TTSCache) -> TTSCache:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def insert_batch(cls, records: List[TTSCache]) -> List[TTSCache]:
        with session_getter() as session:
            try:
                session.add_all(records)
                session.commit()
                for record in records:
                    session.refresh(record)
                return records
            except Exception as e:
                session.rollback()
                raise e

    @classmethod
    def get_by_md5_model_after(cls, md5: str, model_id: int, after_time: datetime) -> Optional[TTSCache]:
        with session_getter() as session:
            return session.exec(
                select(TTSCache)
                .where(
                    TTSCache.md5 == md5,
                    TTSCache.model_id == model_id,
                    TTSCache.create_time > after_time
                )
                .order_by(TTSCache.create_time.desc())  # 按创建时间降序排列
            ).first()


