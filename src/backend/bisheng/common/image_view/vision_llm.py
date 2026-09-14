"""Dynamic LLM factory for ReAct: bind view_image only when the registry is filled.

Must not be a Runnable — create_react_agent treats a non-Runnable callable as a
per-turn model factory and will not compile-time bind ToolNode tools.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
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
    failed_image_ids,
    pixels_were_viewed,
    prepare_vision_messages,
    question_needs_pixels,
)
from bisheng.common.image_view.relocate import relocate_images_to_human
from bisheng.common.image_view.tool import build_view_image_tool

RETRIEVE_BEFORE_VIEW_RULES = (
    "知识库文件不在代码执行器工作目录。"
    "用户问知识库中的截图 / 界面 / 图片时，必须先调用 search_knowledge_bases，"
    "不要用代码执行器查找或抽取这些 PDF。"
    "检索返回的 markdown 图会带 ⟦img#N⟧，然后再调用 view_image。"
)
_SYNTHETIC_RETRIEVE_ID = "search_kb_forced"


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
    return pixels_were_viewed(messages)


def _already_retrieved(messages: list[BaseMessage], tool_name: str) -> bool:
    return any(isinstance(message, ToolMessage) and message.name == tool_name for message in messages)


def _retrieve_query(messages: list[BaseMessage]) -> str:
    return _last_user_question(messages).strip()


def maybe_inject_retrieve(ai: AIMessage, messages: list[BaseMessage], retrieve_tool_name: str | None) -> AIMessage:
    """Force search_knowledge_bases when the model goes to the sandbox instead."""
    if not retrieve_tool_name:
        return ai
    if _already_retrieved(messages, retrieve_tool_name):
        return ai
    calls = list(ai.tool_calls or [])
    if any(call.get("name") == retrieve_tool_name for call in calls):
        return ai
    query = _retrieve_query(messages)
    if not query:
        return ai
    logger.info("image_view injecting retrieve tool={} query={!r}", retrieve_tool_name, query[:80])
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": retrieve_tool_name,
                "args": {"knowledge_base_ids": [], "query": query},
                "id": _SYNTHETIC_RETRIEVE_ID,
                "type": "tool_call",
            }
        ],
    )


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
    if view_calls and not suggested and failed_image_ids(messages):
        logger.info("image_view skip retry failed_ids={}", sorted(failed_image_ids(messages)))
        return AIMessage(content=ai.content if isinstance(ai.content, str) else "")
    if view_calls:
        return _ai_message_for_second_round(ai, view_calls)
    return ai


class _VisionCallRunnable(Runnable):
    """Relocate images, attach viewed pixels, optionally append rules, then call the bound LLM."""

    def __init__(
        self,
        bound: Any,
        extra_rules: bool,
        registry: ImageRegistry,
        hold_for_inject: bool,
        retrieve_tool_name: str | None = None,
        retrieve_hint: bool = False,
    ):
        self._bound = bound
        self._extra_rules = extra_rules
        self._registry = registry
        self._hold_for_inject = hold_for_inject
        self._retrieve_tool_name = retrieve_tool_name
        self._retrieve_hint = retrieve_hint

    def _prepare(self, inp: Any) -> list[BaseMessage]:
        messages = messages_from_model_input(inp)
        viewed = self._registry.pop_viewed()
        if viewed:
            messages = [*messages, viewed_images_human_message(viewed)]
        messages = relocate_images_to_human(messages)
        if self._extra_rules:
            messages = prepare_vision_messages(messages)
        elif self._retrieve_hint:
            messages = [SystemMessage(content=RETRIEVE_BEFORE_VIEW_RULES), *messages]
        return messages

    def _after_model(self, result: Any, messages: list[BaseMessage]) -> Any:
        if not isinstance(result, AIMessage):
            return result
        result = maybe_inject_view_image(result, messages, self._registry)
        if self._retrieve_hint:
            result = maybe_inject_retrieve(result, messages, self._retrieve_tool_name)
        return result

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
        return self._after_model(result, messages)

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
        return self._after_model(result, messages)

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
        injected = self._after_model(ai, messages)
        if isinstance(injected, AIMessage) and injected.tool_calls:
            yield injected
            return
        for chunk in chunks:
            yield chunk


class VisionToolBindWrapper:
    """Per-turn model factory: bind view_image only after the registry is filled."""

    def __init__(
        self,
        llm: Any,
        registry: ImageRegistry,
        base_tools: list[BaseTool],
        *,
        retrieve_tool_name: str | None = None,
    ):
        self._llm = llm
        self._registry = registry
        self._base_tools = list(base_tools)
        self._view_tool = build_view_image_tool(registry)
        self._retrieve_tool_name = retrieve_tool_name

    def __call__(self, state, runtime):
        messages = _messages_from_state(state)
        needs_pixels = question_needs_pixels(_last_user_question(messages)) if messages else False
        viewed = _already_viewed(messages)
        bind_kwargs: dict[str, Any] = {}
        retrieve_hint = False
        if len(self._registry) > 0:
            tools = [*self._base_tools, self._view_tool]
            extra_rules = True
            remaining = _suggested_ids_for(messages) if needs_pixels else []
            exhausted = bool(failed_image_ids(messages)) and not remaining
            if needs_pixels and not viewed and not exhausted:
                bind_kwargs["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}
                logger.info("image_view forcing tool_choice={}", TOOL_NAME)
        else:
            tools = list(self._base_tools)
            extra_rules = False
            retrieve_ready = bool(
                self._retrieve_tool_name
                and needs_pixels
                and any(getattr(tool, "name", None) == self._retrieve_tool_name for tool in tools)
                and not _already_retrieved(messages, self._retrieve_tool_name)
            )
            if retrieve_ready:
                retrieve_hint = True
                bind_kwargs["tool_choice"] = {
                    "type": "function",
                    "function": {"name": self._retrieve_tool_name},
                }
                logger.info("image_view forcing retrieve tool={}", self._retrieve_tool_name)
            else:
                logger.info(
                    "image_view skip view_image registry_size=0 tools={} needs_pixels={}",
                    [getattr(tool, "name", "") for tool in tools],
                    needs_pixels,
                )
        bound = self._llm.bind_tools(tools, **bind_kwargs) if tools else self._llm
        hold_for_inject = (extra_rules and needs_pixels and not viewed) or retrieve_hint
        return _VisionCallRunnable(
            bound,
            extra_rules=extra_rules,
            registry=self._registry,
            hold_for_inject=hold_for_inject,
            retrieve_tool_name=self._retrieve_tool_name,
            retrieve_hint=retrieve_hint,
        )
