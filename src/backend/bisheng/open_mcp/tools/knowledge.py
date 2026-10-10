"""Knowledge-resource MCP tool handlers."""

from __future__ import annotations

from bisheng.open_mcp import application
from bisheng.open_mcp.compatibility import (
    map_knowledge_resource_to_mcp,
    map_resource_list_to_mcp,
    map_retrieve_to_mcp,
)
from bisheng.open_mcp.contracts import (
    KnowledgeCreateInput,
    KnowledgeIdInput,
    KnowledgeListInput,
    KnowledgeRetrieveInput,
    KnowledgeUpdateInput,
    OperationResult,
)


async def knowledge_list(arguments: KnowledgeListInput):
    async with application.knowledge_repositories() as (version_repo, doc_repo):
        result = await application.list_knowledge(
            request=application.current_request(),
            command=arguments,
            version_repo=version_repo,
            doc_repo=doc_repo,
        )
    return map_resource_list_to_mcp(result)


async def knowledge_create(arguments: KnowledgeCreateInput):
    async with application.knowledge_repositories() as (version_repo, doc_repo):
        result = await application.create_knowledge(
            request=application.current_request(),
            command=arguments,
            version_repo=version_repo,
            doc_repo=doc_repo,
        )
    return map_knowledge_resource_to_mcp(result)


async def knowledge_update(arguments: KnowledgeUpdateInput):
    async with application.knowledge_repositories() as (version_repo, doc_repo):
        result = await application.update_knowledge(
            request=application.current_request(),
            command=arguments,
            version_repo=version_repo,
            doc_repo=doc_repo,
        )
    return map_knowledge_resource_to_mcp(result)


async def knowledge_delete(arguments: KnowledgeIdInput):
    async with application.knowledge_repositories() as (version_repo, doc_repo):
        await application.delete_knowledge(
            request=application.current_request(),
            knowledge_id=arguments.knowledge_id,
            version_repo=version_repo,
            doc_repo=doc_repo,
        )
    return OperationResult()


async def knowledge_clear(arguments: KnowledgeIdInput):
    async with application.knowledge_repositories() as (version_repo, doc_repo):
        await application.clear_knowledge(
            request=application.current_request(),
            knowledge_id=arguments.knowledge_id,
            version_repo=version_repo,
            doc_repo=doc_repo,
        )
    return OperationResult()


async def knowledge_retrieve(arguments: KnowledgeRetrieveInput):
    async with application.knowledge_repositories() as (version_repo, _doc_repo):
        result = await application.retrieve_knowledge(
            request=application.current_request(),
            command=arguments,
            version_repo=version_repo,
        )
    return map_retrieve_to_mcp(result)


KNOWLEDGE_HANDLERS = {
    "bisheng_knowledge_list": knowledge_list,
    "bisheng_knowledge_create": knowledge_create,
    "bisheng_knowledge_update": knowledge_update,
    "bisheng_knowledge_delete": knowledge_delete,
    "bisheng_knowledge_clear": knowledge_clear,
    "bisheng_knowledge_retrieve": knowledge_retrieve,
}


__all__ = ["KNOWLEDGE_HANDLERS"]
