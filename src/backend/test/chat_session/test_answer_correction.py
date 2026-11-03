from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.chat_session.application import answer_correction as correction
from bisheng.database.models.message import ChatMessage


@pytest.mark.parametrize("category", ["output_msg", "stream_msg"])
def test_workflow_quote_uses_display_text(category):
    answer = ChatMessage(
        category=category,
        message='{"msg":"<think>private reasoning</think>Visible answer.:::web[]:::"}',
    )
    assert correction.answer_text(answer) == "Visible answer."


@pytest.mark.asyncio
async def test_inactive_membership_does_not_grant_maintenance(monkeypatch):
    membership = AsyncMock(return_value=SimpleNamespace(tenant_id=3, status="disabled"))
    monkeypatch.setattr(correction.UserTenantDao, "aget_active_user_tenant", membership)
    assert not await correction.AnswerCorrectionService.can_maintain(7, 8, 3)
    membership.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_owned_answer_requires_owned_session(monkeypatch):
    monkeypatch.setattr(correction, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(correction.ChatMessageDao, "aget_message_by_id", AsyncMock(return_value=ChatMessage(
        tenant_id=3, user_id=7, flow_id="app", chat_id="session", is_bot=True,
        category="output_msg", sensitive_status=1,
    )))
    monkeypatch.setattr(correction.MessageSessionDao, "async_get_one", AsyncMock(return_value=SimpleNamespace(
        tenant_id=3, user_id=9, flow_id="app",
    )))
    assert await correction.AnswerCorrectionService.eligible_answer(
        42, SimpleNamespace(tenant_id=3, user_id=7),
    ) is None


@pytest.mark.asyncio
async def test_stale_transition_preserves_first_assignment(async_db_engine, monkeypatch):
    from contextlib import asynccontextmanager

    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.chat_session.domain.models.answer_correction import AnswerCorrection, CorrectionState
    from bisheng.chat_session.domain.repositories import answer_correction as persistence

    async with async_db_engine.begin() as connection:
        await connection.run_sync(AnswerCorrection.__table__.create)

    @asynccontextmanager
    async def session():
        async with AsyncSession(async_db_engine) as database:
            yield database

    monkeypatch.setattr(persistence, "get_async_db_session", session)
    repository = persistence.AnswerCorrectionRepository
    record = await repository.create(AnswerCorrection(
        tenant_id=3, app_id="app", answer_id=42, submitter_id=7,
        quote="Original.", correction="Correction.", evidence="Evidence.",
    ))
    expected = CorrectionState.PENDING_ASSIGNMENT
    target = CorrectionState.PENDING_PROCESSING
    assert await repository.transition(record, expected, target, knowledge_id=8, assignee_id=9)
    assert not await repository.transition(record, expected, target, knowledge_id=8, assignee_id=10)
    stored = await repository.get(record.id)
    assert stored is not None
    assert stored.assignee_id == 9
    assert stored.state == target.value
