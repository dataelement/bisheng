"""The workbench download endpoints hand the user citation-free bytes.

``download-md-to-pdf-or-docx`` converts a stored report; ``batch-download-files``
zips the stored files. Both must lose the citation spans (wrapper chars and ids)
while the stored ``.md`` in MinIO keeps them for the in-app preview.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.responses import StreamingResponse

from bisheng.linsight.api.endpoints import linsight as endpoint
from bisheng.linsight.domain.schemas.linsight_schema import DownloadFilesSchema


@pytest.fixture(autouse=True)
def _no_persisted_sources(monkeypatch):
    """F069 P2: exports resolve sources through the DB; these tests have none
    persisted, so baking degrades to the plain strip the assertions expect."""
    from bisheng.citation.domain.services import citation_export_service

    monkeypatch.setattr(citation_export_service, "resolve_items_for_export", AsyncMock(return_value=[]))

_CITED_MD = (
    "# 报告\n\n"
    "PM2.5 年均浓度下降。\ue200knowledgesearch_18f5868b:0\ue202\n\n"
    "- 要点\ue200knowledgesearch_18f5868b:1\ue201websearch_3a1c9f22:0\ue202\n"
)


def _assert_clean(md: str) -> None:
    assert "\ue200" not in md and "\ue201" not in md and "\ue202" not in md
    assert "knowledgesearch_" not in md and "websearch_" not in md
    assert "PM2.5 年均浓度下降。" in md


@pytest.fixture
def stored_report(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        endpoint.LinsightWorkbenchImpl,
        "download_file",
        AsyncMock(return_value=("report.md", _CITED_MD.encode("utf-8"))),
    )
    return DownloadFilesSchema(file_name="report.md", file_url="/bucket/linsight/report.md")


async def test_convert_to_docx_strips_markers(stored_report, monkeypatch: pytest.MonkeyPatch):
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod

    seen = {}

    class _FakeMarkDocx:
        def __call__(self, md):
            seen["md"] = md
            return (b"DOCXBYTES", "title")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _FakeMarkDocx)

    resp = await endpoint.download_md_to_pdf_or_docx(
        file_info=stored_report, to_type="docx", login_user=SimpleNamespace(user_id=1)
    )

    assert isinstance(resp, StreamingResponse)
    _assert_clean(seen["md"])


async def test_convert_to_pdf_strips_markers(stored_report, monkeypatch: pytest.MonkeyPatch):
    import bisheng.common.utils.markdown_cmpnt.md_to_pdf as md_to_pdf_mod

    seen = {}

    def _fake_pdf(md, *args, **kwargs):
        seen["md"] = md
        return b"PDFBYTES"

    monkeypatch.setattr(md_to_pdf_mod, "md_to_pdf_bytes", _fake_pdf)

    resp = await endpoint.download_md_to_pdf_or_docx(
        file_info=stored_report, to_type="pdf", login_user=SimpleNamespace(user_id=1)
    )

    assert isinstance(resp, StreamingResponse)
    _assert_clean(seen["md"])


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_zip_rewrite_strips_markdown_entries_only():
    # Not UTF-8 (0x89 lead byte) even though it carries a PUA marker: must be copied byte-for-byte.
    raw_png = b"\x89PNG\r\n\x1a\n" + "\ue200knowledgesearch_18f5868b:0\ue202".encode()
    original = _zip({"report.md": _CITED_MD.encode("utf-8"), "chart.png": raw_png})

    out = endpoint._strip_citation_markers_in_zip(original)

    with zipfile.ZipFile(BytesIO(out)) as zf:
        assert sorted(zf.namelist()) == ["chart.png", "report.md"]
        _assert_clean(zf.read("report.md").decode("utf-8"))
        assert zf.read("chart.png") == raw_png


def test_zip_rewrite_returns_bundle_untouched_without_markdown():
    original = _zip({"data.csv": b"a,b\n1,2\n"})
    assert endpoint._strip_citation_markers_in_zip(original) is original


async def test_batch_download_serves_stripped_markdown(monkeypatch: pytest.MonkeyPatch):
    original = _zip({"report.md": _CITED_MD.encode("utf-8")})
    monkeypatch.setattr(endpoint.LinsightWorkbenchImpl, "batch_download_files", AsyncMock(return_value=original))

    resp = await endpoint.batch_download_files(
        zip_name="bundle",
        file_info_list=[DownloadFilesSchema(file_name="report.md", file_url="/bucket/linsight/report.md")],
        login_user=SimpleNamespace(user_id=1),
    )

    assert isinstance(resp, StreamingResponse)
    body = b"".join([chunk async for chunk in resp.body_iterator])
    with zipfile.ZipFile(BytesIO(body)) as zf:
        _assert_clean(zf.read("report.md").decode("utf-8"))


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


@pytest.fixture
def stored_handle_report(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        endpoint.LinsightWorkbenchImpl,
        "download_file",
        AsyncMock(return_value=("report.md", _HANDLE_MD.encode("utf-8"))),
    )
    return DownloadFilesSchema(file_name="report.md", file_url="/bucket/linsight/report.md")


async def test_convert_to_docx_strips_unknown_handles(stored_handle_report, monkeypatch: pytest.MonkeyPatch):
    import bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx as markdocx_mod

    seen = {}

    class _FakeMarkDocx:
        def __call__(self, md):
            seen["md"] = md
            return (b"DOCXBYTES", "title")

    monkeypatch.setattr(markdocx_mod, "MarkDocx", _FakeMarkDocx)

    resp = await endpoint.download_md_to_pdf_or_docx(
        file_info=stored_handle_report, to_type="docx", login_user=SimpleNamespace(user_id=1)
    )

    assert isinstance(resp, StreamingResponse)
    _assert_clean_handles(seen["md"])


async def test_convert_to_pdf_strips_unknown_handles(stored_handle_report, monkeypatch: pytest.MonkeyPatch):
    import bisheng.common.utils.markdown_cmpnt.md_to_pdf as md_to_pdf_mod

    seen = {}

    def _fake_pdf(md, *args, **kwargs):
        seen["md"] = md
        return b"PDFBYTES"

    monkeypatch.setattr(md_to_pdf_mod, "md_to_pdf_bytes", _fake_pdf)

    resp = await endpoint.download_md_to_pdf_or_docx(
        file_info=stored_handle_report, to_type="pdf", login_user=SimpleNamespace(user_id=1)
    )

    assert isinstance(resp, StreamingResponse)
    _assert_clean_handles(seen["md"])


def test_zip_rewrite_strips_unknown_handles_in_markdown():
    original = _zip({"report.md": _HANDLE_MD.encode("utf-8"), "data.csv": b"[S99],x\n"})

    out = endpoint._strip_citation_markers_in_zip(original)

    with zipfile.ZipFile(BytesIO(out)) as zf:
        _assert_clean_handles(zf.read("report.md").decode("utf-8"))
        assert zf.read("data.csv") == b"[S99],x\n"  # only .md entries are rewritten


# ---------------------------------------------------------------------------
# F069 P2: the endpoints bake resolvable citations for the logged-in exporter
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


async def test_convert_to_docx_bakes_for_the_exporter(stored_report, monkeypatch: pytest.MonkeyPatch):
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
    user = SimpleNamespace(user_id=1)

    resp = await endpoint.download_md_to_pdf_or_docx(file_info=stored_report, to_type="docx", login_user=user)

    assert isinstance(resp, StreamingResponse)
    assert seen["user"] is user
    assert "PM2.5 年均浓度下降。[1]" in seen["md"] and "## 参考资料" in seen["md"]
    assert "" not in seen["md"] and "websearch_" not in seen["md"]


async def test_batch_download_bakes_md_entries(monkeypatch: pytest.MonkeyPatch):
    from bisheng.citation.domain.services import citation_export_service

    monkeypatch.setattr(citation_export_service, "resolve_items_for_export", AsyncMock(return_value=[_resolved_rag()]))
    original = _zip({"report.md": _CITED_MD.encode("utf-8"), "data.csv": b"a,b\n"})
    monkeypatch.setattr(endpoint.LinsightWorkbenchImpl, "batch_download_files", AsyncMock(return_value=original))

    resp = await endpoint.batch_download_files(
        zip_name="bundle", file_info_list=[], login_user=SimpleNamespace(user_id=1)
    )
    body = b"".join([chunk async for chunk in resp.body_iterator]) if hasattr(resp.body_iterator, "__aiter__") else b"".join(resp.body_iterator)
    with zipfile.ZipFile(BytesIO(body)) as z:
        md = z.read("report.md").decode("utf-8")
        assert z.read("data.csv") == b"a,b\n"
    assert "PM2.5 年均浓度下降。[1]" in md and "## 参考资料" in md
    assert "" not in md and "websearch_" not in md


async def test_batch_download_without_markdown_returns_bundle_untouched(monkeypatch: pytest.MonkeyPatch):
    original = _zip({"data.csv": b"a,b\n"})
    assert await endpoint._bake_citations_in_zip(original, SimpleNamespace(user_id=1)) is original
