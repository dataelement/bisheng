from datetime import datetime
from typing import Optional, Dict, Any, List, Literal
from uuid import UUID

from loguru import logger
from sqlalchemy import Column, Text, DateTime, text, CHAR, ForeignKey
from sqlmodel import Field, select, delete, col

from bisheng.api.v1.schema.inspiration_schema import SOPManagementUpdateSchema
from bisheng.database.base import async_session_getter, async_get_count
from bisheng.database.models.base import SQLModelSerializable


class LinsightSOPBase(SQLModelSerializable):
    """
    Inspiration SOP模型基类
    """
    name: str = Field(..., description='SOP名称', sa_column=Column(Text, nullable=False))
    description: Optional[str] = Field(default=None, description='SOP描述', sa_column=Column(Text))
    user_id: int = Field(..., description='用户ID', foreign_key="user.user_id", nullable=False)
    content: str = Field(..., description='SOP内容',
                         sa_column=Column(Text, nullable=False, comment="SOP内容"))

    rating: Optional[int] = Field(None, ge=0, le=5, description='SOP评分，范围0-5')

    vector_store_id: Optional[str] = Field(..., description='向量存储ID',
                                           sa_column=Column(CHAR(36), nullable=False, comment="向量存储ID"))

    linsight_session_id: Optional[str] = Field(default=None, description='灵思会话ID',
                                                        sa_column=Column(CHAR(36),
                                                                         ForeignKey("message_session.chat_id"),
                                                                         nullable=True))


class LinsightSOP(LinsightSOPBase, table=True):
    """
    Inspiration SOP模型
    """
    __tablename__ = "linsight_sop"
    id: Optional[int] = Field(default=None, primary_key=True, description='SOP唯一ID')
    create_time: datetime = Field(default_factory=datetime.now, description='创建时间',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class LinsightSOPDao(LinsightSOPBase):
    """
    Inspiration SOP数据访问对象
    """

    @classmethod
    async def create_sop(cls, sop: LinsightSOP) -> LinsightSOP:
        async with async_session_getter() as session:
            session.add(sop)
            await session.commit()
            await session.refresh(sop)
            return sop

    @classmethod
    async def update_sop(cls, sop_obj: SOPManagementUpdateSchema) -> LinsightSOP:
        async with async_session_getter() as session:
            # 使用Update语句更新SOP
            statement = select(LinsightSOP).where(LinsightSOP.id == sop_obj.id)
            result = await session.exec(statement)
            sop = result.first()
            if not sop:
                raise ValueError("SOP not found")

            # 将sop_obj的字段值更新到sop实例中
            for key, value in sop_obj.model_dump().items():
                if hasattr(sop, key):
                    setattr(sop, key, value)

            sop.update_time = datetime.now()  # 更新修改时间
            session.add(sop)
            await session.commit()
            await session.refresh(sop)
            return sop

    @classmethod
    async def get_sop_page(cls, keywords: Optional[str] = None, sort: Literal["asc", "desc"] = "desc", page: int = 1,
                           page_size: int = 10) -> Dict[str, Any]:
        """
        获取SOP分页列表
        """

        statement = select(LinsightSOP)
        if keywords:
            statement = statement.where(
                LinsightSOP.name.ilike(f'%{keywords}%') |
                LinsightSOP.description.ilike(f'%{keywords}%') |
                LinsightSOP.content.ilike(f'%{keywords}%')
            )

        # 根据 rating 和 create_time 排序
        if sort == "asc":
            statement = statement.order_by(col(LinsightSOP.rating).asc(), col(LinsightSOP.create_time).asc())
        else:
            statement = statement.order_by(col(LinsightSOP.rating).desc(), col(LinsightSOP.create_time).desc())


        async with async_session_getter() as session:
            total_count = await async_get_count(session, statement)
            statement = statement.offset((page - 1) * page_size).limit(page_size)
            result = (await session.exec(statement)).all()

        return {
            "total": total_count,
            "current_page": page,
            "page_size": page_size,
            "items": [result.model_dump() for result in result]
        }

    @classmethod
    async def get_sops_by_ids(cls, sop_ids: List[int]) -> List[LinsightSOP]:
        """
        根据SOP ID列表获取SOP对象
        """
        async with async_session_getter() as session:
            statement = select(LinsightSOP).where(col(LinsightSOP.id).in_(sop_ids))
            result = await session.exec(statement)
            sop_list = result.all()
            return sop_list

    @classmethod
    async def remove_sop(cls, sop_ids: List[int]) -> bool:
        """
        删除SOP
        """
        async with async_session_getter() as session:
            delete_statement = delete(LinsightSOP).where(col(LinsightSOP.id).in_(sop_ids))
            result = await session.exec(delete_statement)
            await session.commit()
            logger.info(f"Deleted {result.rowcount} SOP(s) with IDs: {sop_ids}")
            return True

    @classmethod
    async def get_sop_by_session_id(cls, session_id: str) -> Optional[LinsightSOP]:
        """
        根据灵思会话ID获取SOP
        """
        async with async_session_getter() as session:
            statement = select(LinsightSOP).where(LinsightSOP.linsight_session_id == session_id)
            result = await session.exec(statement)
            sop = result.first()
            return sop if sop else None

    @classmethod
    async def get_sop_by_vector_store_ids(cls, vector_store_ids: List[str]) -> List[LinsightSOP]:
        """
        根据向量存储ID列表获取SOP对象
        """
        async with async_session_getter() as session:
            statement = select(LinsightSOP).where(col(LinsightSOP.vector_store_id).in_(vector_store_ids))
            result = await session.exec(statement)
            sop_list = result.all()
            return sop_list