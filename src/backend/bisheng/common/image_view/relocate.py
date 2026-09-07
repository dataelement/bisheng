"""Move image blocks from ToolMessage onto a HumanMessage (Kimi rejects tool-role images)."""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage


def _is_image_block(block: object) -> bool:
    if not isinstance(block, dict):
        return False
    return block.get("type") in {"image_url", "image"}


def relocate_images_to_human(messages: list[BaseMessage]) -> list[BaseMessage]:
    relocated: list[dict] = []
    out: list[BaseMessage] = []
    for message in messages:
        if not isinstance(message, ToolMessage) or not isinstance(message.content, list):
            out.append(message)
            continue
        kept: list[object] = []
        for block in message.content:
            if _is_image_block(block):
                relocated.append(block)
            else:
                kept.append(block)
        if len(kept) == 1 and isinstance(kept[0], dict) and kept[0].get("type") == "text":
            content: object = kept[0].get("text") or ""
        elif not kept:
            content = ""
        else:
            content = kept
        out.append(
            ToolMessage(
                content=content,
                tool_call_id=message.tool_call_id,
                name=message.name,
            )
        )
    if relocated:
        out.append(
            HumanMessage(
                content=[
                    {"type": "text", "text": "Images from the tool result."},
                    *relocated,
                ]
            )
        )
    return out
