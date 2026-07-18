"""Unit tests for the Linsight export tools (export_docx / export_pdf).

The real converters (MarkDocx / md_to_pdf_bytes) are monkeypatched so these
tests don't need pandoc/Playwright; we verify the tool wiring: closure-injected
backend, read md -> convert -> write bytes, dest-path derivation, and the
soft-return contract on failure (a raised exception would kill the whole task).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.tool.domain.langchain import linsight_export


def _writable_backend(md_content="# Hello\n\ncontent", read_error=None):
    backend = MagicMock()
    backend.aread = AsyncMock(
        return_value=SimpleNamespace(
            error=read_error,
            file_data=None if read_error else {"content": md_content},
        )
    )
    backend.awrite = AsyncMock(return_value=SimpleNamespace(path="/output/report.docx"))
    return backend


def test_init_returns_empty_for_non_writable_backend():
    """A backend with no awrite (e.g. test FakeWorkspaceBackend) yields no tools."""
    assert linsight_export.init_linsight_export_tools(None) == []
    assert linsight_export.init_linsight_export_tools(object()) == []  # no awrite attr


def test_init_returns_both_tools_for_writable_backend():
    tools = linsight_export.init_linsight_export_tools(_writable_backend())
    names = {t.name for t in tools}
    assert names == {"export_docx", "export_pdf"}


async def test_export_docx_reads_converts_writes(monkeypatch):
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod

    class _FakeMarkDocx:
        def __call__(self, md):
            assert md == "# Hello\n\ncontent"  # the md we wrote was read back
            return (b"DOCXBYTES", "title")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _FakeMarkDocx)

    backend = _writable_backend()
    tool = linsight_export.ExportDocxTool(backend=backend)
    res = await tool._arun(source_path="output/report.md")

    backend.aread.assert_awaited_once()
    # dest defaults to source with .docx extension; binary written through
    args, _ = backend.awrite.await_args
    assert args[0] == "output/report.docx"
    assert args[1] == b"DOCXBYTES"
    assert "已生成 Word" in res


async def test_export_docx_handles_memoryview(monkeypatch):
    """MarkDocx returns a memoryview (BytesIO.getbuffer()); the tool must write
    real bytes, never the stringified ``<memory at 0x...>`` (the Word-won't-open
    bug). Regression guard for the memoryview path."""
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod

    class _FakeMarkDocx:
        def __call__(self, md):
            return (memoryview(b"DOCXBYTES"), "title")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _FakeMarkDocx)

    backend = _writable_backend()
    tool = linsight_export.ExportDocxTool(backend=backend)
    res = await tool._arun(source_path="output/report.md")

    args, _ = backend.awrite.await_args
    assert args[1] == b"DOCXBYTES"  # memoryview copied to bytes, not stringified
    assert "已生成 Word" in res


async def test_export_pdf_reads_converts_writes(monkeypatch):
    # PDF now goes markdown -> docx -> pdf (LibreOffice); patch the helper.
    monkeypatch.setattr(linsight_export, "_md_to_pdf_bytes_via_libreoffice", lambda md: b"PDFBYTES")

    backend = _writable_backend()
    tool = linsight_export.ExportPdfTool(backend=backend)
    res = await tool._arun(source_path="output/report.md", dest_path="output/custom.pdf")

    args, _ = backend.awrite.await_args
    assert args[0] == "output/custom.pdf"  # explicit dest honoured
    assert args[1] == b"PDFBYTES"
    assert "已生成 PDF" in res


async def test_export_pdf_engine_error_soft_returns(monkeypatch):
    """LibreOffice missing/errored must soft-return, never raise (would kill task)."""

    def _boom(md):
        raise RuntimeError("LibreOffice docx->pdf 转换失败 (soffice 缺失或出错)")

    monkeypatch.setattr(linsight_export, "_md_to_pdf_bytes_via_libreoffice", _boom)

    backend = _writable_backend()
    tool = linsight_export.ExportPdfTool(backend=backend)
    res = await tool._arun(source_path="output/report.md")
    backend.awrite.assert_not_awaited()
    assert "导出失败" in res


async def test_export_docx_missing_source_soft_returns():
    """Missing/unreadable source must soft-return (never raise → never kill task)."""
    backend = _writable_backend(read_error="File 'output/x.md' not found")
    tool = linsight_export.ExportDocxTool(backend=backend)
    res = await tool._arun(source_path="output/x.md")
    backend.awrite.assert_not_awaited()
    assert "导出失败" in res and "不存在" in res


async def test_export_docx_non_writable_backend_soft_returns():
    """A backend without awrite must soft-return, not blow up."""
    tool = linsight_export.ExportDocxTool(backend=object())
    res = await tool._arun(source_path="output/report.md")
    assert "导出不可用" in res


async def test_export_docx_converter_error_soft_returns(monkeypatch):
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod

    class _BoomMarkDocx:
        def __call__(self, md):
            raise RuntimeError("pandoc missing")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _BoomMarkDocx)

    backend = _writable_backend()
    tool = linsight_export.ExportDocxTool(backend=backend)
    res = await tool._arun(source_path="output/report.md")
    backend.awrite.assert_not_awaited()
    assert "导出失败" in res


def test_run_sync_unsupported():
    tool = linsight_export.ExportPdfTool(backend=_writable_backend())
    assert "not supported in sync mode" in tool._run()
