"""F003 T008: session detail endpoints answer the list's scope question (decision 8)."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.chat_session.api.endpoints import session as endpoints
from bisheng.database.models.mark_app_user import MarkAppUser
from bisheng.database.models.session import MessageSession

OWNER = 31


@pytest.fixture()
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: MessageSession.__table__.create(sync))
        await conn.run_sync(lambda sync: MarkAppUser.__table__.create(sync))
        for chat_id, dept_id in [("in-scope", 3), ("out-of-scope", 20)]:
            await conn.execute(
                insert(MessageSession.__table__).values(
                    chat_id=chat_id,
                    flow_id=f"app-{chat_id}",
                    flow_type=15,
                    flow_name="n",
                    user_id=OWNER,
                    tenant_id=1,
                    operator_dept_id=dept_id,
                )
            )
        await conn.execute(
            insert(MarkAppUser.__table__).values(app_id="app-out-of-scope", user_id=77, task_id=1, create_id=1)
        )

    @asynccontextmanager
    async def _session():
        async with AsyncSession(engine) as one:
            yield one

    monkeypatch.setattr(
        "bisheng.chat_session.domain.repositories.audit_session_repository.get_async_db_session", _session
    )

    async def _get_one(chat_id):
        async with AsyncSession(engine) as one:
            return await one.get(MessageSession, chat_id)

    monkeypatch.setattr(endpoints.MessageSessionDao, "async_get_one", staticmethod(_get_one))
    monkeypatch.setattr(endpoints.ChatSessionService, "get_chat_history", AsyncMock(return_value=["msg"]))
    monkeypatch.setattr(endpoints.ChatMessageDao, "aget_messages_by_chat_id", AsyncMock(return_value=[]))
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=1),
    ):
        yield
    await engine.dispose()


def _user(user_id=900, admin=False):
    user = MagicMock()
    user.user_id = user_id
    user.is_admin.return_value = admin
    user.is_global_super = False
    return user


@pytest.fixture()
def menu_role_of_dept_3(audit_identity):
    audit_identity.menu = True
    audit_identity.primary_dept_id = 3


async def _messages(user, chat_id):
    return await endpoints.get_chat_messages_by_conversation_id(conversationId=chat_id, login_user=user)


async def _history(user, chat_id):
    return await endpoints.get_chat_message_public(chat_id=chat_id, flow_id=f"app-{chat_id}", login_user=user)


class TestMessages:
    async def test_in_scope_passes_the_check(self, db, menu_role_of_dept_3):
        # Messages are empty in this fixture, so passing the check surfaces as NotFound.
        from bisheng.common.errcode.http_error import NotFoundError

        with pytest.raises(NotFoundError):
            await _messages(_user(), "in-scope")

    async def test_out_of_scope_refused(self, db, menu_role_of_dept_3):
        with pytest.raises(HTTPException):
            await _messages(_user(), "out-of-scope")

    async def test_missing_session_refused(self, db, menu_role_of_dept_3):
        with pytest.raises(HTTPException):
            await _messages(_user(), "nope")

    async def test_owner_has_no_exemption_here(self, db):
        with pytest.raises(HTTPException):
            await _messages(_user(OWNER), "out-of-scope")


class TestHistory:
    async def test_owner_passes_without_audit_menu(self, db):
        assert (await _history(_user(OWNER), "out-of-scope")).data == ["msg"]

    async def test_annotator_of_the_app_passes(self, db):
        assert (await _history(_user(77), "out-of-scope")).data == ["msg"]

    async def test_in_scope_auditor_passes(self, db, menu_role_of_dept_3):
        assert (await _history(_user(), "in-scope")).data == ["msg"]

    async def test_out_of_scope_auditor_refused(self, db, menu_role_of_dept_3):
        with pytest.raises(HTTPException):
            await _history(_user(), "out-of-scope")

    async def test_plain_user_refused(self, db):
        with pytest.raises(HTTPException):
            await _history(_user(), "in-scope")
