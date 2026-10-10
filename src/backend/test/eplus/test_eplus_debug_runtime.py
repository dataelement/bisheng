"""Exercise both real assistant executors with deterministic local models."""

from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.eplus.domain.schemas.debug import DebugRunRequest
from bisheng.eplus.infrastructure.debug_runtime import DebugAssistantRuntime
from bisheng.eplus.infrastructure.debug_trace import DebugTrace
from test.eplus.test_eplus_debug_admission import snapshot
from test.eplus.test_eplus_debug_trace import wrapper


class Agent:
    def __init__(self, assistant, conversation_id, user_id):
        assert conversation_id.startswith("eplus-debug-")
        assert user_id == 2
        self.supports_vision = False
        self.llm = SimpleNamespace(model_name="actual-model")
        self.current_agent_executor = "ReAct"

    async def init_llm(self):
        pass

    async def init_tools(self, context):
        assert context.robot_scope.space_ids == (11,)
        self.tools = [wrapper(), SimpleNamespace(name="dangerous")]

    async def init_agent(self):
        assert [t.name for t in self.tools] == ["eplus_robot_knowledge"]

    async def astream(self, query, history, context):
        assert query == ""
        assert history == [HumanMessage(content="old"), AIMessage(content="answer")]
        assert context.content == "new"
        yield [AIMessageChunk(content="text")]


async def test_runtime_uses_robot_context_and_only_test_history():
    trace = DebugTrace()
    request = DebugRunRequest(query="new", test_user_id=2, history=[{"question": "old", "answer": "answer"}])
    runtime = DebugAssistantRuntime(agent_factory=Agent)
    assert [s async for s in runtime.run(snapshot(), request, trace)] == ["text"]
    event = trace.events[0]["data"]
    assert event["model_name"] == "actual-model"
    assert event["disabled_tools"] == ["dangerous"]
    assert trace.tool_call_count == 0


async def test_runtime_refuses_shared_history_file_mode(monkeypatch):
    monkeypatch.setenv("BISHENG_RECORD_HISTORY", "1")
    with pytest.raises(RuntimeError):
        _ = [
            s
            async for s in DebugAssistantRuntime(agent_factory=Agent).run(
                snapshot(), DebugRunRequest(query="hi", test_user_id=2), DebugTrace()
            )
        ]


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        assert [t.name for t in tools] == ["eplus_robot_knowledge"]
        return self


@pytest.mark.parametrize("mode", ["ReAct", "function call"])
async def test_actual_assistant_executor_observes_tool_then_returns_answer(mode, monkeypatch):
    from dataclasses import replace
    from unittest.mock import patch

    assistant = SimpleNamespace(
        id="a", name="A", model_name="30", tenant_id=7, prompt="Use the configured knowledge tool.", max_token=4096
    )
    if mode == "ReAct":
        responses = [
            AIMessage(
                content='Action:\n```json\n{"action":"eplus_robot_knowledge","action_input":{"query":"empty"}}\n```'
            ),
            AIMessage(content='Action:\n```json\n{"action":"Final Answer","action_input":"done"}\n```'),
        ]
    else:
        responses = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "eplus_robot_knowledge", "args": {"query": "empty"}, "id": "call-1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="done"),
        ]

    class ActualAgent(AssistantAgent):
        async def init_llm(self):
            self.llm = ToolModel(responses=responses)
            self.llm_agent_executor = mode

        async def init_tools(self, context):
            self.tools = [wrapper()]

    trace = DebugTrace()
    with patch(
        "bisheng.api.services.assistant_agent.KnowledgeUtils.format_retrieved_chunk",
        lambda d, n: d.page_content,
        create=True,
    ):
        output = "".join(
            [
                s
                async for s in DebugAssistantRuntime(agent_factory=ActualAgent).run(
                    replace(snapshot(), assistant=assistant), DebugRunRequest(query="search", test_user_id=2), trace
                )
            ]
        )
    assert output == "done"
    assert trace.tool_call_count == 1
    assert trace.events[-1]["data"]["model_tool_output"] == "[]"


async def test_real_react_reports_tool_failure_even_when_final_answer_succeeds():
    from dataclasses import replace

    class ActualAgent(AssistantAgent):
        async def init_llm(self):
            self.llm = ToolModel(
                responses=[
                    AIMessage(
                        content='Action:\n```json\n{"action":"eplus_robot_knowledge","action_input":{"query":"fail"}}\n```'
                    ),
                    AIMessage(content='Action:\n```json\n{"action":"Final Answer","action_input":"tool failed"}\n```'),
                ]
            )
            self.llm_agent_executor = "ReAct"

        async def init_tools(self, context):
            self.tools = [wrapper()]

    trace = DebugTrace()
    assistant = SimpleNamespace(
        id="a", name="A", model_name="30", tenant_id=7, prompt="Keep the existing prompt.", max_token=4096
    )
    output = "".join(
        [
            s
            async for s in DebugAssistantRuntime(agent_factory=ActualAgent).run(
                replace(snapshot(), assistant=assistant), DebugRunRequest(query="search", test_user_id=2), trace
            )
        ]
    )
    assert output == "tool failed"
    assert [e["type"] for e in trace.events] == ["context", "tool_start", "tool_error"]
