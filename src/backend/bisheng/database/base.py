import uuid
from contextlib import contextmanager, asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy import func
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar

from bisheng.database.service import DatabaseService
from bisheng.settings import settings
from bisheng.utils.logger import logger
from sqlmodel import Session

db_service: 'DatabaseService' = DatabaseService(settings.database_url)


@contextmanager
def session_getter() -> Session:
    """轻量级session context"""
    try:
        session = Session(db_service.engine)
        yield session
    except Exception as e:
        logger.info('Session rollback because of exception:{}', e)
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def async_session_getter() -> AsyncGenerator[AsyncSession, Any]:
    """轻量级异步session context"""
    try:
        async_session = async_sessionmaker(bind=db_service.async_engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            yield session
    except Exception as e:
        logger.info('AsyncSession rollback because of exception:{}', e)
        await session.rollback()
        raise
    finally:
        await session.close()


def get_count(session: Session, q: SelectOfScalar) -> int:
    """
    获取查询结果的数量
    :param session:
    :param q:
    :return:
    """
    count_q = q.with_only_columns(func.count()).order_by(None).select_from(q.get_final_froms()[0])
    iterator = session.exec(count_q)
    for count in iterator:
        return count
    return 0


async def async_get_count(session: AsyncSession, q: SelectOfScalar) -> int:
    """
    获取异步查询结果的数量
    :param session:
    :param q:
    :return:
    """
    count_q = q.with_only_columns(func.count()).order_by(None).select_from(q.get_final_froms()[0])
    iterator = await session.exec(count_q)
    for count in iterator:
        return count
    return 0


def uuid_hex() -> str:
    """
    生成一个UUID的十六进制字符串
    :return: UUID的十六进制字符串
    """
    return uuid.uuid4().hex