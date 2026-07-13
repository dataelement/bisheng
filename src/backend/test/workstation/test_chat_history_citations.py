import json
from datetime import datetime
from bisheng.citation.domain.models.message_citation import MessageCitation
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.database.models.message import ChatMessage
from bisheng.workstation.domain.services.chat_helpers import format_agent_history_message


def build_persisted_citation(message_id: int) -> MessageCitation:
    return MessageCitation(
        id=1,
        citation_id="knowledgesearch_history",
        message_id=message_id,
        chat_id="chat-history",
        citation_type="rag",
        source_payload={
            "knowledgeId": 3313,
            "knowledgeName": "首钢知识空间",
            "documentId": 86146,
            "documentName": "冷轧带钢边部折皱缺陷.pdf",
            "fileType": "pdf",
            "snippet": "第一段",
            "items": [
                {
                    "itemId": "5",
                    "chunkId": "chunk-5",
                    "chunkIndex": 5,
                    "content": "第一段",
                },
                {
                    "itemId": "9",
                    "chunkId": "chunk-9",
                    "chunkIndex": 9,
                    "content": "第二段",
                },
            ],
        },
    )


async def test_list_messages_citations_restores_item_level_keys():
    class FakeRepository:
        async def find_by_message_ids_grouped(self, message_ids):
            assert message_ids == [102]
            return {102: [build_persisted_citation(102)]}

    service = CitationRegistryService(FakeRepository())

    result = await service.list_messages_citations([102])

    assert [item.key for item in result[102]] == [
        "knowledgesearch_history:5",
        "knowledgesearch_history:9",
    ]
    assert result[102][1].itemId == "9"
    assert result[102][1].sourcePayload.snippet == "第二段"


def test_agent_chat_history_includes_persisted_citations():
    now = datetime.now()
    message = ChatMessage(
        id=102,
        user_id=7,
        tenant_id=1,
        chat_id="chat-history",
        flow_id="workflow-1",
        type="end",
        is_bot=True,
        category="agent_answer",
        message=json.dumps(
            {
                "msg": "检查设备状态。\\ue200knowledgesearch_history:5\\ue202",
                "events": [],
            }
        ),
        create_time=now,
        update_time=now,
    )
    grouped_item = CitationRegistryService(None).to_registry_item(build_persisted_citation(102))
    citation = CitationRegistryService.flatten_registry_item(grouped_item)[0]

    result = format_agent_history_message(message, [citation])

    assert result["citations"][0]["key"] == "knowledgesearch_history:5"
    assert result["citations"][0]["sourcePayload"]["documentId"] == 86146
