"""Unit tests for the Linsight export tools (export_docx / export_pdf).

The real converters (MarkDocx / md_to_pdf_bytes) are monkeypatched so these
tests don't need pandoc/Playwright; we verify the tool wiring: closure-injected
backend, read md -> convert -> write bytes, dest-path derivation, and the
soft-return contract on failure (a raised exception would kill the whole task).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.tool.domain.langchain import linsight_export


@pytest.fixture(autouse=True)
def _no_persisted_sources(monkeypatch):
    """F069 P2: exports resolve sources through the DB; these tests have none
    persisted, so baking degrades to the plain strip the assertions expect."""
    from bisheng.citation.domain.services import citation_export_service

    monkeypatch.setattr(citation_export_service, "resolve_items_for_export", AsyncMock(return_value=[]))


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


def test_init_returns_every_deliverable_tool_for_writable_backend():
    tools = linsight_export.init_linsight_export_tools(_writable_backend())
    names = {t.name for t in tools}
    assert names == {"export_docx", "export_pdf", "check_html"}


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


_CITED_MD = (
    "# 报告\n\n"
    "PM2.5 年均浓度下降。\ue200knowledgesearch_18f5868b:0\ue202\n\n"
    "- 要点\ue200knowledgesearch_18f5868b:1\ue201websearch_3a1c9f22:0\ue202\n"
    "- 字面转义形式\\ue200websearch_3a1c9f22:1\\ue202\n"
)


def _assert_clean(md: str) -> None:
    assert "\ue200" not in md and "\ue201" not in md and "\ue202" not in md
    assert "knowledgesearch_" not in md and "websearch_" not in md
    assert "PM2.5 年均浓度下降。" in md  # prose kept


async def test_export_docx_strips_citation_markers_before_convert(monkeypatch):
    """Word must never carry the PUA wrappers nor the bare source ids."""
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod

    seen = {}

    class _FakeMarkDocx:
        def __call__(self, md):
            seen["md"] = md
            return (b"DOCXBYTES", "title")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _FakeMarkDocx)

    backend = _writable_backend(md_content=_CITED_MD)
    tool = linsight_export.ExportDocxTool(backend=backend)
    res = await tool._arun(source_path="output/report.md")

    _assert_clean(seen["md"])
    assert "已生成 Word" in res


async def test_export_pdf_strips_citation_markers_before_convert(monkeypatch):
    seen = {}

    def _fake_pdf(md):
        seen["md"] = md
        return b"PDFBYTES"

    monkeypatch.setattr(linsight_export, "_md_to_pdf_bytes_via_libreoffice", _fake_pdf)

    backend = _writable_backend(md_content=_CITED_MD)
    tool = linsight_export.ExportPdfTool(backend=backend)
    res = await tool._arun(source_path="output/report.md")

    _assert_clean(seen["md"])
    assert "已生成 PDF" in res


# ---------------------------------------------------------------------------
# F069 T026: an unregistered short handle ([S99]) must not leak either
# ---------------------------------------------------------------------------
_HANDLE_MD = (
    "# 报告\n\n"
    "PM2.5 年均浓度下降。knowledgesearch_18f5868b:0[S99]\n\n"
    "- 要点 [S12, S99]\n"
    "- 代码里的 `[S99]` 不是引用\n"
)


def _assert_clean_handles(md: str) -> None:
    _assert_clean(md)
    assert "[S99]" not in md.replace("`[S99]`", "")
    assert "[S12" not in md
    assert "`[S99]`" in md  # code span kept verbatim


async def test_export_docx_strips_unknown_handles(monkeypatch):
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod

    seen = {}

    class _FakeMarkDocx:
        def __call__(self, md):
            seen["md"] = md
            return (b"DOCXBYTES", "title")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _FakeMarkDocx)

    tool = linsight_export.ExportDocxTool(backend=_writable_backend(md_content=_HANDLE_MD))
    res = await tool._arun(source_path="output/report.md")

    _assert_clean_handles(seen["md"])
    assert "已生成 Word" in res


async def test_export_pdf_strips_unknown_handles(monkeypatch):
    seen = {}

    def _fake_pdf(md):
        seen["md"] = md
        return b"PDFBYTES"

    monkeypatch.setattr(linsight_export, "_md_to_pdf_bytes_via_libreoffice", _fake_pdf)

    tool = linsight_export.ExportPdfTool(backend=_writable_backend(md_content=_HANDLE_MD))
    res = await tool._arun(source_path="output/report.md")

    _assert_clean_handles(seen["md"])
    assert "已生成 PDF" in res


# ---------------------------------------------------------------------------
# F069 P2: the tools bake resolvable citations under the exporter's identity
# ---------------------------------------------------------------------------
def _resolved_rag():
    from bisheng.citation.domain.schemas.citation_schema import (
        CitationRegistryItemSchema,
        CitationType,
        RagCitationItemSchema,
        RagCitationPayloadSchema,
    )

    return CitationRegistryItemSchema(
        citationId="knowledgesearch_18f5868b",
        type=CitationType.RAG,
        accessScope="per_user",
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=9, documentId=11, documentName="政策.pdf", items=[RagCitationItemSchema(itemId="0", page=3)]
        ),
    )


async def test_export_docx_bakes_numbers_for_the_task_owner(monkeypatch):
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod
    from bisheng.citation.domain.services import citation_export_service

    seen = {}

    async def fake_resolve(ids, login_user):
        seen["user"] = login_user
        return [_resolved_rag()]

    monkeypatch.setattr(citation_export_service, "resolve_items_for_export", fake_resolve)

    class _FakeMarkDocx:
        def __call__(self, md):
            seen["md"] = md
            return (b"DOCXBYTES", "title")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _FakeMarkDocx)
    owner = SimpleNamespace(user_id=3)
    tools = linsight_export.init_linsight_export_tools(_writable_backend(md_content=_CITED_MD), export_user=owner)
    docx_tool = next(t for t in tools if t.name == "export_docx")

    res = await docx_tool._arun(source_path="output/report.md")

    assert seen["user"] is owner
    assert "PM2.5 年均浓度下降。[1]" in seen["md"]
    assert "## 参考资料" in seen["md"] and "《政策.pdf》 · 第 3 页" in seen["md"]
    assert "" not in seen["md"] and "websearch_" not in seen["md"]  # the unresolved web key is stripped
    assert "已生成 Word" in res


# --- workspace images are inlined as data URIs (the converters run in the
# worker, and sanitize_html_for_pdf drops scheme-less src values) -------------


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


_PNG = _png_bytes()


def _download_backend(md_content: str, files: dict[str, bytes]):
    backend = _writable_backend(md_content)

    async def _download(paths):
        return [
            SimpleNamespace(path="/" + p, content=files[p], error=None)
            if p in files
            else SimpleNamespace(path="/" + p, content=None, error="file_not_found")
            for p in paths
        ]

    backend.adownload_files = AsyncMock(side_effect=_download)
    return backend


def _capture_docx_md(monkeypatch) -> list[str]:
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod

    seen: list[str] = []

    class _FakeMarkDocx:
        def __call__(self, md):
            seen.append(md)
            return (b"DOCXBYTES", "title")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _FakeMarkDocx)
    return seen


async def test_export_docx_inlines_relative_and_rooted_images(monkeypatch):
    seen = _capture_docx_md(monkeypatch)
    # Three spellings seen in practice: md-relative, workspace-rooted with a
    # slash, and workspace-rooted without one (session 48e1bcae wrote this last
    # form inside output/减肥计划.md).
    md = (
        "# R\n\n![曲线](charts/weight_curve.png)\n\n![宏量](/output/charts/macros.png)\n\n"
        "![宏量2](output/charts/macros.png)\n"
    )
    backend = _download_backend(md, {"output/charts/weight_curve.png": _PNG, "output/charts/macros.png": _PNG})
    res = await linsight_export.ExportDocxTool(backend=backend)._arun(source_path="output/report.md")

    (paths,), _ = backend.adownload_files.await_args
    assert paths == [
        "charts/weight_curve.png",
        "output/charts/macros.png",
        "output/charts/weight_curve.png",
        "output/output/charts/macros.png",
    ]
    assert seen[0].count("](data:image/png;base64,") == 3
    assert "charts/" not in seen[0]
    assert "未嵌入" not in res


async def test_export_pdf_inlines_html_img_and_percent_encoded_name(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(linsight_export, "_md_to_pdf_bytes_via_libreoffice", lambda md: seen.append(md) or b"PDFBYTES")
    md = '<img src="%E5%9B%BE.png" width="300">\n'
    backend = _download_backend(md, {"scratch/图.png": _PNG})
    res = await linsight_export.ExportPdfTool(backend=backend)._arun(source_path="scratch/draft.md")

    assert '<img src="data:image/png;base64,' in seen[0]
    assert "已生成 PDF" in res


async def test_export_reports_missing_images_instead_of_dropping_silently(monkeypatch):
    seen = _capture_docx_md(monkeypatch)
    md = "![a](charts/nope.png)\n![b](../../etc/passwd.png)\n![c](https://example.com/x.png)\n"
    backend = _download_backend(md, {})
    res = await linsight_export.ExportDocxTool(backend=backend)._arun(source_path="output/report.md")

    # The escaping path is never requested; the remote url is left for the converter.
    (paths,), _ = backend.adownload_files.await_args
    assert paths == ["charts/nope.png", "output/charts/nope.png"]
    assert "https://example.com/x.png" in seen[0]
    assert "已生成 Word" in res
    assert "2 张图片未找到" in res and "charts/nope.png" in res and "../../etc/passwd.png" in res


async def test_export_without_images_skips_download(monkeypatch):
    _capture_docx_md(monkeypatch)
    backend = _download_backend("# plain\n\ntext", {})
    await linsight_export.ExportDocxTool(backend=backend)._arun(source_path="output/report.md")
    backend.adownload_files.assert_not_awaited()


# --- real converter (no mocks): the 'src' KeyError regression ----------------


def _docx_parts(docx_bytes: bytes) -> tuple[str, list[str]]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        return zf.read("word/document.xml").decode("utf-8"), zf.namelist()


def test_markdocx_local_image_path_does_not_crash():
    """A scheme-less src is stripped by the sanitizer; the converter must skip the
    image instead of raising KeyError('src') (which failed every export with an image)."""
    xml, _ = _docx_parts(linsight_export._md_to_docx_bytes("# 标题\n\n正文\n\n![图](charts/a.png)\n"))
    assert "正文" in xml


def test_markdocx_embeds_data_uri_image():
    import base64

    uri = "data:image/png;base64," + base64.b64encode(_PNG).decode()
    xml, names = _docx_parts(linsight_export._md_to_docx_bytes(f"# 标题\n\n正文\n\n![图]({uri})\n"))
    assert "正文" in xml
    assert "<pic:pic" in xml
    assert any(n.startswith("word/media/") for n in names)
