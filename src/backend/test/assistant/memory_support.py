"""Shared helpers for the F132 assistant memory tests (Wave 9).

Not a test module (no ``test_`` prefix). The memory fixtures come from
``test/memory/conftest.py``; test modules import the ones they use so pytest
registers them in that module (``memory_runtime_config`` is autouse there).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from bisheng.database.models.assistant import Assistant
from bisheng.database.models.session import MessageSession
from bisheng.memory.domain.services.resident import RESIDENT_HEADER
from bisheng.user.domain.models.user import User
from test.memory.conftest import TENANT_A, USER_1

ASSISTANT_ID = "asst-mem-1"
PROMPT = "You are the test assistant."
EXECUTORS = ["ReAct", "function call"]


class StubChatModel(BaseChatModel):
    """Returns scripted replies and records every message list and tool binding."""

    replies: list[Any]
    received: list[list[BaseMessage]]
    bound: list[list[str]]

    @property
    def _llm_type(self) -> str:
        return "stub"

    def bind_tools(self, tools, **kwargs):
        self.bound.append([getattr(t, "name", None) or t.get("name") for t in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        reply = self.replies.pop(0) if self.replies else "done"
        msg = reply if isinstance(reply, AIMessage) else AIMessage(content=reply)
        return ChatResult(generations=[ChatGeneration(message=msg)])


def final_reply(executor: str, text: str = "好的"):
    if executor == "ReAct":
        return f"Action:\n```\n{json.dumps({'action': 'Final Answer', 'action_input': text}, ensure_ascii=False)}\n```"
    return AIMessage(content=text)


def tool_reply(executor: str, name: str, args: dict, call_id: str = "call_1"):
    if executor == "ReAct":
        action = {"action": name, "action_input": args}
        return f"Action:\n```\n{json.dumps(action, ensure_ascii=False)}\n```"
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def make_llm(replies) -> StubChatModel:
    return StubChatModel(replies=list(replies), received=[], bound=[])


async def build_agent(executor: str, replies, chat_id="chat-a1", tools=None, max_token=32000, user_id=USER_1):
    from bisheng.api.services.assistant_agent import AssistantAgent

    assistant = SimpleNamespace(id=ASSISTANT_ID, prompt=PROMPT, max_token=max_token, name="差旅助手", desc="")
    agent = AssistantAgent(assistant, chat_id=chat_id, invoke_user_id=user_id)
    llm = make_llm(replies)
    agent.llm = llm
    agent.tools = list(tools or [])
    agent.llm_agent_executor = executor
    await agent.init_agent()
    return agent, llm


def system_texts(messages) -> list[str]:
    return [m.content for m in messages if isinstance(m, SystemMessage)]


def has_resident(messages) -> bool:
    return any(RESIDENT_HEADER in str(m.content) for m in messages)


def tool_names(agent) -> list[str]:
    return [t.name for t in agent.tools]


def client_slice(result, chat_history):
    """Exactly what ``common/chat/client.py`` does with ``run()``'s result."""
    new_history = result[len(chat_history) : -1]
    kinds = []
    for one in new_history:
        if isinstance(one, AIMessage):
            kinds.append("tool_call")
        elif isinstance(one, ToolMessage):
            kinds.append("tool_result")
        else:
            kinds.append(f"unexpected:{type(one).__name__}")
    return result[-1].content, kinds


class SignalSpy(AsyncCallbackHandler):
    """A callback handler that only records memory signals."""

    def __init__(self):
        self.signals: list[dict] = []

    async def send_memory_signal(self, payload: dict):
        self.signals.append(dict(payload))


@pytest.fixture
def wired(memory_db, service, index, details, kv):
    """Production factory seeded with the in-memory doubles."""
    from bisheng.memory.domain.services import factory
    from bisheng.memory.domain.services.metrics import MemoryMetrics
    from bisheng.memory.domain.services.resident import ResidentService
    from bisheng.memory.domain.services.search import SearchService

    factory.reset()
    metrics = MemoryMetrics(kv)
    factory._instances.update(
        kv=kv,
        index=index,
        details=details,
        metrics=metrics,
        service=service,
        search=SearchService(index=index, details=details, metrics=metrics),
        resident=ResidentService(kv=kv, metrics=metrics),
    )
    yield SimpleNamespace(db=memory_db, service=service, kv=kv, index=index)
    factory.reset()


def seed_assistant(memory_db, enabled: bool | None = None, assistant_id=ASSISTANT_ID):
    with memory_db.session() as s:
        kw = {} if enabled is None else {"memory_enabled": enabled}
        s.add(Assistant(id=assistant_id, name="差旅助手", tenant_id=TENANT_A, user_id=1, **kw))
        s.commit()


def set_switch(memory_db, enabled: bool, assistant_id=ASSISTANT_ID):
    with memory_db.session() as s:
        row = s.get(Assistant, assistant_id)
        row.memory_enabled = enabled
        s.add(row)
        s.commit()


def seed_chat(memory_db, chat_id="chat-a1", owner=USER_1, assistant_id=ASSISTANT_ID):
    with memory_db.session() as s:
        if s.get(User, owner) is None:
            s.add(User(user_id=owner, user_name=f"u{owner}", password="x"))
        s.add(MessageSession(chat_id=chat_id, flow_id=assistant_id, flow_type=5, user_id=owner, name="c"))
        s.commit()


async def register(chat_id="chat-a1", user_id=USER_1):
    from bisheng.memory.domain.services.gate import MemoryGate

    await MemoryGate.open(chat_id, SimpleNamespace(user_id=user_id))
