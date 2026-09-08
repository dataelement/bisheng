"""Dynamic LLM factory for ReAct: bind view_image only when the registry is filled.

Must not be a Runnable — create_react_agent treats a non-Runnable callable as a
per-turn model factory and will not compile-time bind ToolNode tools.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from loguru import logger

from bisheng.common.image_view.annotate import ImageRegistry
from bisheng.common.image_view.loop import (
    TOOL_NAME,
    _ai_message_for_second_round,
    _apply_suggested_ids,
    _collect_ai,
    _last_user_question,
    _suggested_ids_for,
    _synthetic_view_calls,
    _view_calls,
    prepare_vision_messages,
    question_needs_pixels,
)
from bisheng.common.image_view.relocate import relocate_images_to_human
from bisheng.common.image_view.tool import build_view_image_tool


def viewed_images_human_message(viewed: list[tuple[str, str]]) -> HumanMessage:
    blocks: list[dict] = [{"type": "text", "text": "Viewed images: " + ", ".join(image_id for image_id, _ in viewed)}]
    for _, data_uri in viewed:
        blocks.append({"type": "image_url", "image_url": {"url": data_uri}})
    return HumanMessage(content=blocks)


def messages_from_model_input(inp: Any) -> list[BaseMessage]:
    if isinstance(inp, dict):
        return list(inp.get("messages") or inp.get("llm_input_messages") or [])
    if isinstance(inp, list):
        return list(inp)
    return [inp]


def _messages_from_state(state: Any) -> list[BaseMessage]:
    if isinstance(state, dict):
        return list(state.get("messages") or [])
    return []


def _already_viewed(messages: list[BaseMessage]) -> bool:
    return any(isinstance(message, ToolMessage) and message.name == TOOL_NAME for message in messages)


def maybe_inject_view_image(ai: AIMessage, messages: list[BaseMessage], registry: ImageRegistry) -> AIMessage:
    """Force / rewrite view_image when the question needs pixels and the model skipped or mis-picked."""
    if _already_viewed(messages):
        return ai
    view_calls = _view_calls(ai)
    needs_pixels = question_needs_pixels(_last_user_question(messages))
    suggested = _suggested_ids_for(messages) if needs_pixels else []
    if needs_pixels and suggested:
        if view_calls:
            view_calls = _apply_suggested_ids(view_calls, suggested, registry)
        else:
            injected = _synthetic_view_calls(suggested, registry)
            if injected:
                logger.info("image_view injecting view_image ids={}", injected[0]["args"]["image_ids"])
                view_calls = injected
        if view_calls:
            return _ai_message_for_second_round(ai, view_calls)
    elif view_calls:
        return _ai_message_for_second_round(ai, view_calls)
    return ai


class _VisionCallRunnable(Runnable):
    """Relocate images, attach viewed pixels, optionally append rules, then call the bound LLM."""

    def __init__(self, bound: Any, extra_rules: bool, registry: ImageRegistry, hold_for_inject: bool):
        self._bound = bound
        self._extra_rules = extra_rules
        self._registry = registry
        self._hold_for_inject = hold_for_inject

    def _prepare(self, inp: Any) -> list[BaseMessage]:
        messages = messages_from_model_input(inp)
        viewed = self._registry.pop_viewed()
        if viewed:
            messages = [*messages, viewed_images_human_message(viewed)]
        messages = relocate_images_to_human(messages)
        if self._extra_rules:
            messages = prepare_vision_messages(messages)
        return messages

    def _bound_config(self, config):
        if not self._hold_for_inject:
            return config
        if config is None:
            return {"callbacks": []}
        if isinstance(config, dict):
            silent = dict(config)
            silent["callbacks"] = []
            return silent
        return config

    def invoke(self, inp: Any, config=None, **kwargs: Any):
        messages = self._prepare(inp)
        result = self._bound.invoke(messages, config=self._bound_config(config), **kwargs)
        if isinstance(result, AIMessage):
            return maybe_inject_view_image(result, messages, self._registry)
        return result

    async def ainvoke(self, inp: Any, config=None, **kwargs: Any):
        messages = self._prepare(inp)
        call_config = self._bound_config(config)
        if hasattr(self._bound, "ainvoke"):
            result = await self._bound.ainvoke(messages, config=call_config, **kwargs)
        elif hasattr(self._bound, "astream"):
            chunks: list[Any] = []
            async for chunk in self._bound.astream(messages, config=call_config, **kwargs):
                chunks.append(chunk)
            result = _collect_ai(chunks)
        else:
            result = self._bound.invoke(messages, config=call_config, **kwargs)
        if isinstance(result, AIMessage):
            return maybe_inject_view_image(result, messages, self._registry)
        return result

    async def astream(self, inp: Any, config=None, **kwargs: Any):
        messages = self._prepare(inp)
        call_config = self._bound_config(config)
        if not self._hold_for_inject:
            async for chunk in self._bound.astream(messages, config=call_config, **kwargs):
                yield chunk
            return
        chunks: list[Any] = []
        async for chunk in self._bound.astream(messages, config=call_config, **kwargs):
            chunks.append(chunk)
        ai = _collect_ai(chunks)
        injected = maybe_inject_view_image(ai, messages, self._registry)
        if injected.tool_calls:
            yield injected
            return
        for chunk in chunks:
            yield chunk


class VisionToolBindWrapper:
    """Per-turn model factory: bind view_image only after the registry is filled."""

    def __init__(self, llm: Any, registry: ImageRegistry, base_tools: list[BaseTool]):
        self._llm = llm
        self._registry = registry
        self._base_tools = list(base_tools)
        self._view_tool = build_view_image_tool(registry)

    def __call__(self, state, runtime):
        messages = _messages_from_state(state)
        needs_pixels = question_needs_pixels(_last_user_question(messages)) if messages else False
        viewed = _already_viewed(messages)
        bind_kwargs: dict[str, Any] = {}
        if len(self._registry) > 0:
            tools = [*self._base_tools, self._view_tool]
            extra_rules = True
            if needs_pixels and not viewed:
                bind_kwargs["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}
                logger.info("image_view forcing tool_choice={}", TOOL_NAME)
        else:
            tools = list(self._base_tools)
            extra_rules = False
        bound = self._llm.bind_tools(tools, **bind_kwargs) if tools else self._llm
        hold_for_inject = extra_rules and needs_pixels and not viewed
        return _VisionCallRunnable(
            bound,
            extra_rules=extra_rules,
            registry=self._registry,
            hold_for_inject=hold_for_inject,
        )
