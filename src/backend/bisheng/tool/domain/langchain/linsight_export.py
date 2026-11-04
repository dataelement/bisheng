"""Linsight task-mode export tools (design #1-followup, output-format delivery).

Agent-callable tools that convert a workspace markdown deliverable into a Word
(.docx) or PDF file.

- **docx**: ``MarkDocx`` (python-docx, pure Python — no external binary).
- **pdf**: ``markdown -> docx (MarkDocx) -> pdf (LibreOffice headless)``. The
  legacy ``md_to_pdf_bytes`` path rendered HTML with Playwright/Chromium, which
  is absent on stripped customer images (and cannot be installed there without
  shell access). LibreOffice's ``soffice --convert-to pdf`` is already shipped in
  the bisheng-backend image (knowledge-base Office parsing depends on it) and
  needs no browser — reusing ``convert_docx_to_pdf`` from the RAG loader utils.

Both converters are synchronous/blocking (python-docx + a ``soffice``
subprocess), so they run via ``util.sync_func_to_async`` (a thread-pool
executor) to avoid blocking the worker's asyncio loop thread.

Workspace images referenced by the markdown (``![](charts/a.png)``, relative to
the md file, or ``/output/...``) are read from the workspace and inlined as
``data:image/*`` URIs before conversion: the converters run in the worker, not in
the sandbox, and ``sanitize_html_for_pdf`` drops scheme-less ``src`` values (it
blocks ``file://``-style local reads), so a plain path can never resolve.

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
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.citation.domain.services.citation_export_service import bake_citations_for_export
from bisheng.linsight.domain.services.md_image_refs import inline_local_images
from bisheng.utils import util


class _ExportInput(BaseModel):
    source_path: str = Field(..., description="工作区内的源 markdown 路径, 例如 output/report.md 或 scratch/draft.md")
    dest_path: str = Field(default="", description="目标文件路径; 留空则自动用源文件名替换扩展名")


def _swap_ext(path: str, new_ext: str) -> str:
    base, _ = os.path.splitext(path)
    return base + new_ext


def _md_to_docx_bytes(md: str) -> bytes:
    """markdown -> docx bytes (pure Python via MarkDocx).

    ``MarkDocx.__call__`` returns ``(BytesIO.getbuffer(), title)`` — a memoryview,
    NOT bytes — so we copy it to bytes explicitly here. (The workspace backend
    also coerces memoryview now, but keeping the conversion at the source makes
    the contract obvious and engine-independent.) Late import keeps test
    monkeypatching of ``MarkDocx`` working.
    """
    from bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx import MarkDocx

    return bytes(MarkDocx()(md)[0])


def _md_to_pdf_bytes_via_libreoffice(md: str) -> bytes:
    """markdown -> docx -> pdf via LibreOffice headless (no browser).

    Reuses ``convert_docx_to_pdf`` (``soffice --headless --convert-to pdf``),
    already shipped in the image. Raises on failure (soffice missing / errored);
    the caller turns the raise into a soft string return.
    """
    from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import convert_docx_to_pdf

    docx_bytes = _md_to_docx_bytes(md)
    with tempfile.TemporaryDirectory(prefix="linsight_pdf_") as tmpdir:
        docx_path = os.path.join(tmpdir, "doc.docx")
        Path(docx_path).write_bytes(docx_bytes)
        pdf_path = convert_docx_to_pdf(docx_path, output_dir=tmpdir)
        if not pdf_path or not os.path.exists(pdf_path):
            raise RuntimeError("LibreOffice docx->pdf 转换失败 (soffice 缺失或出错)")
        return Path(pdf_path).read_bytes()


class _ExportToolBase(BaseTool):
    """Shared base: closure-injected backend + md read / binary write helpers."""

    # Closure-injected WorkspaceBackend. Typed as Any so pydantic accepts the
    # instance without arbitrary_types_allowed; deliberately NOT in args_schema,
    # so the LLM never sees or fills it.
    backend: Any = None
    # F069 P2: the exporter identity (task owner) used to permission-filter the
    # sources baked into the deliverable's references section. None -> anonymous
    # (only public web sources survive). Not in args_schema either.
    export_user: Any = None
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

    async def _inline_workspace_images(self, md: str, source_path: str) -> tuple[str, list[str]]:
        """Inline workspace images as data URIs; return (md, srcs that could not be inlined).

        A missing image is reported back rather than silently dropped, so the
        agent sees its broken reference.
        """
        if not hasattr(self.backend, "adownload_files"):
            return md, []

        async def _fetch(paths: list[str]) -> dict[str, bytes]:
            responses = await self.backend.adownload_files(paths)
            return {
                path: bytes(res.content)
                for path, res in zip(paths, responses, strict=False)
                if not getattr(res, "error", None) and getattr(res, "content", None)
            }

        return await inline_local_images(md, source_path, _fetch)

    @staticmethod
    def _missing_images_note(missing: list[str]) -> str:
        if not missing:
            return ""
        return (
            f"\n注意: {len(missing)} 张图片未找到, 未嵌入: {', '.join(missing)}"
            "(图片路径相对 md 所在目录, 或写成 /output/... 这样的工作区路径)"
        )

    async def _write_bytes(self, dest_path: str, data: bytes) -> str:
        res = await self.backend.awrite(dest_path, data)
        return getattr(res, "path", None) or ("/" + dest_path)


class ExportDocxTool(_ExportToolBase):
    name: str = "export_docx"
    description: str = (
        "把工作区内的 markdown 文件转换为 Word(.docx)交付物。\n"
        "用法: 先用 write_file 写好 output/<name>.md, 再调用本工具(source_path 指向该 md)。\n"
        "只有 output/ 下的文件会作为交付物交给用户; 试验性的转换请把源文件和 dest_path 都放在 scratch/。\n"
        "markdown 里引用的工作区图片(相对 md 所在目录, 或 /output/... 写法)会自动嵌入文档。\n"
        "仅当用户在澄清阶段选择了 docx 输出格式时才调用。"
    )

    async def _arun(self, source_path: str, dest_path: str = "", **kwargs) -> str:
        if not hasattr(self.backend, "awrite"):
            return "导出不可用: 当前工作区不支持文件写入。"
        md = await self._read_md(source_path)
        if md is None:
            return f"导出失败: 源文件 {source_path} 不存在或不可读, 请先用 write_file 写好 markdown。"
        try:
            # F069 P2: hidden citation spans become visible [n] plus a references
            # section, filtered by the exporter's permissions; anything that cannot
            # be resolved is stripped as before (no marker / id / [S99] leaks).
            md = await bake_citations_for_export(md, self.export_user)
            md, missing = await self._inline_workspace_images(md, source_path)
            docx_bytes = await util.sync_func_to_async(_md_to_docx_bytes)(md)
        except Exception as e:
            logger.exception("export_docx convert failed")
            return f"导出失败: markdown 转 docx 出错: {e}"
        path = await self._write_bytes(dest_path or _swap_ext(source_path, ".docx"), docx_bytes)
        return f"已生成 Word 文档: {path}" + self._missing_images_note(missing)


class ExportPdfTool(_ExportToolBase):
    name: str = "export_pdf"
    description: str = (
        "把工作区内的 markdown 文件转换为 PDF 交付物。\n"
        "用法: 先用 write_file 写好 output/<name>.md, 再调用本工具(source_path 指向该 md)。\n"
        "只有 output/ 下的文件会作为交付物交给用户; 试验性的转换请把源文件和 dest_path 都放在 scratch/。\n"
        "markdown 里引用的工作区图片(相对 md 所在目录, 或 /output/... 写法)会自动嵌入文档。\n"
        "仅当用户在澄清阶段选择了 pdf 输出格式时才调用。"
    )

    async def _arun(self, source_path: str, dest_path: str = "", **kwargs) -> str:
        if not hasattr(self.backend, "awrite"):
            return "导出不可用: 当前工作区不支持文件写入。"
        md = await self._read_md(source_path)
        if md is None:
            return f"导出失败: 源文件 {source_path} 不存在或不可读, 请先用 write_file 写好 markdown。"
        try:
            # Same as export_docx: bake resolvable citations, strip the rest.
            md = await bake_citations_for_export(md, self.export_user)
            md, missing = await self._inline_workspace_images(md, source_path)
            pdf_bytes = await util.sync_func_to_async(_md_to_pdf_bytes_via_libreoffice)(md)
        except Exception as e:
            logger.exception("export_pdf convert failed")
            return f"导出失败: markdown 转 pdf 出错(可能是 PDF 渲染环境缺失): {e}"
        path = await self._write_bytes(dest_path or _swap_ext(source_path, ".pdf"), pdf_bytes)
        return f"已生成 PDF 文档: {path}" + self._missing_images_note(missing)


def init_linsight_export_tools(backend, export_user: Any = None) -> list[BaseTool]:
    """Closure-inject the session WorkspaceBackend (and the exporter identity)
    into the deliverable tools: export_docx, export_pdf and check_html.

    Returns ``[]`` when no writable backend is supplied (e.g. the test-only
    FakeWorkspaceBackend has no ``awrite``), so the tools never surface to the
    model when they cannot actually produce a file.
    """
    if backend is None or not hasattr(backend, "awrite"):
        return []
    # Late import: the HTML checker is a sibling deliverable tool, bound under the
    # same "writable backend" condition so the prompt can advertise all of them.
    from bisheng.tool.domain.langchain.linsight_html_check import CheckHtmlTool

    return [
        ExportDocxTool(backend=backend, export_user=export_user),
        ExportPdfTool(backend=backend, export_user=export_user),
        CheckHtmlTool(backend=backend),
    ]
