"""Tool errors must not abort the daily-chat agent loop.

A tool runtime failure should be fed back to the model as an observation
(ToolMessage with status='error') instead of propagating out of the agent
stream and crashing the whole chat. We assert the real code path:
`create_react_agent` wired with a `ToolNode` that uses our error handler.
"""

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode, create_react_agent

from bisheng.workstation.domain.services.chat_service import (
    _extract_tool_error,
    _handle_agent_tool_error,
)


@tool
def _boom(query: str) -> str:
    """A tool that always fails."""
    raise Exception("Request failed: 403 - not enough quota")


class _FakeToolCallingModel(BaseChatModel):
    """Calls `_boom` once, then answers after seeing the tool observation."""

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # If we've already received a tool observation, give a final answer.
        if any(isinstance(m, ToolMessage) for m in messages):
            msg = AIMessage(content="Sorry, the web search failed.")
        else:
            msg = AIMessage(
                content="",
                tool_calls=[{"name": "_boom", "args": {"query": "x"}, "id": "call_1"}],
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])


async def test_agent_survives_tool_error():
    """A failing tool yields an error ToolMessage and the agent still finishes."""
    tool_node = ToolNode([_boom], handle_tool_errors=_handle_agent_tool_error)
    agent = create_react_agent(_FakeToolCallingModel(), tool_node)

    result = await agent.ainvoke({"messages": [("user", "search something")]})
    msgs = result["messages"]

    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].status == "error"
    assert "403" in tool_msgs[0].content

    # The loop continued past the error to a final assistant answer.
    assert isinstance(msgs[-1], AIMessage)
    assert msgs[-1].content == "Sorry, the web search failed."


def test_handle_agent_tool_error_returns_string():
    msg = _handle_agent_tool_error(Exception("boom"))
    assert isinstance(msg, str)
    assert "boom" in msg


def test_extract_tool_error_from_error_message():
    tm = ToolMessage(content="工具执行失败: boom", tool_call_id="x", status="error")
    assert _extract_tool_error(tm) == "工具执行失败: boom"


def test_extract_tool_error_none_on_success():
    tm = ToolMessage(content="ok", tool_call_id="x", status="success")
    assert _extract_tool_error(tm) is None
    assert _extract_tool_error("plain string") is None
    assert _extract_tool_error(None) is None
