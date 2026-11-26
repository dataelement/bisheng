"""A deterministic chat model for the unified-runtime spikes.

It replays a fixed list of AIMessages and records the messages it received on
every call, so a spike can assert what the agent loop actually sent to the model
without needing a real LLM endpoint.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def tool_call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class ScriptedModel(BaseChatModel):
    script: list[AIMessage]
    seen: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tool_names: list[str] = Field(default_factory=list)
    on_call: Any = None  # optional callable(call_index) run before each reply

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        names = []
        for t in tools:
            name = getattr(t, "name", None)
            if name is None and isinstance(t, dict):
                name = t.get("name") or t.get("function", {}).get("name")
            names.append(str(name))
        self.bound_tool_names = names
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        index = len(self.seen)
        self.seen.append(list(messages))
        if self.on_call is not None:
            self.on_call(index)
        reply = self.script[min(index, len(self.script) - 1)]
        return ChatResult(generations=[ChatGeneration(message=reply)])
