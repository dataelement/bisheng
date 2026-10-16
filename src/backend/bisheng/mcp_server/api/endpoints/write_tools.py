from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from bisheng.mcp_server.domain.schemas.browse import ResourceId
from bisheng.mcp_server.domain.schemas.ingestion import (
    ClassificationCode,
    CreateDocumentRequest,
    DocumentText,
    FileBase64,
    FileName,
    ManualTagIds,
    ManualTagNames,
    UploadFileRequest,
    WriteResponse,
)
from bisheng.mcp_server.domain.services.tool_runtime import McpToolRuntime


def register_write_tools(server: FastMCP, runtime: McpToolRuntime) -> None:
    annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False, idempotentHint=False)

    @server.tool(
        description="把 UTF-8 文本或 Markdown 保存为新文件,写入指定空间和目录;不覆盖,受理后异步解析。文本最多 10 MiB。",
        annotations=annotations,
    )
    async def create_document(
        knowledge_id: ResourceId,
        file_name: FileName,
        content: DocumentText,
        ctx: Context,
        content_format: Literal["text", "markdown"] = "markdown",
        folder_id: ResourceId | None = None,
        file_category_code: ClassificationCode | None = None,
        file_subcategory_code: ClassificationCode | None = None,
        business_domain_code: ClassificationCode | None = None,
        manual_tag_ids: ManualTagIds | None = None,
        manual_tag_names: ManualTagNames | None = None,
    ) -> WriteResponse:
        params = CreateDocumentRequest(
            knowledge_id=knowledge_id,
            file_name=file_name,
            content=content,
            content_format=content_format,
            folder_id=folder_id,
            file_category_code=file_category_code,
            file_subcategory_code=file_subcategory_code,
            business_domain_code=business_domain_code,
            manual_tag_ids=manual_tag_ids or [],
            manual_tag_names=manual_tag_names or [],
        )
        return WriteResponse.model_validate(await runtime.invoke(ctx, "create_document", params))

    @server.tool(
        description="上传 Base64 编码的现有文件到指定空间和目录;解码后最多 50 MiB,不覆盖,受理后异步解析。",
        annotations=annotations,
    )
    async def upload_file(
        knowledge_id: ResourceId,
        file_name: FileName,
        content_base64: FileBase64,
        ctx: Context,
        folder_id: ResourceId | None = None,
        file_category_code: ClassificationCode | None = None,
        file_subcategory_code: ClassificationCode | None = None,
        business_domain_code: ClassificationCode | None = None,
        manual_tag_ids: ManualTagIds | None = None,
        manual_tag_names: ManualTagNames | None = None,
    ) -> WriteResponse:
        params = UploadFileRequest(
            knowledge_id=knowledge_id,
            file_name=file_name,
            content_base64=content_base64,
            folder_id=folder_id,
            file_category_code=file_category_code,
            file_subcategory_code=file_subcategory_code,
            business_domain_code=business_domain_code,
            manual_tag_ids=manual_tag_ids or [],
            manual_tag_names=manual_tag_names or [],
        )
        return WriteResponse.model_validate(await runtime.invoke(ctx, "upload_file", params))
