from contextlib import contextmanager

from sqlalchemy import func
from sqlmodel.sql.expression import  SelectOfScalar

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
