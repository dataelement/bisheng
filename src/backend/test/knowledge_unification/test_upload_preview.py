"""AC-23/24/25: temporary preview authorization and frozen input behavior."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanChangedError,
    KnowledgeOperationPlanConflictError,
    KnowledgePreviewError,
    KnowledgeProcessingJobNotFoundError,
)
from bisheng.knowledge.domain.schemas.upload_preview import UploadContextItem, UploadPreviewRequest
from bisheng.knowledge.domain.services.upload_preview_service import UploadPreviewService, digest
from bisheng.knowledge.rag.pipeline.transformer.preview_cache import PreviewCacheTransformer


class Receipts:
    def __init__(self):
        self.value = {
            "upload_id": "a" * 32,
            "space_id": 7,
            "parent_id": 9,
            "tenant_id": 101,
            "actor_user_id": 5,
            "file_name": "draft.md",
            "file_path": "tmp/draft.md",
            "state": "OPEN",
            "preview": None,
        }
        self.frozen = {}

    async def get(self, upload_id):
        if upload_id != self.value["upload_id"]:
            raise KnowledgeProcessingJobNotFoundError()
        return deepcopy(self.value)

    async def mutate(self, upload_id, change):
        value = await self.get(upload_id)
        frozen = change(value)
        if frozen:
            self.frozen[frozen[0]] = deepcopy(frozen[1])
        self.value = value
        return deepcopy(value)


@pytest.fixture
def service():
    space = SimpleNamespace(
        login_user=SimpleNamespace(user_id=5),
        require_upload_container=AsyncMock(return_value=SimpleNamespace(tenant_id=101)),
    )
    service = UploadPreviewService(space, Receipts())
    service.rule = AsyncMock(return_value=FileProcessBase(knowledge_id=7))
    return service


@pytest.mark.parametrize("field,value", [("actor_user_id", 6), ("tenant_id", 202), ("space_id", 8)])
async def test_cannot_read_another_upload(service, field, value):
    service.repository.value[field] = value
    with pytest.raises(KnowledgeProcessingJobNotFoundError):
        await service.read(7, "a" * 32)


async def test_folder_upload_action_is_the_only_resource_gate(service):
    await service.read(7, "a" * 32)
    service.space_service.require_upload_container.assert_awaited_once_with(7, 9)
    service.space_service.require_upload_container.side_effect = PermissionError("denied")
    with pytest.raises(PermissionError):
        await service.start(7, "a" * 32, {})
    assert service.repository.value["preview"] is None


async def ready(service):
    _, rule, preview_id = await service.start(7, "a" * 32, {})
    service.repository.value["preview"].update(
        status="completed",
        data={
            "chunks": [
                {"text": "first", "metadata": {"chunk_index": 0}},
                {"text": "second", "metadata": {"chunk_index": 1}},
            ]
        },
    )
    return rule, preview_id


async def test_edit_index_zero_and_stale_revision(service):
    _, pid = await ready(service)
    update = SimpleNamespace(text="edited", bbox='{"chunk_bboxes":[]}')
    result = await service.edit(7, "a" * 32, pid, 0, 0, update)
    assert result["revision"] == 1
    assert result["data"]["chunks"][0]["text"] == "edited"
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await service.edit(7, "a" * 32, pid, 0, 0, update)


async def test_replaced_preview_does_not_accept_old_edit(service):
    _, old = await ready(service)
    await service.start(7, "a" * 32, {})
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await service.edit(7, "a" * 32, old, 0, 0, SimpleNamespace(text="stale", bbox=""))


@pytest.mark.parametrize("revision,different_rule", [(0, False), (1, True)])
async def test_changed_preview_cannot_be_frozen(service, revision, different_rule):
    _, pid = await ready(service)
    service.repository.value["preview"]["revision"] = 1
    if different_rule:
        service.rule.return_value = FileProcessBase(knowledge_id=7, chunk_size=17, chunk_overlap=0)
    item = UploadContextItem(
        upload_id="a" * 32, file_path="tmp/draft.md", overrides={}, preview_id=pid, expected_revision=revision
    )
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await service.freeze(await service.read(7, "a" * 32), item, "previewed", "request")
    assert service.repository.value["state"] == "OPEN"


async def test_frozen_result_is_immutable_and_blocks_late_edit(service):
    _, pid = await ready(service)
    item = UploadContextItem(
        upload_id="a" * 32, file_path="tmp/draft.md", overrides={}, preview_id=pid, expected_revision=0
    )
    prepared = await service.freeze(await service.read(7, "a" * 32), item, "previewed", "request")
    assert prepared.cache_key.startswith("space_upload_frozen:")
    assert service.repository.frozen[prepared.cache_key][0]["text"] == "first"
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await service.edit(7, "a" * 32, pid, 0, 0, SimpleNamespace(text="late", bbox=""))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await service.freeze(await service.read(7, "a" * 32), item, "previewed", "request")


async def test_direct_upload_does_not_reuse_previous_preview_edits(service):
    await ready(service)
    item = UploadContextItem(upload_id="a" * 32, file_path="tmp/draft.md", overrides={})
    prepared = await service.freeze(await service.read(7, "a" * 32), item, "direct", "request")
    assert prepared.cache_key == ""
    assert not service.repository.frozen


def test_frozen_cache_loss_cannot_silently_reparse(monkeypatch):
    from bisheng.knowledge.rag.pipeline.transformer.preview_cache import KnowledgeUtils

    monkeypatch.setattr(KnowledgeUtils, "get_preview_cache", lambda key: {}, raising=False)
    with pytest.raises(KnowledgePreviewError):
        PreviewCacheTransformer("space_upload_frozen:missing", {}).transform_documents([])
    assert PreviewCacheTransformer("old-missing-key", {}).transform_documents([]) == []


@pytest.mark.parametrize("flag", [True, 1.0, "1"])
def test_new_preview_wire_rejects_noninteger_flags(flag):
    with pytest.raises(ValueError):
        UploadPreviewRequest(overrides={"document": {"force_ocr": flag}})


def test_rule_digest_is_order_independent():
    assert digest({"a": 0, "b": 1}) == digest({"b": 1, "a": 0})


def test_frozen_cache_preserves_numeric_chunk_order_and_rejects_incomplete_data(monkeypatch):
    from bisheng.knowledge.rag.pipeline.transformer.preview_cache import KnowledgeUtils

    values = {str(i): {"text": str(i), "metadata": {"chunk_index": i}} for i in [10, 2, 0]}
    monkeypatch.setattr(KnowledgeUtils, "get_preview_cache", lambda key: values, raising=False)
    monkeypatch.setattr(KnowledgeUtils, "aggregate_chunk_metadata", lambda text, meta: text, raising=False)
    transformer = PreviewCacheTransformer("space_upload_frozen:test", {})
    assert [doc.page_content for doc in transformer.transform_documents([])] == ["0", "2", "10"]
    values["2"] = {"text": "incomplete"}
    with pytest.raises(KnowledgePreviewError):
        transformer.transform_documents([])
