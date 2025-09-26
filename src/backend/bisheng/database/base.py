import uuid
from sqlalchemy import func
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar
from sqlmodel import Session



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