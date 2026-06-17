"""F037: transient DB write-conflict retry.

Concurrent writes to a hot row (``message_session`` touched per chat turn) make
DM raise transient conflicts (-6403 deadlock / -7067 mvcc / -7184 object version)
that a full-rollback-then-retry resolves. These tests lock that the decorator
retries those and only those, and gives up after the configured attempts.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from bisheng.core.database import retry as retry_mod
from bisheng.core.database.retry import (
    is_transient_db_conflict,
    retry_on_transient_db_conflict,
)


def _dbapi_error(message: str) -> DBAPIError:
    # Mirror how SQLAlchemy surfaces a dmPython error: the driver exception is
    # carried on ``.orig`` and its str holds the [CODE:...] marker.
    return DBAPIError("UPDATE message_session ...", {}, Exception(message))


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    # Keep the retry loop instant in tests.
    monkeypatch.setattr(retry_mod, "_BASE_BACKOFF_SECONDS", 0.0)


def test_is_transient_recognizes_dm_and_mysql_conflicts():
    for code in ("-6403", "-7067", "-7184", "1213", "1205"):
        assert is_transient_db_conflict(_dbapi_error(f"[CODE:{code}]conflict")) is True
    # A non-conflict DBAPIError and non-DBAPIError must not be treated as transient.
    assert is_transient_db_conflict(_dbapi_error("[CODE:-9999]other")) is False
    assert is_transient_db_conflict(ValueError("boom")) is False


@pytest.mark.asyncio
async def test_async_retries_transient_then_succeeds():
    calls = {"n": 0}

    @retry_on_transient_db_conflict(attempts=4)
    async def op():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _dbapi_error("[CODE:-6403]Deadlock")
        return "ok"

    assert await op() == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_async_non_transient_raises_immediately():
    calls = {"n": 0}

    @retry_on_transient_db_conflict(attempts=4)
    async def op():
        calls["n"] += 1
        raise IntegrityError("dup", {}, Exception("duplicate key"))

    with pytest.raises(IntegrityError):
        await op()
    assert calls["n"] == 1  # not retried


@pytest.mark.asyncio
async def test_async_exhausts_and_reraises_last_conflict():
    calls = {"n": 0}

    @retry_on_transient_db_conflict(attempts=3)
    async def op():
        calls["n"] += 1
        raise _dbapi_error("[CODE:-7067]Too many mvcc conflict")

    with pytest.raises(DBAPIError):
        await op()
    assert calls["n"] == 3


def test_sync_retries_transient_then_succeeds():
    calls = {"n": 0}

    @retry_on_transient_db_conflict(attempts=4)
    def op():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _dbapi_error("[CODE:-7184]object version check failed")
        return 42

    assert op() == 42
    assert calls["n"] == 2
