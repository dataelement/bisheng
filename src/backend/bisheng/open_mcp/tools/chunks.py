"""Synchronous chunk-import MCP tool handlers."""

from __future__ import annotations

from bisheng.open_mcp import application, chunks
from bisheng.open_mcp.compatibility import map_file_record_to_mcp
from bisheng.open_mcp.contracts import KnowledgeChunksTextInput, KnowledgeChunksUploadInput
from bisheng.open_mcp.upload import prepared_upload


async def chunks_upload(arguments: KnowledgeChunksUploadInput):
    request = application.current_request()
    async with prepared_upload(arguments) as (path, _file_name):
        result = await chunks.upload_chunks(request=request, command=arguments, path=path)
    return map_file_record_to_mcp(result)


async def chunks_text(arguments: KnowledgeChunksTextInput):
    return map_file_record_to_mcp(await chunks.import_text_chunks(command=arguments))


CHUNKS_HANDLERS = {
    "bisheng_knowledge_chunks_upload": chunks_upload,
    "bisheng_knowledge_chunks_text": chunks_text,
}


__all__ = ["CHUNKS_HANDLERS"]
