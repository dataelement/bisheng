from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.database.models.flow import FlowType
from bisheng.database.models.session import MessageSession
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeChatSessionResponse
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService


def _service() -> KnowledgeSpaceChatService:
    service = KnowledgeSpaceChatService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=7),
    )
    service.chat_session_repo = MagicMock()
    service.chat_session_repo.list_by_effective_entry = AsyncMock(return_value=[])
    service.chat_session_repo.find_first_by_effective_entry = AsyncMock(return_value=None)
    service.chat_session_repo.get_by_chat_and_effective_entry = AsyncMock(return_value=None)
    return service


async def test_root_session_list_uses_effective_entry_repository():
    service = _service()
    recovered = SimpleNamespace(chat_id="recovered")
    service.chat_session_repo.list_by_effective_entry.return_value = [recovered]
    service._require_space_view_permission = AsyncMock()

    result = await service.get_chat_folder_session(space_id=3, folder_id=0)

    assert result == [recovered]
    service._require_space_view_permission.assert_awaited_once_with(3)
    service.chat_session_repo.list_by_effective_entry.assert_awaited_once_with(
        "space_3_folder_0",
        7,
    )


async def test_recovered_history_reads_messages_with_original_content_flow():
    service = _service()
    recovered = SimpleNamespace(
        chat_id="chat-1",
        flow_id="space_3_folder_99",
        entry_flow_id="space_3_folder_0",
    )
    service.chat_session_repo.get_by_chat_and_effective_entry.return_value = recovered
    service._require_space_view_permission = AsyncMock()

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.ChatSessionService.get_chat_history",
        new_callable=AsyncMock,
        return_value=["message"],
    ) as get_history:
        result = await service.get_chat_folder_history(3, 0, "chat-1", page_size=20)

    assert result == ["message"]
    get_history.assert_awaited_once_with(
        "chat-1",
        "space_3_folder_99",
        page_size=20,
    )


async def test_wrong_entry_chat_id_is_rejected_before_history_read():
    service = _service()
    service._require_space_view_permission = AsyncMock()

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.ChatSessionService.get_chat_history",
        new_callable=AsyncMock,
    ) as get_history:
        result = await service.get_chat_folder_history(3, 0, "old-folder-chat")

    assert result == []
    get_history.assert_not_awaited()


async def test_recovered_root_chat_uses_whole_space_retrieval():
    service = _service()
    recovered = SimpleNamespace(
        chat_id="chat-1",
        flow_id="space_3_file_99",
        entry_flow_id="space_3_folder_0",
        name="already named",
    )
    service.chat_session_repo.get_by_chat_and_effective_entry.return_value = recovered
    service._require_space_view_permission = AsyncMock()
    service.get_space_llm_config = AsyncMock(return_value=(MagicMock(), SimpleNamespace(max_chunk_size=100)))
    service._retrieve_and_filter = AsyncMock(return_value=[])

    async def _empty_render(*args, **kwargs):
        if False:
            yield None

    service._render_rag_response = _empty_render
    space = SimpleNamespace(id=3)

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=space,
    ):
        result = [
            item
            async for item in service.chat_folder(
                knowledge_id=3,
                folder_id=0,
                chat_id="chat-1",
                query="question",
                model_id=1,
            )
        ]

    assert result == []
    service._retrieve_and_filter.assert_awaited_once_with(
        space=space,
        query="question",
        candidate_file_ids=None,
        max_content=100,
    )


def test_public_session_schema_excludes_internal_entry_flow_id():
    session = MessageSession(
        chat_id="chat-1",
        name="title",
        flow_id="space_3_file_99",
        entry_flow_id="space_3_folder_0",
        flow_type=FlowType.KNOLEDGE_SPACE.value,
        flow_name="file",
        user_id=7,
        tenant_id=1,
        sensitive_status=1,
        create_time=datetime(2026, 1, 1),
        update_time=datetime(2026, 1, 1),
    )

    payload = KnowledgeChatSessionResponse.model_validate(session).model_dump()

    assert payload["flow_id"] == "space_3_file_99"
    assert "entry_flow_id" not in payload
