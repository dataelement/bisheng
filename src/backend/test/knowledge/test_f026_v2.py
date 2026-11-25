"""External legacy writes must stop before local materialization or URL fetch."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile
from langchain_core.documents import Document

from bisheng.api.v1.schemas import ChunkInput
from bisheng.knowledge.application import provider_v1_runtime as provider
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.open_endpoints.api.endpoints import filelib


def test_snapshot_identity_covers_html_and_final_locator():
    from bisheng.knowledge.application.web_link_upload import PreparedWebLink, snapshot_revision

    def material(html, final):
        return PreparedWebLink(
            "sample.md",
            "same-markdown",
            b"body",
            html,
            "{}",
            {"source_url": "https://example.invalid", "final_url": final},
        )

    a = material(b"A", "https://example.invalid/a")
    assert snapshot_revision(a) == snapshot_revision(a)
    assert snapshot_revision(a) != snapshot_revision(material(b"B", "https://example.invalid/a"))
    assert snapshot_revision(a) != snapshot_revision(material(b"A", "https://example.invalid/b"))


@pytest.mark.parametrize("operation", ["file", "url", "chunks", "chunks_string"])
async def test_incompatible_external_write_is_rejected_before_reading_or_fetching(operation, monkeypatch):
    space = SimpleNamespace(id=3, tenant_id=1, type=KnowledgeTypeEnum.SPACE.value)
    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=space))
    monkeypatch.setattr(
        filelib, "get_open_api_operator_async", AsyncMock(return_value=SimpleNamespace(tenant_id=1, user_id=8))
    )
    monkeypatch.setattr(
        provider, "resolve_space_route", AsyncMock(return_value=SimpleNamespace(provider_key="weknora"))
    )

    def forbidden(*args, **kwargs):
        pytest.fail("local file saved or external URL fetched before provider dispatch")

    monkeypatch.setattr(filelib, "save_download_file", forbidden)
    monkeypatch.setattr(filelib, "async_file_download", forbidden)
    f = UploadFile(BytesIO(b"proof"), filename="proof.txt")
    with pytest.raises(provider.ProviderFeatureUnavailable):
        if operation in ("file", "url"):
            await filelib.upload_file(
                request=None,
                knowledge_id=3,
                file=f if operation == "file" else None,
                file_url="https://example.invalid/file" if operation == "url" else None,
            )
        elif operation == "chunks":
            await filelib.post_chunks(request=None, knowledge_id=3, metadata="{}", file=f)
        else:
            await filelib.post_string_chunks(
                request=None,
                document=ChunkInput(
                    knowledge_id=3, documents=[Document(page_content="x", metadata={"source": "x.txt"})]
                ),
            )
