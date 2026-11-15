"""F003 T006: application-usage tab — usage type, org filter, type whitelist.

Real ``get_session_list`` over one SQLite file: the list statement through a
sync session (the DAO helpers are patched to it), the task-version lookup
through an aiosqlite session, so the ``EXISTS`` clause and the per-page batch
query both execute.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.org_snapshot import DEPT_NONE, DeptSelection
from bisheng.database.models.session import MessageSession
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from test.fixtures.table_definitions import TABLE_DEFINITIONS

TENANT = 2
# chat_id → (flow_type, task versions, operator_dept_id)
_SESSIONS = {
    "asst": (5, 0, 3),
    "wf": (10, 0, 3),
    "ws-daily": (15, 0, 3),
    "ws-task": (15, 2, 3),
    "linsight": (20, 1, 20),
    "article": (25, 0, 2),
    "space": (30, 0, DEPT_NONE),
    "hosted": (35, 0, 3),
}


class _Row(SimpleNamespace):
    pass


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "usage.db"
    engine = create_engine(f"sqlite:///{path}")
    MessageSession.__table__.create(engine)
    LinsightSessionVersion.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(text(TABLE_DEFINITIONS["department"]))
        for dept_id, dept_path in [(1, "/1/"), (2, "/1/2/"), (3, "/1/2/3/"), (20, "/1/20/")]:
            conn.execute(
                text("INSERT INTO department (id, dept_id, name, path, tenant_id) VALUES (:i, :c, :n, :p, :t)"),
                {"i": dept_id, "c": f"BS@{dept_id}", "n": f"d{dept_id}", "p": dept_path, "t": TENANT},
            )
    session = Session(engine)
    for index, (chat_id, (flow_type, versions, dept_id)) in enumerate(_SESSIONS.items()):
        session.add(
            MessageSession(
                chat_id=chat_id,
                flow_id=f"f-{chat_id}",
                flow_type=flow_type,
                flow_name=f"name-{chat_id}",
                user_id=100 + index,
                tenant_id=TENANT,
                operator_dept_id=dept_id,
            )
        )
        session.commit()
        for _ in range(versions):
            session.add(LinsightSessionVersion(session_id=chat_id, user_id=100 + index, question="q"))
        session.commit()

    async def _results(statement, page=None, limit=None):
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        return list(session.exec(statement).all())

    async def _count(statement):
        return session.exec(select(func.count()).select_from(statement.subquery())).one()

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    @asynccontextmanager
    async def _async_session():
        async with AsyncSession(async_engine) as one:
            yield one

    svc = "bisheng.api.services.audit_log"
    monkeypatch.setattr(f"{svc}.MessageSessionDao.get_statement_results", staticmethod(_results))
    monkeypatch.setattr(f"{svc}.MessageSessionDao.get_statement_count", staticmethod(_count))
    monkeypatch.setattr(f"{svc}.AppChatList", lambda **kwargs: _Row(**kwargs))
    monkeypatch.setattr(f"{svc}.UserDao.aget_user_by_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(f"{svc}.FlowDao.aget_flow_by_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(f"{svc}.AssistantDao.aget_assistants_by_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "bisheng.chat_session.domain.repositories.audit_session_repository.get_async_db_session", _async_session
    )
    yield session
    session.close()
    engine.dispose()


def _user(admin=True):
    user = MagicMock()
    user.user_id = 900
    user.is_admin.return_value = admin
    user.is_global_super = False
    user.get_user_groups = AsyncMock(return_value=[])
    return user


async def _list(user, **kwargs):
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=TENANT),
    ):
        rows, total = await AuditLogService.get_session_list(user, [], [], [], None, None, None, None, 1, 50, **kwargs)
    assert total == len(rows)
    return {row.chat_id: row for row in rows}


async def test_whitelist_and_usage_types(db):
    rows = await _list(_user())
    assert {chat_id: row.usage_type for chat_id, row in rows.items()} == {
        "asst": "assistant",
        "wf": "workflow",
        "ws-daily": "daily",
        "ws-task": "task",
        "linsight": "task",
        "article": "daily",
        "space": "daily",
    }


async def test_names_of_types_without_a_flow_row_come_from_the_session(db):
    rows = await _list(_user())
    assert rows["linsight"].flow_name == "name-linsight"
    assert rows["space"].flow_name == "name-space"


@pytest.mark.parametrize(
    "usage_type,expected",
    [
        ("task", {"ws-task", "linsight"}),
        ("daily", {"ws-daily", "article", "space"}),
        ("assistant", {"asst"}),
        ("workflow", {"wf"}),
    ],
)
async def test_usage_type_filter_counts_multi_version_sessions_once(db, usage_type, expected):
    assert set(await _list(_user(), usage_type=usage_type)) == expected


async def test_usage_type_and_organisation_intersect(db):
    rows = await _list(_user(), usage_type="task", dept_selection=DeptSelection.of([2]))
    assert set(rows) == {"ws-task"}


async def test_rows_carry_the_snapshot(db):
    rows = await _list(_user())
    assert rows["space"].operator_dept_id == DEPT_NONE


async def test_menu_role_is_limited_to_primary_department(db, audit_identity):
    audit_identity.menu = True
    audit_identity.primary_dept_id = 2
    assert set(await _list(_user(admin=False))) == {"article"}


async def test_without_menu_is_refused(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await _list(_user(admin=False))
    assert caught.value.status_code == UnAuthorizedError.http_exception().status_code
