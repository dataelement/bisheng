import json
from types import SimpleNamespace

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.database.models.message import ChatMessage
from bisheng.knowledge.api.endpoints import knowledge_space as endpoint
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.llm.domain.services.model_rate_limit import (
    ClaimedAttempt,
    ModelCallEntry,
    ModelCallResumeMode,
    RecoveryAction,
)


async def _response_text(response) -> str:
    chunks = [chunk async for chunk in response.body_iterator]
    return "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)


async def test_file_recovery_reinvokes_same_subject_without_new_question(monkeypatch) -> None:
    service = KnowledgeSpaceChatService.__new__(KnowledgeSpaceChatService)
    service.login_user = SimpleNamespace(user_id=9, tenant_id=2)
    calls = []

    async def fake_chat(space_id, file_id, query, model_id, call_context=None):
        calls.append((space_id, file_id, query, model_id, call_context))
        if False:
            yield None

    monkeypatch.setattr(service, "chat_single_file", fake_chat)
    message = ChatMessage(
        id=101,
        user_id=9,
        chat_id="chat-1",
        flow_id="space_4_file_8",
        type="end",
        is_bot=False,
        category="question",
        message=json.dumps({"query": "summarize", "model_id": 17}),
        extra=json.dumps({"recovery_request": {"mode": "file", "space_id": 4, "file_id": 8}}),
    )
    attempt = ClaimedAttempt(
        execution_id="execution-1",
        attempt_id="attempt-2",
        subject_id="101",
        entry=ModelCallEntry.KNOWLEDGE,
        model_id=18,
        resume_mode=ModelCallResumeMode.READ_ONLY_REINVOKE,
        action=RecoveryAction.SWITCH_MODEL,
        should_execute=True,
    )

    assert [event async for event in service.recover_attempt(attempt, message)] == []

    assert len(calls) == 1
    context = calls[0][4]
    assert calls[0][:4] == (4, 8, "summarize", 18)
    assert context.subject_id == "101"
    assert context.execution_id == "execution-1"
    assert context.action == RecoveryAction.SWITCH_MODEL


async def test_recovery_validation_error_uses_standard_rejected_sse(monkeypatch) -> None:
    class RejectingRecoveryService:
        async def claim_recovery(self, *args, **kwargs):
            raise NotFoundError()

    monkeypatch.setattr(endpoint, "ModelRecoveryService", RejectingRecoveryService)
    service = SimpleNamespace(login_user=SimpleNamespace(user_id=9, tenant_id=2))

    response = await endpoint.recover_knowledge_chat(
        4,
        "101",
        endpoint.KnowledgeChatRecoveryRequest(
            attempt_id="attempt-2",
            subject_id="101",
            action=RecoveryAction.MANUAL_RETRY,
        ),
        service,
    )
    payload = json.loads((await _response_text(response)).split("data: ", 1)[1])

    assert payload["status_code"] == 12048
    assert payload["data"]["error_type"] == "recovery_rejected"
