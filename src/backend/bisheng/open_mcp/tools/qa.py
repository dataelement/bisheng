"""QA-library MCP tool handlers."""

from __future__ import annotations

from bisheng.open_mcp import qa
from bisheng.open_mcp.compatibility import map_qa_item_to_mcp, map_qa_list_to_mcp
from bisheng.open_mcp.contracts import (
    OperationResult,
    QaAddInput,
    QaAddRelativeInput,
    QaDeleteInput,
    QaDetailInput,
    QaQueryInput,
    QaUpdateInput,
)


async def qa_query(arguments: QaQueryInput):
    return map_qa_list_to_mcp(await qa.query_qa(time_range=arguments.time_range))


async def qa_detail(arguments: QaDetailInput):
    return map_qa_item_to_mcp(await qa.detail_qa(qa_id=arguments.id))


async def qa_add(arguments: QaAddInput):
    return map_qa_list_to_mcp(await qa.add_qa(knowledge_id=arguments.knowledge_id, items=arguments.data))


async def qa_add_relative(arguments: QaAddRelativeInput):
    result = await qa.add_relative_qa(
        knowledge_id=arguments.knowledge_id,
        qa_id=arguments.id,
        relative_questions=arguments.relative_questions,
    )
    return map_qa_item_to_mcp(result)


async def qa_update(arguments: QaUpdateInput):
    await qa.update_qa(command=arguments)
    return OperationResult()


async def qa_delete(arguments: QaDeleteInput):
    await qa.delete_qa(qa_id=arguments.id, question=arguments.question)
    return OperationResult()


QA_HANDLERS = {
    "bisheng_knowledge_qa_query": qa_query,
    "bisheng_knowledge_qa_detail": qa_detail,
    "bisheng_knowledge_qa_add": qa_add,
    "bisheng_knowledge_qa_add_relative": qa_add_relative,
    "bisheng_knowledge_qa_update": qa_update,
    "bisheng_knowledge_qa_delete": qa_delete,
}


__all__ = ["QA_HANDLERS"]
