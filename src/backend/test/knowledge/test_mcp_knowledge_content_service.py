import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.knowledge import KnowledgeChunkError
from bisheng.common.errcode.knowledge_space import KnowledgeDocumentStateConflictError, SpacePermissionDeniedError
from bisheng.knowledge.domain.services.knowledge_mcp_content_service import KnowledgeMcpContentService
from test.knowledge.test_mcp_knowledge_query_service import item, make_query


@pytest.fixture(autouse=True)
def real_utilities(monkeypatch):
    # Load real utility functions instead of copying the globally stubbed helpers.
    module = importlib.import_module("bisheng.knowledge.domain.services.knowledge_mcp_content_service")
    base = importlib.import_module("bisheng.common.services.base")
    monkeypatch.setattr(base, "BaseService", object)
    path = Path(module.__file__).with_name("knowledge_utils.py")
    spec = importlib.util.spec_from_file_location("mcp_real_knowledge_utils", path)
    actual = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(actual)
    monkeypatch.setattr(module, "KnowledgeService", actual.KnowledgeUtils)


def make_content():
    query, repo, _ = make_query()
    file = item(3)
    file.preview_file_object_name = "preview/3.pdf"
    repo.find_by_id.return_value = file
    repo.content_refs = AsyncMock(return_value={3: (8, 11, 2)})
    repo.chunks = AsyncMock(return_value=[{"text": "abcdef", "metadata": {"chunk_index": 0}}])
    storage = SimpleNamespace(
        bucket="public",
        object_exists=AsyncMock(return_value=False),
        get_share_link=AsyncMock(return_value="https://example.test/preview"),
        get_minio_share_host=Mock(return_value="https://example.test"),
    )
    query.owner.get_file_preview = AsyncMock(
        return_value={"preview_url": "https://example.test/preview", "original_url": "https://example.test/original"}
    )
    resolved = SimpleNamespace(
        content_file_id=3,
        projection_ready=True,
        capabilities=SimpleNamespace(can_view=True, can_preview=True, can_download=False),
    )
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=resolved))
    return KnowledgeMcpContentService(repo, query, storage, resolver), query, repo, storage, file


async def test_current_content_pagination_and_version_change():
    """AC-07, AC-08: bounded content resumes only within the current authorized generation."""
    service, _, repo, _, _ = make_content()
    first = await service.get_file_detail(knowledge_id=1, file_id=3, max_chars=3)
    assert first["content"] == "abc" and first["has_more"] and first["content_ready"]
    second = await service.get_file_detail(knowledge_id=1, file_id=3, max_chars=3, cursor=first["next_cursor"])
    assert second["content"] == "def" and not second["has_more"]
    assert repo.chunks.call_args.args[0].knowledge_id == 1
    repo.content_refs.return_value = {3: (8, 12, 3)}
    with pytest.raises((KnowledgeDocumentStateConflictError, ValueError)):
        await service.get_file_detail(knowledge_id=1, file_id=3, cursor=first["next_cursor"])


async def test_unparsed_and_denied_files_never_read_content():
    """AC-07, AC-17: parse state and authorization are distinct from empty content."""
    service, query, repo, storage, file = make_content()
    file.status = 5
    result = await service.get_file_detail(knowledge_id=1, file_id=3)
    assert not result["content_ready"] and result["content"] == ""
    repo.chunks.assert_not_called()
    query._permission_cache[("knowledge_file", 3, 1)] = set()
    with pytest.raises(SpacePermissionDeniedError):
        await service.get_file_detail(knowledge_id=1, file_id=3)
    storage.object_exists.assert_not_called()


async def test_source_never_turns_preview_access_into_original_download():
    """AC-09: preview-only clients receive no original and explicit original fails before signing."""
    service, query, _, storage, _ = make_content()
    result = await service.get_file_source(knowledge_id=1, file_id=3)
    assert result["preview_url"] and not result["original_url"]
    assert result["original_unavailable_reason"]
    query.owner.get_file_preview.reset_mock()
    with pytest.raises(SpacePermissionDeniedError):
        await service.get_file_source(knowledge_id=1, file_id=3, source_type="original")
    storage.get_share_link.assert_not_called()
    query.owner.get_file_preview.assert_not_called()


@pytest.mark.parametrize(
    ("filename", "detail", "expected"),
    [
        ("note.md", {"original_url": "/public/note.md?signature=native"}, "/public/note.md?signature=native"),
        ("scan.PDF", {"original_url": "/public/scan.pdf?signature=native"}, "/public/scan.pdf?signature=native"),
        ("note.txt", {"original_url": "/public/note.txt"}, "/public/note.txt"),
        ("image.png", {"original_url": "/public/image.png"}, "/public/image.png"),
        (
            "report.docx",
            {"pdf_preview_url": "/public/current.pdf?signature=pdf", "preview_url": "/public/legacy.docx"},
            "/public/current.pdf?signature=pdf",
        ),
        ("page.html", {"html_preview_url": "/public/snapshot.html"}, "/public/snapshot.html"),
        ("sheet.xlsx", {"preview_url": "https://cdn.example.test/sheet.xlsx"}, "https://cdn.example.test/sheet.xlsx"),
    ],
)
async def test_source_uses_existing_preview_sources_without_guessing_objects(filename, detail, expected):
    """AC-09-FIX: native and derived previews reuse the owner's existing signed links."""
    service, query, _, storage, file = make_content()
    file.file_name, file.preview_file_object_name = filename, None
    query.owner.get_file_preview.return_value = {**detail, "manager_file_id": 99, "source_url": "private"}
    result = await service.get_file_source(knowledge_id=1, file_id=3)
    assert result["preview_url"] == (expected if expected.startswith("https://") else "https://example.test" + expected)
    assert result["original_url"] == "" and "manager_file_id" not in result and "source_url" not in result
    query.owner.get_file_preview.assert_awaited_once_with(3)
    storage.object_exists.assert_not_called()
    storage.get_share_link.assert_not_called()


@pytest.mark.parametrize("denial", ["space", "file", "preview", "owner"])
async def test_source_preserves_permission_denials(denial):
    """AC-09-FIX: denied requests never fall through to a storage URL."""
    service, query, _, storage, _ = make_content()
    if denial == "space":
        query.repository.get_space.return_value = None
    elif denial == "file":
        query._permission_cache[("knowledge_file", 3, 1)] = set()
    elif denial == "preview":
        service.resolver.resolve.return_value.capabilities.can_preview = False
    else:
        query.owner.get_file_preview.side_effect = SpacePermissionDeniedError()
    with pytest.raises(SpacePermissionDeniedError):
        await service.get_file_source(knowledge_id=1, file_id=3)
    if denial != "owner":
        query.owner.get_file_preview.assert_not_called()
    storage.get_share_link.assert_not_called()


@pytest.mark.parametrize("detail", [{}, {"original_url": "https://example.test/private.docx"}])
async def test_source_missing_office_preview_never_falls_back_to_original(detail):
    service, query, _, storage, file = make_content()
    file.file_name = "report.docx"
    query.owner.get_file_preview.return_value = detail
    with pytest.raises(KnowledgeChunkError):
        await service.get_file_source(knowledge_id=1, file_id=3)
    storage.get_share_link.assert_not_called()


async def test_source_resolves_logical_entry_through_owner_entry_id():
    service, query, repo, _, entry = make_content()
    physical = item(11)
    physical.knowledge_id, physical.file_name = 2, "private-manager.docx"
    service.resolver.resolve.return_value.content_file_id = 11
    repo.find_by_id.side_effect = lambda file_id: entry if file_id == 3 else physical
    result = await service.get_file_source(knowledge_id=1, file_id=3, source_type="preview")
    query.owner.get_file_preview.assert_awaited_once_with(3)
    assert result["file_id"] == 3 and result["knowledge_id"] == 1
    assert "private-manager" not in str(result)


async def test_chunk_boundaries_preserve_separator_across_pages():
    """AC-08: concatenating pages must not lose the separator between chunks."""
    service, _, repo, _, _ = make_content()
    repo.chunks.return_value = [
        {"text": "abc", "metadata": {"chunk_index": 0}},
        {"text": "def", "metadata": {"chunk_index": 1}},
    ]
    first = await service.get_file_detail(knowledge_id=1, file_id=3, max_chars=3)
    second = await service.get_file_detail(knowledge_id=1, file_id=3, max_chars=3, cursor=first["next_cursor"])
    assert first["content"] + second["content"] == "abc\nde"


async def test_logical_entry_reads_current_physical_content_with_entry_scope():
    """AC-08, AC-17: public entry access does not expose its private manager metadata."""
    service, _, repo, _, entry = make_content()
    entry.reference_document_id, entry.entry_status = 8, "active"
    physical = item(11)
    physical.knowledge_id, physical.file_name = 2, "private-manager.txt"
    physical.preview_file_object_name = "preview/11.pdf"
    service.resolver.resolve.return_value.content_file_id = 11
    repo.find_by_id.side_effect = lambda file_id: entry if file_id == 3 else physical
    result = await service.get_file_detail(knowledge_id=1, file_id=3)
    assert result["file"]["id"] == 3 and result["file"]["knowledge_id"] == 1
    assert "private-manager" not in str(result)
    assert result["content"] == "abcdef"
    assert repo.chunks.call_args.args == (entry, (8, 11, 2))
