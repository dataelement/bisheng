from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import Column, Text, DateTime, text
from sqlmodel import Field, select

from bisheng.database.base import session_getter, get_count
from bisheng.database.models.base import SQLModelSerializable


class InspirationSOPBase(SQLModelSerializable):
    """
    Inspiration SOP模型基类
    """
    name: str = Field(..., index=True, description='SOP名称', max_length=256)
    description: str = Field(default=None, sa_column=Column(Text), description='SOP描述')
    user_id: int = Field(default=0, description='创建人ID')
    content: str = Field(..., description='SOP内容', sa_column=Column(Text))
    rating: int = Field(default=0, ge=0, le=5, description='SOP评分，范围0-5')

    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class InspirationSOP(InspirationSOPBase, table=True):
    """
    Inspiration SOP模型
    """
    __tablename__ = "inspiration_sop"
    id: Optional[int] = Field(default=None, primary_key=True, description='SOP唯一ID')


class InspirationSOPDao(InspirationSOPBase):
    """
    Inspiration SOP数据访问对象
    """

    @classmethod
    def create_sop(cls, sop: InspirationSOP) -> InspirationSOP:
        with session_getter() as session:
            session.add(sop)
            session.commit()
            session.refresh(sop)
            return sop

    @classmethod
    def update_sop(cls, sop: InspirationSOP) -> InspirationSOP:
        with session_getter() as session:
            # 使用Update语句更新SOP
            session.add(sop)
            session.commit()
            session.refresh(sop)
            return sop

    @classmethod
    def get_sop_page(cls, keywords: Optional[str] = None, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        """
        获取SOP分页列表
        """

        statement = select(InspirationSOP)
        if keywords:
            statement = statement.where(
                InspirationSOP.name.ilike(f'%{keywords}%') |
                InspirationSOP.description.ilike(f'%{keywords}%') |
                InspirationSOP.content.ilike(f'%{keywords}%')
            )
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        with session_getter() as session:
            sop_list = session.exec(statement).all()
            sop_list_dict = [sop.model_dump() for sop in sop_list]

            total_count = get_count(session, statement)

        return {
            "total": total_count,
            "current_page": page,
            "page_size": page_size,
            "items": sop_list_dict
        }
