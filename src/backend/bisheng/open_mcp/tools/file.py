"""Knowledge-file MCP tool handlers."""

from __future__ import annotations

from bisheng.open_mcp import application
from bisheng.open_mcp.compatibility import map_file_list_to_mcp, map_file_record_to_mcp
from bisheng.open_mcp.contracts import (
    KnowledgeFileDeleteInput,
    KnowledgeFileListInput,
    KnowledgeFilesDeleteInput,
    KnowledgeFileUploadInput,
    OperationResult,
)
from bisheng.open_mcp.upload import prepared_upload


async def knowledge_file_upload(arguments: KnowledgeFileUploadInput):
    async with application.knowledge_repositories() as (version_repo, doc_repo):
        request = application.current_request()
        await application.ensure_upload_allowed(
            request=request,
            command=arguments,
            version_repo=version_repo,
            doc_repo=doc_repo,
        )
        async with prepared_upload(arguments) as (path, file_name):
            result = await application.upload_knowledge_file(
                request=request,
                command=arguments,
                path=path,
                file_name=file_name,
                version_repo=version_repo,
                doc_repo=doc_repo,
            )
    return map_file_record_to_mcp(result)


async def knowledge_file_list(arguments: KnowledgeFileListInput):
    async with application.knowledge_repositories() as (version_repo, doc_repo):
        result = await application.list_knowledge_files(
            request=application.current_request(),
            command=arguments,
            version_repo=version_repo,
            doc_repo=doc_repo,
        )
    return map_file_list_to_mcp(result)


async def knowledge_file_delete(arguments: KnowledgeFileDeleteInput):
    await application.delete_knowledge_files(
        request=application.current_request(),
        file_ids=[arguments.file_id],
    )
    return OperationResult()


async def knowledge_files_delete(arguments: KnowledgeFilesDeleteInput):
    await application.delete_knowledge_files(
        request=application.current_request(),
        file_ids=arguments.file_ids,
    )
    return OperationResult()


FILE_HANDLERS = {
    "bisheng_knowledge_file_upload": knowledge_file_upload,
    "bisheng_knowledge_file_list": knowledge_file_list,
    "bisheng_knowledge_file_delete": knowledge_file_delete,
    "bisheng_knowledge_files_delete": knowledge_files_delete,
}


__all__ = ["FILE_HANDLERS"]
