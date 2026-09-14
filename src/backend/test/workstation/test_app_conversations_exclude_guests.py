"""The workbench conversation list must not show anonymous share-link sessions.

Guest sessions are stamped with the configured default operator's ``user_id``
for backwards compatibility, so a filter on ``user_id`` alone would show every
visitor's conversation to whoever holds that account. The subject-kind column
is what separates them.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.workstation.api.endpoints import apps

OPERATOR_ID = 41


def _compiled_where(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def test_natural_person_statement_excludes_api_subject_rows() -> None:
    subject = SessionSubject.natural_person(tenant_id=3, user_id=OPERATOR_ID)
    sql = _compiled_where(
        subject.filter_statement(select(MessageSession).where(MessageSession.flow_id == "flow-1"))
    )

    assert "api_subject_type IS NULL" in sql
    assert f"user_id = {OPERATOR_ID}" in sql
    assert "flow_id = 'flow-1'" in sql


@pytest.mark.asyncio
async def test_app_conversations_queries_with_the_subject_filter(monkeypatch) -> None:
    """Regression: the endpoint used to pass user_ids only."""

    captured = {}

    async def get_statement_results(statement, page=0, limit=0):
        captured["sql"] = _compiled_where(statement)
        captured["page"] = page
        captured["limit"] = limit
        return []

    monkeypatch.setattr(
        MessageSessionDao, "get_statement_results", AsyncMock(side_effect=get_statement_results)
    )
    monkeypatch.setattr(
        apps.MessageSessionDao, "get_statement_results", AsyncMock(side_effect=get_statement_results)
    )

    login_user = SimpleNamespace(user_id=OPERATOR_ID, tenant_id=3)
    response = await apps.get_app_conversations(flow_id="flow-1", page=2, limit=5, login_user=login_user)

    assert response.data == {"list": [], "total": 0}
    assert captured["page"] == 2
    assert captured["limit"] == 5
    # The guard that keeps visitor sessions out of a person's own list.
    assert "api_subject_type IS NULL" in captured["sql"]
