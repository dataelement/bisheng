"""Read visible text and reasoning without flattening model content blocks."""

from typing import Any


def extract_message_text(message: Any) -> str:
    """Accept legacy text and Responses blocks, excluding non-text payloads."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in ("text", "output_text"):
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def extract_message_reasoning(message: Any) -> str:
    """Keep legacy reasoning or Responses summaries on the thinking channel."""
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        reasoning = additional_kwargs.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            return reasoning
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "reasoning":
            continue
        # LangChain's standard blocks use reasoning; Responses uses summary.
        reasoning = block.get("reasoning")
        if isinstance(reasoning, str):
            parts.append(reasoning)
            continue
        summary = block.get("summary")
        if isinstance(summary, list):
            for item in summary:
                if isinstance(item, dict) and item.get("type") == "summary_text":
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
    return "".join(parts)
