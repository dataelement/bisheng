"""Linsight task-mode export tools (design #1-followup, output-format delivery).

Agent-callable tools that convert a workspace markdown deliverable into a Word
(.docx) or PDF file, reusing the SAME converters as the frontend download API
(``common/utils/markdown_cmpnt``): ``md_to_pdf_bytes`` (Playwright) and
``MarkDocx``. Both are synchronous/blocking, so they are wrapped with
``util.sync_func_to_async`` (run in a thread-pool executor) — identical to the
download endpoint — otherwise ``sync_playwright`` inside the worker's asyncio
loop thread raises.

The session ``WorkspaceBackend`` is **closure-injected** via the factory below:
deepagents tools cannot reach the FilesystemMiddleware backend through
``ToolRuntime``, so the only reliable path is to bind the backend onto the tool
instance — mirroring ``SearchKnowledgeBase(allowed_knowledge_ids=...)``.

A tool failure MUST be a soft string return (never raise): a raised exception
propagates through the deepagents tool node and kills the whole task (same
contract as ``linsight_knowledge.SearchKnowledgeBase``).
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.utils import util


class _ExportInput(BaseModel):
    source_path: str = Field(..., description="工作区 output/ 下的源 markdown 路径, 例如 output/report.md")
    dest_path: str = Field(default="", description="目标文件路径; 留空则自动用源文件名替换扩展名")


def _swap_ext(path: str, new_ext: str) -> str:
    base, _ = os.path.splitext(path)
    return base + new_ext


class _ExportToolBase(BaseTool):
    """Shared base: closure-injected backend + md read / binary write helpers."""

    # Closure-injected WorkspaceBackend. Typed as Any so pydantic accepts the
    # instance without arbitrary_types_allowed; deliberately NOT in args_schema,
    # so the LLM never sees or fills it.
    backend: Any = None
    args_schema: type[BaseModel] = _ExportInput

    def _run(self, *args, **kwargs) -> str:
        return "not supported in sync mode, please use async version"

    async def _read_md(self, source_path: str) -> str | None:
        """Read a workspace markdown file as text; None if missing/unreadable."""
        if not hasattr(self.backend, "aread"):
            return None
        # limit=None reads the whole file (aread defaults to the first 2000 lines).
        res = await self.backend.aread(source_path, limit=None)
        if getattr(res, "error", None):
            return None
        fd = getattr(res, "file_data", None)
        if fd is None:
            return None
        # FileData is a TypedDict (dict at runtime); tolerate an attr-style impl too.
        return fd["content"] if isinstance(fd, dict) else getattr(fd, "content", None)

    async def _write_bytes(self, dest_path: str, data: bytes) -> str:
        res = await self.backend.awrite(dest_path, data)
        return getattr(res, "path", None) or ("/" + dest_path)


class ExportDocxTool(_ExportToolBase):
    name: str = "export_docx"
    description: str = (
        "把工作区 output/ 下的 markdown 文件转换为 Word(.docx)交付物。\n"
        "用法: 先用 write_file 写好 output/<name>.md, 再调用本工具(source_path 指向该 md)。\n"
        "仅当用户在澄清阶段选择了 docx 输出格式时才调用。"
    )

    async def _arun(self, source_path: str, dest_path: str = "", **kwargs) -> str:
        if not hasattr(self.backend, "awrite"):
            return "导出不可用: 当前工作区不支持文件写入。"
        md = await self._read_md(source_path)
        if md is None:
            return f"导出失败: 源文件 {source_path} 不存在或不可读, 请先用 write_file 写好 markdown。"
        try:
            from bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx import MarkDocx

            docx_bytes, _ = await util.sync_func_to_async(MarkDocx())(md)
        except Exception as e:
            logger.exception("export_docx convert failed")
            return f"导出失败: markdown 转 docx 出错: {e}"
        path = await self._write_bytes(dest_path or _swap_ext(source_path, ".docx"), docx_bytes)
        return f"已生成 Word 文档: {path}"


class ExportPdfTool(_ExportToolBase):
    name: str = "export_pdf"
    description: str = (
        "把工作区 output/ 下的 markdown 文件转换为 PDF 交付物。\n"
        "用法: 先用 write_file 写好 output/<name>.md, 再调用本工具(source_path 指向该 md)。\n"
        "仅当用户在澄清阶段选择了 pdf 输出格式时才调用。"
    )

    async def _arun(self, source_path: str, dest_path: str = "", **kwargs) -> str:
        if not hasattr(self.backend, "awrite"):
            return "导出不可用: 当前工作区不支持文件写入。"
        md = await self._read_md(source_path)
        if md is None:
            return f"导出失败: 源文件 {source_path} 不存在或不可读, 请先用 write_file 写好 markdown。"
        try:
            from bisheng.common.utils.markdown_cmpnt.md_to_pdf import md_to_pdf_bytes

            pdf_bytes = await util.sync_func_to_async(md_to_pdf_bytes)(md)
        except Exception as e:
            logger.exception("export_pdf convert failed")
            return f"导出失败: markdown 转 pdf 出错(可能是 PDF 渲染环境缺失): {e}"
        path = await self._write_bytes(dest_path or _swap_ext(source_path, ".pdf"), pdf_bytes)
        return f"已生成 PDF 文档: {path}"


def init_linsight_export_tools(backend) -> list[BaseTool]:
    """Closure-inject the session WorkspaceBackend into the export tools.

    Returns ``[]`` when no writable backend is supplied (e.g. the test-only
    FakeWorkspaceBackend has no ``awrite``), so the tools never surface to the
    model when they cannot actually produce a file.
    """
    if backend is None or not hasattr(backend, "awrite"):
        return []
    return [ExportDocxTool(backend=backend), ExportPdfTool(backend=backend)]
