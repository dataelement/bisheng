"""Server-side answer MCP tool handler."""

from __future__ import annotations

from bisheng.open_mcp import answer
from bisheng.open_mcp.compatibility import map_answer_to_mcp
from bisheng.open_mcp.contracts import KnowledgeAnswerInput


async def knowledge_answer(arguments: KnowledgeAnswerInput):
    return map_answer_to_mcp(await answer.answer_knowledge(command=arguments))


ANSWER_HANDLERS = {"bisheng_knowledge_answer": knowledge_answer}


__all__ = ["ANSWER_HANDLERS"]
