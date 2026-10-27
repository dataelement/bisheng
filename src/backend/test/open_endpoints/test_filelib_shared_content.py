import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge import (
    KnowledgeSharedContentNotReadyError,
    KnowledgeSharedStorageUnavailableError,
)
from bisheng.common.errcode.knowledge_space import KnowledgeDocumentStateConflictError, SpacePermissionDeniedError
from bisheng.open_endpoints.domain.services.filelib_space_content_service import FilelibSpaceContentService


@pytest.fixture(autouse=True)
def real_text_utilities(monkeypatch):
    base = importlib.import_module("bisheng.common.services.base")
    monkeypatch.setattr(base, "BaseService", object)
    owner = importlib.import_module("bisheng.knowledge.domain.services.knowledge_service")
    path = Path(owner.__file__).with_name("knowledge_utils.py")
    spec = importlib.util.spec_from_file_location("f112_real_utils", path)
    utilities = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utilities)
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_space_content_service.KnowledgeService",
        utilities.KnowledgeUtils,
    )
    return utilities.KnowledgeUtils


def content_service():
    entry = SimpleNamespace(id=12, tenant_id=1, knowledge_id=7, status=2, file_type=1)
    physical = SimpleNamespace(
        id=99,
        tenant_id=1,
        knowledge_id=9,
        status=2,
        file_type=1,
        file_name="report.pdf",
        preview_file_object_name=None,
        update_time="v1",
        md5="sum",
    )
    repository = SimpleNamespace(
        find_by_id=AsyncMock(side_effect=lambda file_id: entry if file_id == 12 else physical),
        content_refs=AsyncMock(return_value={12: (100, 200, 3)}),
        primary_flags=AsyncMock(return_value={}),
        fresh_content_state=AsyncMock(return_value=((100, 200, 3), 99, 2, "sum", "v1", None)),
        chunks=AsyncMock(
            return_value=[
                {"text": "正文一", "metadata": {"chunk_index": 0}},
                {"text": "正文二", "metadata": {"chunk_index": 1}},
            ]
        ),
    )
    resolved = SimpleNamespace(
        content_file_id=99,
        canonical_document_id=100,
        canonical_version_id=200,
        content_generation=3,
        applied_entry_generation=2,
        projection_ready=True,
        capabilities=SimpleNamespace(can_view=True),
    )
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=resolved))
    storage = SimpleNamespace(
        bucket="files", object_exists=AsyncMock(return_value=False), get_object=AsyncMock(return_value=b"")
    )
    guard = SimpleNamespace(
        require_space=AsyncMock(return_value=SimpleNamespace(id=7, type=3)),
        route=AsyncMock(return_value=SimpleNamespace(routing_version=1)),
    )
    service = FilelibSpaceContentService(
        repository=repository, resolver=resolver, storage=storage, guard=guard, user=SimpleNamespace(tenant_id=1)
    )
    return service, repository, resolver, storage, entry


async def test_text_miss_returns_shared_chunks_for_logical_entry():
    service, repo, resolver, storage, entry = content_service()
    assert await service.read(entry, "text") == ("正文一\n正文二", 2)
    assert repo.chunks.await_args.args == (entry, (100, 200, 3))
    assert all(
        call.args[1].startswith(("preview/99.", "text/99.", "markdown/99."))
        for call in storage.object_exists.await_args_list
    )
    assert resolver.resolve.await_count == 2


@pytest.mark.parametrize("denial", ["permission", "pending", "historical", "changed", "backend", "missing"])
async def test_content_refuses_unsafe_or_unavailable_results(denial):
    service, repo, resolver, storage, entry = content_service()
    expected = KnowledgeSharedContentNotReadyError
    if denial == "permission":
        resolver.resolve.return_value.capabilities.can_view = False
        expected = SpacePermissionDeniedError
    elif denial == "pending":
        resolver.resolve.return_value.projection_ready = False
    elif denial == "historical":
        repo.primary_flags.return_value = {12: False}
        expected = KnowledgeDocumentStateConflictError
    elif denial == "changed":
        repo.content_refs.side_effect = [{12: (100, 200, 3)}, {12: (100, 201, 4)}]
        expected = KnowledgeDocumentStateConflictError
    elif denial == "backend":
        repo.chunks.side_effect = ConnectionError("ES offline")
        expected = KnowledgeSharedStorageUnavailableError
    else:
        repo.chunks.return_value = []
    with pytest.raises(expected):
        await service.read(entry, "text")
    if denial in {"permission", "pending", "historical"}:
        storage.object_exists.assert_not_awaited()
        repo.chunks.assert_not_awaited()


async def test_text_object_uses_actual_file_and_still_checks_version():
    service, repo, _, storage, entry = content_service()
    storage.object_exists.side_effect = lambda bucket, name: name == "preview/99.md"
    storage.get_object.return_value = "# 正文".encode()
    assert await service.read(entry, "markdown") == ("# 正文", 1)
    repo.chunks.assert_not_awaited()
    assert repo.content_refs.await_count == 2


async def test_complete_content_reads_more_than_one_shared_page():
    service, repo, _, _, entry = content_service()
    repo.chunks.side_effect = [
        [{"text": str(i), "metadata": {"chunk_index": i}} for i in range(100)],
        [{"text": "last", "metadata": {"chunk_index": 100}}],
    ]
    text, count = await service.read(entry, "text")
    assert count == 101 and text.endswith("\nlast")
    assert repo.chunks.await_args.kwargs["from_index"] == 100


async def test_fresh_transaction_detects_a_change_hidden_by_the_original_read():
    service, repo, _, _, entry = content_service()
    repo.fresh_content_state.return_value = ((100, 201, 4), 100, 3, "new", "v2", None)
    with pytest.raises(KnowledgeDocumentStateConflictError):
        await service.read(entry, "text")
