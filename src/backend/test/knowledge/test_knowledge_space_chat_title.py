"""Conversation naming for knowledge-space chat.

The title is generated from the question alone, so it is started as early as the
question is known and collected again when the round is finalized. That ordering
is what lets the closing event carry the name back to a history list that is
otherwise only loaded when the panel mounts.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService

MODULE = "bisheng.knowledge.domain.services.knowledge_space_chat_service"


def _service() -> KnowledgeSpaceChatService:
    service = KnowledgeSpaceChatService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=7),
    )
    service.chat_session_repo = MagicMock()
    return service


async def test_named_conversation_is_not_renamed():
    service = _service()
    session = SimpleNamespace(chat_id="chat-1", name="already named")

    with patch.object(KnowledgeSpaceChatService, "generate_conversation", new_callable=AsyncMock) as generate:
        assert service._start_session_title_task(session, "a question") is None

    generate.assert_not_awaited()


async def test_unnamed_conversation_is_named_from_the_question_alone():
    service = _service()
    session = SimpleNamespace(chat_id="chat-1", name="")

    with patch.object(
        KnowledgeSpaceChatService,
        "generate_conversation",
        new_callable=AsyncMock,
        return_value="Weather Tomorrow",
    ) as generate:
        task = service._start_session_title_task(session, "will it rain tomorrow")
        assert task is not None
        assert await service._resolve_session_title(task) == "Weather Tomorrow"

    # The answer is deliberately not passed: waiting for it would delay the title
    # without improving it.
    generate.assert_awaited_once_with(user_id=7, chat_id="chat-1", question="will it rain tomorrow")


async def test_no_title_when_none_was_requested():
    assert await KnowledgeSpaceChatService._resolve_session_title(None) is None


async def test_slow_title_is_left_running_rather_than_cancelled():
    """A timeout must not cancel the task, or a slow model loses the name entirely.

    Missing this round's closing event is acceptable — the title still reaches the
    database and shows up the next time the history list is loaded.
    """
    released = asyncio.Event()

    async def _slow_title() -> str:
        await released.wait()
        return "Late Title"

    task = asyncio.create_task(_slow_title())
    with patch(f"{MODULE}.SESSION_TITLE_WAIT_SECONDS", 0.01):
        assert await KnowledgeSpaceChatService._resolve_session_title(task) is None

    assert not task.cancelled()
    released.set()
    assert await task == "Late Title"


async def test_failed_title_does_not_break_the_round():
    async def _failing_title() -> str:
        raise RuntimeError("title model unavailable")

    task = asyncio.create_task(_failing_title())

    assert await KnowledgeSpaceChatService._resolve_session_title(task) is None


async def test_title_starts_before_retrieval():
    """Starting before retrieval is the whole point: it buys the title the time it
    needs to be ready when the answer finishes."""
    service = _service()
    session = SimpleNamespace(chat_id="chat-1", flow_id="space_3_folder_0", name="")
    service.chat_session_repo.get_by_chat_and_effective_entry = AsyncMock(return_value=session)
    service._require_space_view_permission = AsyncMock()
    service.get_space_llm_config = AsyncMock(return_value=(MagicMock(), SimpleNamespace(max_chunk_size=100)))

    order: list[str] = []

    async def _retrieve(**kwargs):
        order.append("retrieve")
        return []

    service._retrieve_and_filter = _retrieve

    async def _empty_render(*args, **kwargs):
        order.append(f"render:{kwargs.get('title_task') is not None}")
        if False:
            yield None

    service._render_rag_response = _empty_render

    def _start_title(*args, **kwargs):
        order.append("title")
        return MagicMock()

    service._start_session_title_task = _start_title

    with patch(f"{MODULE}.KnowledgeDao.aquery_by_id", new_callable=AsyncMock, return_value=SimpleNamespace(id=3)):
        assert [item async for item in service.chat_folder(3, 0, "chat-1", "question", 1)] == []

    assert order == ["title", "retrieve", "render:True"]
