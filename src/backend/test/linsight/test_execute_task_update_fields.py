"""LinsightExecuteTaskDao.update_fields_by_id must write without reading the row back.

Reading the row (as update_by_id does, twice) loads the growing history CLOB on every
agent step; on DaMeng that leaked worker memory until OOM. The history writers in
state_message_manager rely on this method issuing one UPDATE and nothing else.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select

from bisheng.linsight.domain.models import linsight_execute_task as dao_module
from bisheng.linsight.domain.models.linsight_execute_task import LinsightExecuteTaskDao


def _fake_session_factory(executed: list, opened: list):
    session = AsyncMock()

    async def exec_(statement):
        executed.append(statement)

    session.exec = AsyncMock(side_effect=exec_)

    @asynccontextmanager
    async def factory():
        opened.append(True)
        yield session

    return factory, session


@pytest.mark.asyncio
async def test_update_fields_by_id_issues_one_update_and_no_select(monkeypatch):
    executed, opened = [], []
    factory, session = _fake_session_factory(executed, opened)
    monkeypatch.setattr(dao_module, "get_async_db_session", factory)

    await LinsightExecuteTaskDao.update_fields_by_id("t1", history=[{"step_type": "thinking"}])

    assert len(executed) == 1
    statement = executed[0]
    assert isinstance(statement, Update)
    assert not isinstance(statement, Select)
    assert statement.table.name == "linsight_execute_task"
    assert "history" in {c.key for c in statement._values}
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_fields_by_id_without_fields_does_nothing(monkeypatch):
    executed, opened = [], []
    factory, _session = _fake_session_factory(executed, opened)
    monkeypatch.setattr(dao_module, "get_async_db_session", factory)

    await LinsightExecuteTaskDao.update_fields_by_id("t1")

    assert opened == []
    assert executed == []
