"""view_image StructuredTool. Looks up ImageRegistry only — no arbitrary URLs."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from bisheng.common.image_view.annotate import ImageRegistry
from bisheng.common.image_view.fetch import fetch_and_encode

MAX_IMAGES_PER_TURN = 3
TOOL_NAME = "view_image"


class ViewImageArgs(BaseModel):
    image_ids: list[str] = Field(
        description="img#N ids whose nearby heading matches the question; do not default to img#1"
    )
    quality: str = Field(default="standard", description="v1 only accepts standard")


async def _view_image(registry: ImageRegistry, image_ids: list[str], quality: str) -> str:
    if quality != "standard":
        return "Only standard quality is supported."

    lines: list[str] = []
    to_fetch = image_ids[:MAX_IMAGES_PER_TURN]
    overflow = image_ids[MAX_IMAGES_PER_TURN:]

    for image_id in to_fetch:
        entry = registry.get(image_id)
        if not entry:
            lines.append(f"Image {image_id} is not available in this turn.")
            continue
        result = await fetch_and_encode(entry["url"])
        if result.ok and result.data_uri:
            registry.record_viewed(image_id, result.data_uri)
            lines.append(f"Viewed {image_id} at standard quality.")
        else:
            lines.append(f"Image {image_id} is not available.")

    if overflow:
        extra = ", ".join(overflow)
        lines.append(f"{extra} not fetched: limit is {MAX_IMAGES_PER_TURN} images per turn.")

    return "\n".join(lines)


def build_view_image_tool(registry: ImageRegistry) -> StructuredTool:
    async def _run(image_ids: list[str], quality: str = "standard") -> str:
        return await _view_image(registry, image_ids, quality)

    return StructuredTool.from_function(
        func=None,
        coroutine=_run,
        name=TOOL_NAME,
        description=(
            "View numbered images from this turn. Required argument: image_ids "
            "(list of img#N). Pick ids whose nearby heading/caption matches the "
            "question; do not default to img#1. Do not pass URLs. Max 3 per call."
        ),
        args_schema=ViewImageArgs,
    )
