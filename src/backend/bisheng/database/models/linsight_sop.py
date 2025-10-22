from datetime import datetime
from typing import Optional, Dict, Any, List, Literal

from loguru import logger
from sqlalchemy import update
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import Field, select, delete, col, or_, func, Column, Text, DateTime, text, CHAR

from bisheng.api.v1.schema.inspiration_schema import SOPManagementUpdateSchema
from bisheng.core.database import get_async_db_session
from bisheng.database.base import async_get_count
from bisheng.database.models.base import SQLModelSerializable


class LinsightSOPBase(SQLModelSerializable):
    """
    Inspiration SOP模型基类
    """
    name: str = Field(..., description='SOP名称', sa_column=Column(Text, nullable=False))
    description: Optional[str] = Field(default=None, description='SOP描述', sa_column=Column(Text))
    user_id: int = Field(..., description='用户ID', foreign_key="user.user_id", nullable=False)
    content: str = Field(..., description='SOP内容',
                         sa_column=Column(LONGTEXT, nullable=False, comment="SOP内容"))

    rating: Optional[int] = Field(default=0, ge=0, le=5, description='SOP评分，范围0-5')
    showcase: Optional[bool] = Field(default=False, index=True, description='是否作为精选案例在首页展示')
    vector_store_id: Optional[str] = Field(..., description='向量存储ID',
                                           sa_column=Column(CHAR(36), nullable=False, comment="向量存储ID"))

    linsight_version_id: Optional[str] = Field(default=None,
                                               description='灵思会话版本ID，用来查询精选案例的运行结果',
                                               sa_column=Column(CHAR(36), nullable=True))
    create_time: datetime = Field(default_factory=datetime.now, description='创建时间',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class LinsightSOP(LinsightSOPBase, table=True):
    """
    Inspiration SOP模型
    """
    __tablename__ = "linsight_sop"
    id: Optional[int] = Field(default=None, primary_key=True, description='SOP唯一ID')


class LinsightSOPRecord(SQLModelSerializable, table=True):
    """
    灵思SOP运行记录表，记录灵思执行过程中产生的sop
    """
    __tablename__ = "linsight_sop_record"
    id: Optional[int] = Field(default=None, primary_key=True, description='SOP记录唯一ID')
    name: str = Field(..., description='SOP名称', sa_column=Column(Text, nullable=False))
    description: Optional[str] = Field(default=None, description='SOP描述', sa_column=Column(Text))
    user_id: int = Field(..., description='用户ID', foreign_key="user.user_id", nullable=False)
    content: str = Field(..., description='SOP内容',
                         sa_column=Column(LONGTEXT, nullable=False, comment="SOP内容"))

    rating: Optional[int] = Field(default=0, ge=0, le=5, description='SOP评分，范围0-5')
    execute_feedback: Optional[str] = Field(None, description='执行结果反馈信息', sa_type=Text, nullable=True)
    linsight_version_id: Optional[str] = Field(default=None, description='灵思会话版本id，同步评分')
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
        async with get_async_db_session() as session:
            session.add(sop)
            await session.commit()
            await session.refresh(sop)
            return sop

    @classmethod
    async def update_sop(cls, sop_obj: SOPManagementUpdateSchema) -> LinsightSOP:
        async with get_async_db_session() as session:
            # 使用Update语句更新SOP
            statement = select(LinsightSOP).where(LinsightSOP.id == sop_obj.id)
            result = await session.exec(statement)
            sop = result.first()
            if not sop:
                raise ValueError("SOP not found")

            # 将sop_obj的字段值更新到sop实例中
            for key, value in sop_obj.model_dump().items():
                if hasattr(sop, key) and value is not None:
                    setattr(sop, key, value)

            sop.update_time = datetime.now()  # 更新修改时间
            session.add(sop)
            await session.commit()
            await session.refresh(sop)
            return sop

    @classmethod
    async def get_sop_page(cls, keywords: Optional[str] = None, showcase: bool = None,
                           sort: Literal["asc", "desc"] = "desc", page: int = 1,
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
            statement = statement.order_by(col(LinsightSOP.rating).asc(), col(LinsightSOP.update_time).asc())
        else:
            statement = statement.order_by(col(LinsightSOP.rating).desc(), col(LinsightSOP.update_time).desc())

        if showcase is not None:
            statement = statement.where(LinsightSOP.showcase == showcase)

        async with get_async_db_session() as session:
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
        async with get_async_db_session() as session:
            statement = select(LinsightSOP).where(col(LinsightSOP.id).in_(sop_ids))
            result = await session.exec(statement)
            sop_list = result.all()
            return sop_list

    @classmethod
    async def get_sops_by_names(cls, names: list[str]) -> List[LinsightSOP]:
        """
        根据SOP名称列表获取SOP对象
        """
        statement = select(LinsightSOP).where(col(LinsightSOP.name).in_(names))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            sop_list = result.all()
            return sop_list

    @classmethod
    async def remove_sop(cls, sop_ids: List[int]) -> bool:
        """
        删除SOP
        """
        async with get_async_db_session() as session:
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
        async with get_async_db_session() as session:
            statement = select(LinsightSOP).where(LinsightSOP.linsight_session_id == session_id)
            result = await session.exec(statement)
            sop = result.first()
            return sop if sop else None

    @classmethod
    async def get_sop_by_vector_store_ids(cls, vector_store_ids: List[str]) -> List[LinsightSOP]:
        """
        根据向量存储ID列表获取SOP对象
        """
        async with get_async_db_session() as session:
            statement = select(LinsightSOP).where(col(LinsightSOP.vector_store_id).in_(vector_store_ids))
            result = await session.exec(statement)
            sop_list = result.all()
            return sop_list

    @classmethod
    async def get_all_sops(cls) -> List[LinsightSOP]:
        """
        获取所有SOP
        """
        async with get_async_db_session() as session:
            statement = select(LinsightSOP)
            result = await session.exec(statement)
            sop_list = result.all()
            return sop_list

    @classmethod
    async def create_sop_record(cls, sop_record: LinsightSOPRecord) -> LinsightSOPRecord:
        """
        插入一条SOP记录
        """
        async with get_async_db_session() as session:
            session.add(sop_record)
            await session.commit()
            await session.refresh(sop_record)
            return sop_record

    @classmethod
    async def _filter_sop_record_statement(cls, statement, keywords: str = None, user_ids: list[int] = None) -> select:
        """
        构建SOP记录的查询语句
        """
        or_params = []
        if keywords:
            or_params.extend([
                LinsightSOPRecord.name.like(f'%{keywords}%'),
                LinsightSOPRecord.description.like(f'%{keywords}%'),
                LinsightSOPRecord.content.like(f'%{keywords}%')
            ])
        if user_ids:
            or_params.append(LinsightSOPRecord.user_id.in_(user_ids))
        if or_params:
            statement = statement.where(or_(*or_params))
        return statement

    @classmethod
    async def filter_sop_record(cls, keywords: str = None, user_ids: list[int] = None, page: int = None,
                                page_size: int = None, sort: str = None) -> List[LinsightSOPRecord]:
        """
        获取所有SOP记录, 关键字匹配name、description、content。user_ids为用户ID列表。筛选条件之间是or的关系
        """
        statement = select(LinsightSOPRecord)
        statement = await cls._filter_sop_record_statement(statement, keywords, user_ids)
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        if sort == "asc":
            statement = statement.order_by(col(LinsightSOPRecord.create_time).asc())
        else:
            statement = statement.order_by(col(LinsightSOPRecord.create_time).desc())

        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def count_sop_record(cls, keywords: str = None, user_ids: list[int] = None) -> int:
        """
        统计SOP记录数量
        """
        statement = select(func.count(LinsightSOPRecord.id))
        statement = await cls._filter_sop_record_statement(statement, keywords, user_ids)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def get_sop_record_by_ids(cls, ids: list[int]) -> List[LinsightSOPRecord]:
        """
        根据SOP记录ID列表获取SOP记录对象
        """
        statement = select(LinsightSOPRecord).where(col(LinsightSOPRecord.id).in_(ids))

        async with get_async_db_session() as session:
            result = await session.exec(statement)
            sop_record_list = result.all()
            return sop_record_list

    @classmethod
    async def update_sop_record_score(cls, linsight_version_id: str, rating: int) -> bool:
        """
        更新SOP记录的评分
        """
        statement = update(LinsightSOPRecord).where(
            col(LinsightSOPRecord.linsight_version_id) == linsight_version_id).values(rating=rating)
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.commit()
            return True

    @classmethod
    async def update_sop_record_feedback(cls, linsight_version_id: str, execute_feedback: str) -> bool:
        """
        更新SOP记录的执行反馈
        """
        statement = update(LinsightSOPRecord).where(
            col(LinsightSOPRecord.linsight_version_id) == linsight_version_id).values(execute_feedback=execute_feedback)
        async with async_session_getter() as session:
            await session.exec(statement)
            await session.commit()
            return True

    @classmethod
    async def set_sop_showcase(cls, sop_id: int, showcase: bool) -> bool:
        """
        设置SOP是否作为精选案例在首页展示
        """
        statement = update(LinsightSOP).where(
            col(LinsightSOP.id) == sop_id).values(showcase=showcase)
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.commit()
            return True
