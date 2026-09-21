"""F067 MCP tool handler dispatch."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from bisheng.open_mcp.registry import TOOL_REGISTRY
from bisheng.open_mcp.tools.file import FILE_HANDLERS
from bisheng.open_mcp.tools.knowledge import KNOWLEDGE_HANDLERS

TOOL_HANDLERS = {**KNOWLEDGE_HANDLERS, **FILE_HANDLERS}


async def execute_tool(name: str, arguments: dict[str, Any]) -> BaseModel:
    definition = TOOL_REGISTRY[name]
    command = definition.input_model.model_validate(arguments)
    return await TOOL_HANDLERS[name](command)


__all__ = ["TOOL_HANDLERS", "execute_tool"]
