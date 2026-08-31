import json
from types import SimpleNamespace

from bisheng.channel.api.endpoints import channel_chat as endpoint
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.llm.domain.services.model_rate_limit import RecoveryAction


async def _response_text(response) -> str:
    chunks = [chunk async for chunk in response.body_iterator]
    return "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)


async def test_successful_recovery_persists_only_the_business_answer(monkeypatch) -> None:
    inserted = []

    async def insert(message):
        inserted.append(message)
        message.id = 22
        return message

    monkeypatch.setattr(
        "bisheng.channel.api.endpoints.channel_chat.ChatMessageDao.ainsert_one",
        insert,
    )
    conversation = SimpleNamespace(user_id=9, chat_id="chat-1")
    data = SimpleNamespace(article_doc_id="article-1")

    result = await endpoint._persist_channel_answer(
        conversation,
        data,
        "answer",
        "reasoning",
    )

    assert result.id == 22
    assert len(inserted) == 1
    assert inserted[0].is_bot is True
    assert inserted[0].extra == "{}"


async def test_recovery_validation_error_uses_standard_rejected_sse(monkeypatch) -> None:
    class RejectingRecoveryService:
        async def claim_recovery(self, *args, **kwargs):
            raise NotFoundError()

    monkeypatch.setattr(endpoint, "ModelRecoveryService", RejectingRecoveryService)

    response = await endpoint.recover_channel_chat(
        "101",
        endpoint.ChannelChatRecoveryRequest(
            attempt_id="attempt-2",
            subject_id="101",
            action=RecoveryAction.MANUAL_RETRY,
        ),
        SimpleNamespace(user_id=9, tenant_id=2),
    )
    payload = json.loads((await _response_text(response)).split("data: ", 1)[1])

    assert payload["status_code"] == 12048
    assert payload["data"]["error_type"] == "recovery_rejected"
