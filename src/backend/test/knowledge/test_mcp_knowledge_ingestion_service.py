import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest

from bisheng.common.errcode.knowledge_space import (
    KnowledgeDocumentStateConflictError,
    SpaceFileDuplicateError,
    SpacePermissionDeniedError,
)
from bisheng.knowledge.domain.services.knowledge_mcp_ingestion_service import KnowledgeMcpIngestionService
from test.knowledge.test_mcp_knowledge_query_service import make_query


def make_ingestion():
    query, _, owner = make_query()

    async def permissions(kind, object_id, **kwargs):
        return {"view_space", "upload_file_to_space"}

    owner._get_effective_permission_ids = permissions
    owner.add_file = AsyncMock(return_value=[SimpleNamespace(id=7, file_name="a.txt", status=5)])
    owner.get_preview_cache_key = lambda space_id, path: "cache"
    owner.enqueue_file_title_extraction = AsyncMock()
    storage = SimpleNamespace(
        tmp_bucket="tmp",
        put_object_tmp=AsyncMock(),
        remove_object=AsyncMock(),
        get_share_link=AsyncMock(return_value="https://example.test/staged.txt"),
    )
    service = KnowledgeMcpIngestionService(
        query,
        storage,
        max_file_bytes=50 * 1024 * 1024,
        max_text_bytes=10 * 1024 * 1024,
        size_validator=lambda *args: None,
        name_factory=AsyncMock(return_value="uuid.txt"),
    )
    return service, query, owner, storage


@pytest.mark.parametrize("method", ["create_document", "upload_file"])
async def test_write_preserves_bytes_and_returns_real_queue_state(method):
    """AC-11, AC-12: both sources use the same authorized ingestion and dispatch."""
    service, _, owner, storage = make_ingestion()
    raw = "你好\n".encode()
    args = (
        {"content": raw.decode(), "content_format": "text"}
        if method == "create_document"
        else {
            "content_base64": base64.b64encode(raw).decode(),
        }
    )
    result = await getattr(service, method)(knowledge_id=1, file_name="a.txt", **args)
    assert result == {
        "file_id": 7,
        "knowledge_id": 1,
        "folder_id": None,
        "file_name": "a.txt",
        "status": 5,
        "accepted": True,
        "content_ready": False,
    }
    assert storage.put_object_tmp.call_args.kwargs["file"] == raw
    assert owner.add_file.call_args.kwargs["enqueue_processing"] is False
    owner.enqueue_file_title_extraction.assert_awaited_once()
    storage.remove_object.assert_awaited_once()


@pytest.mark.parametrize("case", ["denied", "invalid_base64", "too_large", "duplicate"])
async def test_rejected_upload_does_not_replace_existing_file(case):
    """AC-13, AC-14: permissions, bytes and duplicate failures never report accepted."""
    service, query, owner, storage = make_ingestion()
    payload = base64.b64encode(b"abc").decode()
    if case == "denied":
        query._permission_cache[("knowledge_space", 1, None)] = {"view_space"}
    elif case == "invalid_base64":
        payload = "not!base64"
    elif case == "too_large":
        service.max_file_bytes = 2
    else:
        owner.add_file.return_value[0].status = 3
    with pytest.raises((ValueError, SpacePermissionDeniedError, SpaceFileDuplicateError)):
        await service.upload_file(knowledge_id=1, file_name="a.txt", content_base64=payload)
    owner.enqueue_file_title_extraction.assert_not_called()
    if case != "duplicate":
        owner.add_file.assert_not_called()
        storage.put_object_tmp.assert_not_called()


async def test_dispatch_failure_preserves_known_file_and_reports_uncertainty(caplog):
    """AC-15: a possibly published task cannot be compensated by deleting its file."""
    service, _, owner, storage = make_ingestion()
    owner.enqueue_file_title_extraction.side_effect = RuntimeError("broker result uncertain")
    with pytest.raises(KnowledgeDocumentStateConflictError) as caught:
        await service.upload_file(knowledge_id=1, file_name="a.txt", content_base64="YQ==")
    assert caught.value.kwargs["file_id"] == 7
    assert caught.value.kwargs["mcp_write_uncertain"] is True
    storage.remove_object.assert_awaited_once()
    assert "file_id=7" in caplog.text and "broker result uncertain" not in caplog.text


async def test_large_file_and_utf8_text_use_adjusted_limits():
    """AC-13: accepted boundaries use 50 MiB and 10 MiB rather than old limits."""
    service, _, _, storage = make_ingestion()
    raw = b"x" * (50 * 1024 * 1024)
    await service.upload_file(knowledge_id=1, file_name="a.txt", content_base64=base64.b64encode(raw).decode())
    assert len(storage.put_object_tmp.call_args.kwargs["file"]) == len(raw)
    storage.put_object_tmp.reset_mock()
    await service.create_document(
        knowledge_id=1, file_name="a.txt", content_format="text", content="x" * (10 * 1024 * 1024)
    )
    assert len(storage.put_object_tmp.call_args.kwargs["file"]) == 10 * 1024 * 1024
    with pytest.raises(ValueError):
        await service.create_document(
            knowledge_id=1, file_name="a.txt", content_format="text", content="中" * (10 * 1024 * 1024 // 3 + 1)
        )


@pytest.mark.parametrize("phase", ["staging", "dispatch"])
async def test_cancellation_respects_write_side_effect_boundary(phase):
    """AC-15: pre-write cancellation cleans staging; committed handoff is shielded."""
    service, _, owner, storage = make_ingestion()
    entered = anyio.Event()
    completed = []

    async def pause(*args, **kwargs):
        entered.set()
        await anyio.sleep(0.05)

    if phase == "staging":
        storage.put_object_tmp.side_effect = pause
    else:
        owner.enqueue_file_title_extraction.side_effect = pause

    async def writer():
        completed.append(await service.upload_file(knowledge_id=1, file_name="a.txt", content_base64="YQ=="))

    async with anyio.create_task_group() as group:
        group.start_soon(writer)
        await entered.wait()
        group.cancel_scope.cancel()
    storage.remove_object.assert_awaited_once()
    if phase == "staging":
        owner.add_file.assert_not_called()
        assert not completed
    else:
        assert completed[0]["file_id"] == 7 and completed[0]["accepted"]
