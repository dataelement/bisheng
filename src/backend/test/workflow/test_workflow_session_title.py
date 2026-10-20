"""Workflow titles must describe submitted questions, never input-node schemas."""

import json
from types import SimpleNamespace

import pytest

from bisheng.worker.workflow import redis_callback as callback_module
from bisheng.worker.workflow.redis_callback import RedisCallback


@pytest.fixture
def title_context(monkeypatch):
    session = SimpleNamespace(chat_id="chat-title", name="", tenant_id=1)
    questions = [SimpleNamespace(message="Recommend places to visit in Hangzhou")]
    inputs = [SimpleNamespace(message=json.dumps({"node_id": "input_1", "input_schema": {"key": "user_input"}}))]
    received = []

    def messages(chat_id, categories, limit):
        assert chat_id == "chat-title"
        return (questions if categories == ["question"] else inputs)[:limit]

    def persist(chat_id, title, *, only_if_default=False, tenant_id=None):
        assert chat_id == "chat-title"
        if only_if_default and session.name not in (None, "", "New Chat"):
            return False
        session.name = title
        return True

    class TitleModel:
        def invoke(self, messages):
            received.append(messages[0].content)
            if "Recommend places to visit in Hangzhou" in messages[0].content:
                return SimpleNamespace(content="Hangzhou travel recommendations")
            return SimpleNamespace(content="Input Node Schema")

    monkeypatch.setattr(callback_module.ChatMessageDao, "get_messages_by_chat_id", messages)
    monkeypatch.setattr(callback_module.MessageSessionDao, "get_one", lambda chat_id: session)
    monkeypatch.setattr(callback_module.MessageSessionDao, "update_session_name_sync", persist)
    monkeypatch.setattr(
        callback_module.LLMService,
        "get_workbench_llm_sync",
        lambda **kwargs: SimpleNamespace(chat_title_llm=SimpleNamespace(id="913")),
    )
    monkeypatch.setattr(callback_module.LLMService, "get_bisheng_llm_sync", lambda **kwargs: TitleModel())
    from bisheng.common.utils import title_generator

    monkeypatch.setattr(
        title_generator,
        "get_prompt_manager_sync",
        lambda: SimpleNamespace(
            render_prompt=lambda *args, **kwargs: SimpleNamespace(prompt="Summarize: " + kwargs["human"])
        ),
    )
    callback = RedisCallback.__new__(RedisCallback)
    callback.chat_id = session.chat_id
    callback.user_id = 3
    callback.tenant_id = 1
    callback.new_session = session
    return SimpleNamespace(callback=callback, session=session, questions=questions, received=received)


def test_title_uses_submitted_question_instead_of_input_schema(title_context):
    title_context.callback.generate_session_title()
    assert title_context.session.name == "Hangzhou travel recommendations"
    assert title_context.received == ["Summarize: Recommend places to visit in Hangzhou"]


def test_no_question_does_not_generate_a_title_from_input_schema(title_context):
    title_context.questions.clear()
    title_context.callback.generate_session_title()
    assert title_context.received == []
    assert title_context.session.name == ""


def test_manual_rename_during_model_call_is_not_overwritten(monkeypatch, title_context):
    class SlowTitleModel:
        def invoke(self, messages):
            title_context.session.name = "Manually named conversation"
            return SimpleNamespace(content="Hangzhou travel recommendations")

    monkeypatch.setattr(callback_module.LLMService, "get_bisheng_llm_sync", lambda **kwargs: SlowTitleModel())
    title_context.callback.generate_session_title()
    assert title_context.session.name == "Manually named conversation"


def test_question_can_name_a_session_created_before_this_callback(title_context):
    title_context.callback.new_session = None
    title_context.callback.generate_session_title()
    assert title_context.session.name == "Hangzhou travel recommendations"


def test_default_title_can_be_retried_after_a_question_arrives(title_context):
    title_context.session.name = "New Chat"
    title_context.callback.generate_session_title()
    assert title_context.session.name == "Hangzhou travel recommendations"


def test_existing_title_is_not_overwritten(title_context):
    title_context.session.name = "My conversation"
    title_context.callback.generate_session_title()
    assert title_context.session.name == "My conversation"
    assert title_context.received == []


@pytest.mark.parametrize("category,should_schedule", [("question", True), ("guide_word", False)])
@pytest.mark.parametrize("session_exists", [False, True])
def test_title_is_scheduled_after_question_not_session_creation(
    monkeypatch, title_context, category, should_schedule, session_exists
):
    callback = title_context.callback
    callback.workflow_id = "workflow-1"
    callback.create_session = False
    callback.source = "platform"
    callback._finalize_citation_items = lambda *args, **kwargs: []
    scheduled = []
    existing = [title_context.session] if session_exists else []

    def insert_session(session):
        existing.append(session)
        return session

    monkeypatch.setattr(callback_module.MessageSessionDao, "get_one", lambda chat_id: existing[0] if existing else None)
    monkeypatch.setattr(callback_module.MessageSessionDao, "insert_one", insert_session)
    monkeypatch.setattr(callback_module.ChatMessageDao, "insert_one", lambda message: SimpleNamespace(id=1))
    monkeypatch.setattr(callback_module.FlowDao, "get_flow_by_id", lambda flow_id: SimpleNamespace(name="Workflow"))
    monkeypatch.setattr(callback_module, "promote_chat_attachments_sync", lambda *args: None)
    monkeypatch.setattr(callback_module, "save_message_citations_sync", lambda **kwargs: None)
    monkeypatch.setattr(callback_module.telemetry_service, "log_event_sync", lambda **kwargs: None)
    monkeypatch.setattr(callback_module.thread_pool, "submit", lambda key, fn, *args: scheduled.append(fn))
    callback.save_chat_message(callback_module.ChatResponse(category=category, message="Hello", source=0, type="over"))
    assert (callback.generate_session_title in scheduled) is should_schedule
