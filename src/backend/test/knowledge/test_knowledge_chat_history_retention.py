from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.repositories.interfaces.knowledge_chat_session_repository import (
    KnowledgeChatSessionRehomeResult,
)
from bisheng.knowledge.domain.services.knowledge_space_chat_history_retention_service import (
    DEFAULT_FLOW_CHUNK_SIZE,
    KnowledgeSpaceChatHistoryRetentionService,
    build_knowledge_chat_flows,
    dispatch_knowledge_chat_rehome,
)


async def test_retention_service_validates_and_rehomes_exact_flows():
    repository = AsyncMock()
    repository.rehome_by_flows.return_value = KnowledgeChatSessionRehomeResult(3, 3)
    service = KnowledgeSpaceChatHistoryRetentionService(repository)

    result = await service.rehome_by_flows(
        9,
        ["space_9_file_2", "space_9_folder_3", "space_9_file_2"],
    )

    assert result == KnowledgeChatSessionRehomeResult(3, 3)
    repository.rehome_by_flows.assert_awaited_once_with(
        "space_9_folder_0",
        ["space_9_file_2", "space_9_folder_3"],
    )


@pytest.mark.parametrize(
    "flow_ids",
    [
        ["space_8_file_2"],
        ["space_9_folder_0"],
        ["assistant_9"],
        ["space_9_file_bad"],
    ],
)
async def test_retention_service_rejects_invalid_or_cross_space_flows(flow_ids):
    service = KnowledgeSpaceChatHistoryRetentionService(AsyncMock())

    with pytest.raises(ValueError):
        await service.rehome_by_flows(9, flow_ids)


def test_build_flows_and_dispatch_in_chunks_of_500():
    flows = build_knowledge_chat_flows(
        9,
        [("file", resource_id) for resource_id in range(1, DEFAULT_FLOW_CHUNK_SIZE + 2)],
    )

    with patch(
        "bisheng.worker.knowledge.knowledge_chat_history_retention.rehome_knowledge_chat_sessions.apply_async"
    ) as apply_async:
        dispatched = dispatch_knowledge_chat_rehome(
            source_space_id=9,
            source_flow_ids=flows,
            reason="delete_file",
        )

    assert dispatched == 2
    assert [len(call.kwargs["kwargs"]["source_flow_ids"]) for call in apply_async.call_args_list] == [500, 1]
    assert all(call.kwargs["countdown"] == 5 for call in apply_async.call_args_list)


def test_dispatch_failure_is_best_effort():
    with patch(
        "bisheng.worker.knowledge.knowledge_chat_history_retention.rehome_knowledge_chat_sessions.apply_async",
        side_effect=RuntimeError("broker unavailable"),
    ):
        dispatched = dispatch_knowledge_chat_rehome(
            source_space_id=9,
            source_flow_ids=["space_9_file_1"],
            reason="delete_file",
        )

    assert dispatched == 0
