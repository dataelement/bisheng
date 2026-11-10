"""Send earlier assistant reasoning back with a tool-calling request.

DeepSeek's thinking-mode contract: when the request carries ``tools``, every
earlier assistant message's ``reasoning_content`` goes back and is spliced into
the context (the official API rejects the request otherwise); without ``tools``
it is ignored. On 106 the dsv4 vLLM template behaved the same way, and because
BiSheng never sent it, task mode re-derived a 15k-token analysis after each tool
call (svid 2009d685 and 4c85fb69, 2026-10-23).

Nothing is attached to a request without ``tools``: DeepSeek ignores it there,
and another provider might reject the field or splice it in.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage


def attach_reasoning(payload: dict, messages: Sequence[BaseMessage], *, missing: str | None = None) -> dict:
    """Copy each AIMessage's ``reasoning_content`` onto its assistant payload entry.

    ``missing`` is what an AIMessage without reasoning gets: ``None`` leaves the
    entry alone; DeepSeek's official API wants the key present, so it passes "".
    """
    if not payload.get("tools"):
        return payload
    entries = payload.get("messages")
    if not isinstance(entries, list) or len(entries) != len(messages):
        # Not a 1:1 chat-completions conversion (e.g. the Responses API); nothing to pair.
        return payload
    for entry, message in zip(entries, messages, strict=True):
        if not isinstance(message, AIMessage) or not isinstance(entry, dict) or entry.get("role") != "assistant":
            continue
        reasoning = message.additional_kwargs.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            entry["reasoning_content"] = reasoning
        elif missing is not None:
            entry["reasoning_content"] = missing
    return payload
