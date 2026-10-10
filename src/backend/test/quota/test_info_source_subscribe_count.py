"""Regression: /quota/effective 500'd with "unhashable type: 'list'".

``_distinct_info_source_ids`` reads one JSON-array column through SQLModel's
``Session.exec``. That call only unwraps the selected column when the statement
is a ``SelectOfScalar`` — build it with sqlalchemy's ``select`` instead and it
returns ``Row`` tuples, so the set comprehension tries to hash the array itself
and every tenant with sourced channels gets a 500.
"""

from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel.sql.expression import SelectOfScalar

from bisheng.role.domain.services.quota_service import QuotaService


class _FakeSession:
    """Mimics the part of Session.exec that this bug turned on: a SelectOfScalar
    yields the column value, a plain Select yields a one-element Row tuple."""

    def __init__(self, values):
        self._values = values
        self.statement = None

    async def exec(self, statement):
        self.statement = statement
        scalar = isinstance(statement, SelectOfScalar)
        rows = [v if scalar else (v,) for v in self._values]
        result = MagicMock()
        result.all.return_value = rows
        return result


@asynccontextmanager
async def _session_ctx(session):
    yield session


@pytest.mark.parametrize("col", ["user_id", "tenant_id"])
async def test_dedupes_source_ids_across_channels(col):
    session = _FakeSession([["a", "b"], ["b", "c"], None])
    with patch(
        "bisheng.core.database.get_async_db_session",
        lambda: _session_ctx(session),
    ):
        ids = await QuotaService._distinct_info_source_ids(col, 1)

    assert ids == {"a", "b", "c"}


async def test_statement_is_a_scalar_select():
    """The guard proper: anything else and exec hands back Row tuples."""
    session = _FakeSession([["a"]])
    with patch(
        "bisheng.core.database.get_async_db_session",
        lambda: _session_ctx(session),
    ):
        await QuotaService._distinct_info_source_ids("user_id", 1)

    assert isinstance(session.statement, SelectOfScalar)


async def test_unknown_column_is_not_queried():
    session = _FakeSession([["a"]])
    with patch(
        "bisheng.core.database.get_async_db_session",
        lambda: _session_ctx(session),
    ):
        assert await QuotaService._distinct_info_source_ids("nope", 1) == set()
    assert session.statement is None
