import uuid
from contextlib import contextmanager

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


def generate_uuid() -> str:
    """
    生成uuid的字符串
    """
    return uuid.uuid4().hex
