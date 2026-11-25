"""MCP-local orchestration for synchronous chunk import.

Mirrors ``POST /api/v2/filelib/chunks`` (file import that waits for parsing)
and ``POST /api/v2/filelib/chunks_string`` (import a list of text segments)
without calling the FastAPI endpoint functions.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.documents import Document
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from bisheng.api.services.knowledge_imp import text_knowledge
from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess
from bisheng.core.cache.utils import save_download_file
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async
from bisheng.open_mcp.upload import safe_file_name
from bisheng.role.domain.services.quota_service import QuotaService
from bisheng.utils.util import sync_func_to_async


async def upload_chunks(*, request: Request, command, path: str) -> Any:
    """Import one staged file and wait until parsing finishes."""
    login_user = await get_open_api_operator_async()
    req_data = KnowledgeFileProcess(
        knowledge_id=command.knowledge_id,
        split_mode=command.split_mode,
        separator=command.separator,
        separator_rule=command.separator_rule,
        chunk_size=command.chunk_size,
        chunk_overlap=command.chunk_overlap,
        hierarchy_level=command.hierarchy_level,
        append_title=command.append_title,
        max_chunk_size=command.max_chunk_size,
        file_list=[KnowledgeFileOne(file_path=path)],
    )
    limit = await QuotaService.get_knowledge_space_upload_limit_bytes(login_user)
    results = await run_in_threadpool(
        KnowledgeService.sync_process_knowledge_file,
        request,
        login_user,
        req_data,
        upload_limit_bytes=limit,
    )
    return results[0]


async def import_text_chunks(*, command) -> Any:
    """Import caller-provided text segments as one file; the first segment's ``source`` names the file."""
    first = command.documents[0]
    file_name = safe_file_name(first.metadata.source)
    content = "\n\n".join(item.page_content for item in command.documents)
    file_path = await sync_func_to_async(save_download_file)(content.encode("utf-8"), "bisheng", file_name)

    login_user = await get_open_api_operator_async()
    req_data = KnowledgeFileProcess(
        knowledge_id=command.knowledge_id,
        separator=["\n\n"],
        separator_rule=["after"],
        file_list=[KnowledgeFileOne(file_path=file_path)],
        extra=json.dumps(first.metadata.model_dump(), ensure_ascii=False),
    )
    limit = await QuotaService.get_knowledge_space_upload_limit_bytes(login_user)
    knowledge, failed_files, process_files, _ = await KnowledgeService.asave_knowledge_file(
        login_user, req_data, upload_limit_bytes=limit
    )
    if failed_files:
        return failed_files[0]
    documents = [Document(page_content=item.page_content, metadata=item.metadata.model_dump()) for item in command.documents]
    return await run_in_threadpool(text_knowledge, knowledge, process_files[0], documents)


__all__ = ["import_text_chunks", "upload_chunks"]
