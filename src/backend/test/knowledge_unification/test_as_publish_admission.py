"""T367: publication borrows its real write Session; RPC overrides are transient."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from bisheng.api.services import assistant as assistant_module
from bisheng.api.services.assistant import AssistantService
from bisheng.assistant.domain.services import published_assistant_service as published_module
from bisheng.assistant.domain.services.published_assistant_service import PublishedAssistantService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.database.models.assistant import Assistant, AssistantStatus
from test.knowledge_unification import test_as_bindings as bindings_tests

assistant_business = bindings_tests.assistant_business
assistant_tenant = bindings_tests.assistant_tenant
seed = bindings_tests.seed
inspect_business = bindings_tests.inspect_business


async def test_publication_passes_original_identity_and_active_business_session(assistant_business, monkeypatch):
    context = assistant_business
    context.user = UserPayload(user_id=7, user_name="actor", tenant_id=101, user_role=[])
    await seed(context)
    seen = []

    class Agent:
        def __init__(self, row, chat_id, invoke_user_id, *, login_user, reference_session):
            assert login_user is context.user
            assert invoke_user_id == context.user.user_id
            assert reference_session.in_transaction()
            seen.append((row, reference_session))

        async def init_assistant(self):
            row, session = seen[-1]
            assert row in session
            assert session.in_transaction()

    monkeypatch.setattr(assistant_module, "AssistantAgent", Agent)
    assert await AssistantService.update_status(
        context.request, context.user, "assistant-a", AssistantStatus.ONLINE.value
    )
    row, _links, _refs, source = await inspect_business(context)
    assert len(seen) == 1 and row.status == AssistantStatus.ONLINE.value and source.effective


async def test_publication_admission_error_rolls_back_without_laundering_10996(assistant_business, monkeypatch):
    context = assistant_business
    await seed(context)
    _row, _links, _refs, before = await inspect_business(context)
    error = ResourceReferenceInvalidError(reason="read_admission")

    class Agent:
        def __init__(self, row, chat_id, invoke_user_id, *, login_user, reference_session):
            assert reference_session.in_transaction()

        async def init_assistant(self):
            raise error

    monkeypatch.setattr(assistant_module, "AssistantAgent", Agent)
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        await AssistantService.update_status(context.request, context.user, "assistant-a", AssistantStatus.ONLINE.value)
    assert caught.value is error
    row, _links, _refs, after = await inspect_business(context)
    assert row.status == AssistantStatus.OFFLINE.value and after.source_revision == before.source_revision


async def test_rpc_passes_actual_operator_and_does_not_change_source_temperature(monkeypatch):
    user = UserPayload(user_id=9, user_name="actor", tenant_id=101, user_role=[])
    info = Assistant(id="assistant-a", tenant_id=101, temperature=0.4)
    monkeypatch.setattr(PublishedAssistantService, "get_info", AsyncMock(return_value=info))
    seen = []

    class Agent:
        def __init__(self, row, chat_id, invoke_user_id, *, login_user, runtime_temperature):
            assert row is info and info.temperature == 0.4
            assert login_user is user and invoke_user_id == 9 and runtime_temperature == 0.9
            self.llm = SimpleNamespace(streaming=False)
            seen.append(self)

        async def init_assistant(self):
            return None

        async def run(self, question, history):
            return [AIMessage(content="answer")]

    monkeypatch.setattr(published_module, "AssistantAgent", Agent)
    completion, returned = await PublishedAssistantService.complete(
        assistant_id="assistant-a",
        model="model",
        messages=[{"role": "user", "content": "question"}],
        stream=False,
        temperature=0.9,
        operator=user,
    )
    assert completion.payload["choices"][0]["message"]["content"] == "answer"
    assert returned is info and info.temperature == 0.4 and len(seen) == 1
