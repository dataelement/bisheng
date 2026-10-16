"""F078 T21: the agent node's function-call branch moves to create_agent unchanged.

Runs the same tool-calling conversation through the old builder
(``create_react_agent``) and the new one, and compares what the model saw and
what came back (spec AC-25).
"""

import warnings

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from bisheng.workflow.nodes.agent.agent import build_function_call_agent


@tool
def lookup(query: str) -> str:
    """Look something up."""
    return f"result for {query}"


# Module-level on purpose: a pydantic field would be copied per model instance.
CALLS: list = []


class _ScriptedModel(BaseChatModel):
    """Calls ``lookup`` once, then answers; records every request in CALLS."""

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        CALLS.append(("bind", sorted(getattr(t, "name", None) or t.get("name") for t in tools)))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        CALLS.append(("call", [(type(m).__name__, m.content) for m in messages]))
        if not any(isinstance(m, ToolMessage) for m in messages):
            message = AIMessage(content="", tool_calls=[{"name": "lookup", "args": {"query": "q"}, "id": "c1"}])
        else:
            message = AIMessage(content="final answer")
        return ChatResult(generations=[ChatGeneration(message=message)])


def _run(agent_factory):
    CALLS.clear()
    agent = agent_factory(_ScriptedModel(), [lookup], "你是助手。")
    history = [HumanMessage(content="earlier"), AIMessage(content="earlier answer"), HumanMessage(content="now")]
    result = agent.invoke({"messages": history})
    return list(CALLS), [(type(m).__name__, m.content) for m in result["messages"]]


def _legacy(llm, tools, prompt):
    from langgraph.prebuilt import create_react_agent

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return create_react_agent(llm, tools, prompt=prompt, checkpointer=False)


def _new(llm, tools, prompt):
    return build_function_call_agent(llm, tools, prompt, middleware=[])


def test_create_agent_matches_create_react_agent_without_skills():
    legacy_calls, legacy_messages = _run(_legacy)
    new_calls, new_messages = _run(_new)

    def model_requests(calls):
        return [payload for kind, payload in calls if kind == "call"]

    def bound_tools(calls):
        return {tuple(payload) for kind, payload in calls if kind == "bind"}

    assert bound_tools(new_calls) == bound_tools(legacy_calls) == {("lookup",)}
    assert model_requests(new_calls) == model_requests(legacy_calls)
    assert model_requests(new_calls)[0][0] == ("SystemMessage", "你是助手。")
    assert new_messages == legacy_messages
    assert new_messages[-1] == ("AIMessage", "final answer")
