"""Offline protocol-to-document coverage for the MinerU V4 integration.

The target MinerU service and BiSheng middleware are not available in this
checkout. Live API and UI acceptance steps are recorded in e2e-checklist.md.
"""

import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import httpx
import pytest
from PIL import Image

from bisheng.core.config.settings import KnowledgeConf
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.loader.mineru_v4 import MineruV4Loader


class OfflinePipeline(BaseFilePipeline):
    @property
    def file_metadata(self) -> dict:
        return {"source": "offline-e2e"}


def _archive() -> bytes:
    middle = {
        "schema": "docvortex.middle",
        "schema_version": "2.0",
        "pages": [
            {
                "page_idx": 0,
                "blocks": [
                    {
                        "type": "text",
                        "bbox": [0.1, 0.1, 0.9, 0.3],
                        "content": [{"type": "text", "content": "Visible text"}],
                    },
                    {
                        "type": "image",
                        "bbox": [0.2, 0.4, 0.8, 0.8],
                        "content": [{"type": "image_body", "image_path": "images/figure.png", "content": ""}],
                    },
                ],
            }
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("middle_json.json", json.dumps(middle))
        archive.writestr("images/figure.png", b"figure-bytes")
    return output.getvalue()


@pytest.mark.parametrize("extension,expected_bbox", [("pdf", [20, 10, 180, 30]), ("png", [10, 5, 90, 15])])
def test_ac01_ac04_v1_protocol_through_pipeline_to_document(tmp_path, extension, expected_bbox):
    """AC-01, AC-04, AC-05: selection, upload, parse, ZIP and document metadata."""
    source = tmp_path / f"source.{extension}"
    if extension == "pdf":
        pdf = fitz.open()
        pdf.new_page(width=200, height=100)
        pdf.save(source)
        pdf.close()
    else:
        Image.new("RGB", (100, 50), "white").save(source)

    pipeline = OfflinePipeline(
        invoke_user_id=1,
        file_name=source.name,
        file_rule=SimpleNamespace(filter_page_header_footer=0, force_ocr=0, retain_images=1),
    )
    pipeline.local_file_path = str(source)
    pipeline.tmp_dir = str(tmp_path)
    pipeline.db_file = SimpleNamespace(parse_type=None)
    config = KnowledgeConf(loader_provider="mineru_v4", mineru_v4={"api_url": "https://mineru.example"})
    with patch("bisheng.knowledge.rag.base_file_pipeline.settings", SimpleNamespace(get_knowledge=lambda: config)):
        loader = pipeline._init_pdf_loader() if extension == "pdf" else pipeline._init_image_loader()
    assert isinstance(loader, MineruV4Loader)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/uploads":
            return httpx.Response(200, json={"status": "completed", "file": {"id": "source-id"}})
        if request.url.path == "/v1/parse/jobs" and request.method == "POST":
            payload = json.loads(request.content)
            assert payload["files"][0]["source"]["file_id"] == "source-id"
            assert payload["output_formats"] == ["zip"]
            return httpx.Response(202, json={"job_id": "job-id"})
        if request.url.path == "/v1/parse/jobs/job-id":
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "files": [{"status": "completed", "output_files": {"zip": {"file_id": "zip-id"}}}],
                },
            )
        if request.url.path == "/v1/files/zip-id/content":
            return httpx.Response(200, content=_archive())
        raise AssertionError(request.url)

    loader.client.transport = httpx.MockTransport(handler)
    document = loader.load()[0]
    assert "Visible text" in document.page_content
    assert "figure.png" in document.page_content
    assert document.metadata["pages"] == [0, 0]
    assert document.metadata["bboxes"][0] == expected_bbox
    assert all(document.page_content[start:end].strip() for start, end in document.metadata["indexes"])
    assert (tmp_path / "images" / "figure.png").read_bytes() == b"figure-bytes"
