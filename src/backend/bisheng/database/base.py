import uuid
from sqlalchemy import func, Select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import Session


def get_count(session: Session, q: Select) -> int:
    """
    Number of fetch query results
    :param session:
    :param q:
    :return:
    """
    count_q = q.with_only_columns(func.count()).order_by(None).select_from(q.get_final_froms()[0])
    iterator = session.exec(count_q)
    for count in iterator:
        return count
    return 0


async def async_get_count(session: AsyncSession, q: Select) -> int:
    """
    Get the number of asynchronous query results
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
    Generate oneUUIDhexadecimal string
    :return: UUIDhexadecimal string
    """
    return uuid.uuid4().hex