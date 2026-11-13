"""Single seam for database sessions used by memory repositories (tests patch it)."""

from bisheng.core.database import get_async_db_session, get_sync_db_session


def async_session():
    return get_async_db_session()


def sync_session():
    return get_sync_db_session()
