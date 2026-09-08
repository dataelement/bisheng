"""LangGraph ReAct loop for knowledge-space / channel vision chat (F061 increment).

Yields the same model chunks as the old run_vision_tool_loop. Does not construct ChatResponse.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode, create_react_agent
from loguru import logger

from bisheng.common.image_view.annotate import ImageRegistry
from bisheng.common.image_view.tool import TOOL_NAME, build_view_image_tool
from bisheng.common.image_view.vision_llm import VisionToolBindWrapper

REACT_RECURSION_LIMIT = 8


def _handle_view_tool_error(exc: Exception) -> str:
    logger.exception("view_image invoke failed; returning observation")
    return "Image is not available."


def _chunk_has_tool_call(chunk: Any) -> bool:
    if getattr(chunk, "tool_calls", None):
        return True
    if getattr(chunk, "tool_call_chunks", None):
        return True
    return False


def _chunk_visible(chunk: Any) -> bool:
    if _chunk_has_tool_call(chunk):
        return False
    content = getattr(chunk, "content", "") or ""
    if content:
        return True
    extra = getattr(chunk, "additional_kwargs", None) or {}
    return bool(extra.get("reasoning_content"))


def _message_from_event_output(output: Any) -> AIMessage | None:
    if isinstance(output, AIMessage):
        return output
    generations = getattr(output, "generations", None)
    if generations:
        message = getattr(generations[0], "message", None)
        if isinstance(message, AIMessage):
            return message
    if isinstance(output, dict):
        inner = output.get("messages")
        if isinstance(inner, list) and inner and isinstance(inner[-1], AIMessage):
            return inner[-1]
        inner = output.get("output")
        if isinstance(inner, AIMessage):
            return inner
    return None


async def run_react_vision_stream(
    llm: Any,
    messages: list,
    registry: ImageRegistry,
    *,
    visual: bool,
) -> AsyncIterator[Any]:
    """Yield LLM chunks. Uses ReAct when visual and the registry has images."""
    if not visual or len(registry) == 0:
        logger.info("image_view skip bind visual={} registry_size={}", visual, len(registry))
        async for chunk in llm.astream(messages):
            yield chunk
        return

    logger.info(
        "image_view react_loop recursion={} registry_size={}",
        REACT_RECURSION_LIMIT,
        len(registry),
    )
    view_tool = build_view_image_tool(registry)
    tool_node = ToolNode([view_tool], handle_tool_errors=_handle_view_tool_error)
    agent = create_react_agent(
        VisionToolBindWrapper(llm, registry, []),
        tool_node,
    )
    streamed_this_model = False
    emitted: set[tuple] = set()
    async for ev in agent.astream_events(
        {"messages": messages},
        version="v2",
        config=RunnableConfig(recursion_limit=REACT_RECURSION_LIMIT),
    ):
        et = ev.get("event", "")
        if et == "on_chat_model_start":
            streamed_this_model = False
            continue
        if et == "on_chat_model_stream":
            if (ev.get("name") or "") == TOOL_NAME:
                continue
            chunk = (ev.get("data") or {}).get("chunk")
            if chunk is None or not _chunk_visible(chunk):
                continue
            streamed_this_model = True
            yield chunk
            continue
        if et == "on_chat_model_end":
            if streamed_this_model:
                # Keep the flag until the next model start. Resetting here lets
                # the wrapping Runnable's on_chain_end re-yield the full answer
                # after token deltas — knowledge-space concatenates both.
                continue
            message = _message_from_event_output((ev.get("data") or {}).get("output"))
            if message is None or not _chunk_visible(message):
                continue
            key = (getattr(message, "id", None), getattr(message, "content", ""))
            if key in emitted:
                continue
            emitted.add(key)
            streamed_this_model = True
            yield message
            continue
        if et == "on_chain_end":
            if streamed_this_model:
                continue
            message = _message_from_event_output((ev.get("data") or {}).get("output"))
            if message is None or not _chunk_visible(message):
                continue
            key = (getattr(message, "id", None), getattr(message, "content", ""))
            if key in emitted:
                continue
            emitted.add(key)
            streamed_this_model = True
            yield message
