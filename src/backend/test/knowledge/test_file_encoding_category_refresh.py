"""分类元数据变化须刷新全部有效入口, 不扩大内容投影派发范围。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.constants import normalize_file_category_code
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_space_service as subject


@pytest.mark.parametrize("mode", ["split_rule", "encoding", "subcategory", "unchanged", "enqueue_failure"])
async def test_file_category_refresh_covers_all_entries_and_propagates_failure(monkeypatch, mode):
    old_code = "POL" if mode in {"split_rule", "enqueue_failure"} else "STD"
    file = KnowledgeFile(
        id=501,
        tenant_id=1,
        knowledge_id=10,
        reference_document_id=91,
        entry_type="manager",
        entry_status="active",
        file_encoding="SG-STD-EM-2026100001",
        split_rule=json.dumps({"file_category_code": old_code, "business_domain_code": "EM"}),
        file_subcategory_code="STD-A",
        file_subcategory_source="manual",
    )
    service = object.__new__(subject.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=1, user_name="管理员", tenant_id=1)
    service.normalize_file_category_code = normalize_file_category_code
    service._get_file_for_action = AsyncMock(return_value=file)
    service._require_file_metadata_edit_permission = AsyncMock(return_value=object())
    service._ensure_unique_file_encoding = AsyncMock(side_effect=lambda value, _: value)
    service._notify_favorite_source_changed = AsyncMock()
    service._enqueue_recommendation_files_refresh = MagicMock()
    service._enqueue_recommendation_file_refresh = MagicMock()
    service._enqueue_document_distribution_projection = AsyncMock()
    service.document_distribution_service = SimpleNamespace(
        update_manager_metadata=AsyncMock(
            return_value=SimpleNamespace(manager_file=file, active_entry_ids=(501, 502, 503)),
        )
    )
    monkeypatch.setattr(subject, "_require_not_write_frozen", AsyncMock())
    monkeypatch.setattr(
        subject.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(business_domain_codes=["EM"]))
    )
    monkeypatch.setattr(subject.KnowledgeFileDao, "async_update", AsyncMock(return_value=file))
    monkeypatch.setattr(subject.FileClassificationLabelService, "get_label_lookup_for_tenant", lambda _: ({}, {}))
    enqueue = AsyncMock(side_effect=RuntimeError("queue failed") if mode == "enqueue_failure" else None)
    monkeypatch.setattr(subject.KnowledgeSpaceContentStat, "enqueue_file_stat_async", enqueue)
    encoding = "SG-RPT-EM-2026100001" if mode == "encoding" else file.file_encoding
    subcategory = "STD-B" if mode == "subcategory" else None
    if mode == "enqueue_failure":
        with pytest.raises(RuntimeError, match="queue failed"):
            await service.update_file_encoding(501, encoding, subcategory)
    else:
        await service.update_file_encoding(501, encoding, subcategory)
    if mode == "unchanged":
        enqueue.assert_not_awaited()
    else:
        enqueue.assert_awaited_once_with([501, 502, 503])
    if mode in {"split_rule", "enqueue_failure", "unchanged"}:
        service._enqueue_document_distribution_projection.assert_not_awaited()


async def test_update_file_encoding_refreshes_similarity_candidates_and_sets_pending_status(monkeypatch):
    file = KnowledgeFile(
        id=601,
        tenant_id=1,
        knowledge_id=10,
        reference_document_id=95,
        entry_type="manager",
        entry_status="active",
        file_encoding="SG-STD-EM-2026100001",
        split_rule=json.dumps({"file_category_code": "STD", "business_domain_code": "EM"}),
        file_subcategory_code="STD-A",
        file_subcategory_source="manual",
        similar_status=0,
    )
    service = object.__new__(subject.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=1, user_name="管理员", tenant_id=1)
    service.normalize_file_category_code = normalize_file_category_code
    service._get_file_for_action = AsyncMock(return_value=file)
    service._require_file_metadata_edit_permission = AsyncMock(return_value=object())
    service._ensure_unique_file_encoding = AsyncMock(side_effect=lambda value, _: value)
    service._notify_favorite_source_changed = AsyncMock()
    service._enqueue_recommendation_files_refresh = MagicMock()
    service._enqueue_recommendation_file_refresh = MagicMock()
    service._enqueue_document_distribution_projection = AsyncMock()
    service._refresh_similarity_candidates_after_encoding_change = AsyncMock(return_value={601})
    service.document_distribution_service = SimpleNamespace(
        update_manager_metadata=AsyncMock(
            return_value=SimpleNamespace(manager_file=file, active_entry_ids=(601, 602)),
        )
    )
    monkeypatch.setattr(subject, "_require_not_write_frozen", AsyncMock())
    monkeypatch.setattr(
        subject.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(business_domain_codes=["EM", "PP"]))
    )
    monkeypatch.setattr(subject.KnowledgeFileDao, "async_update", AsyncMock(return_value=file))
    monkeypatch.setattr(subject.FileClassificationLabelService, "get_label_lookup_for_tenant", lambda _: ({}, {}))
    monkeypatch.setattr(subject.KnowledgeSpaceContentStat, "enqueue_file_stat_async", AsyncMock())

    updated = await service.update_file_encoding(601, "SG-RPT-PP-2026100001", None)
    service._refresh_similarity_candidates_after_encoding_change.assert_awaited_once_with([601, 602])
    assert updated.similar_status == 1


async def test_batch_update_file_encoding_fields_exposes_similar_candidate_file_ids(monkeypatch):
    file_with_candidate = KnowledgeFile(
        id=701,
        tenant_id=1,
        knowledge_id=10,
        file_encoding="SG-STD-EM-2026100001",
        similar_status=0,
    )
    file_without_candidate = KnowledgeFile(
        id=702,
        tenant_id=1,
        knowledge_id=10,
        file_encoding="SG-STD-EM-2026100002",
        similar_status=0,
    )
    service = object.__new__(subject.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=1, user_name="管理员", tenant_id=1)
    service.normalize_file_category_code = normalize_file_category_code
    service._require_read_permission = AsyncMock()
    service._get_space_files_or_raise = AsyncMock(return_value=[file_with_candidate, file_without_candidate])

    async def fake_update(fid: int, new_encoding: str, subcategory: str | None = None):
        target = file_with_candidate if fid == 701 else file_without_candidate
        target.file_encoding = new_encoding
        target.similar_status = 1 if fid == 701 else 0
        return target

    service.update_file_encoding = AsyncMock(side_effect=fake_update)
    monkeypatch.setattr(
        subject.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(business_domain_codes=["EM", "PP"]))
    )

    result = await service.batch_update_file_encoding_fields(
        10,
        [701, 702],
        file_category_code="RPT",
        business_domain_code="PP",
    )
    assert result["updated_file_ids"] == [701, 702]
    assert result["skipped"] == []
    assert result["similar_candidate_file_ids"] == [701]


def test_manager_pending_projection_context_remains_valid_for_similarity():
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.schemas.knowledge_similarity_context import KnowledgeSimilarityContext

    manager_entry = KnowledgeFile(
        id=801,
        tenant_id=1,
        knowledge_id=10,
        file_name="manager.doc",
        file_type=1,
        status=2,
        reference_document_id=99,
        entry_type="manager",
        entry_status="active",
        projection_status="pending",
        applied_content_generation=1,
        desired_content_generation=2,
        applied_entry_generation=1,
        desired_entry_generation=1,
        md5="m1",
        simhash="582b2adff04fbdd7",
        file_encoding="GF-RPT-RD-20261100000005",
        file_subcategory_code="RPT-6DJP",
    )
    doc = KnowledgeDocument(
        id=99,
        tenant_id=1,
        knowledge_id=10,
        primary_version_id=199,
        lifecycle_status="active",
        content_generation=2,
    )
    ver = KnowledgeDocumentVersion(
        id=199,
        document_id=99,
        knowledge_file_id=801,
        version_no=1,
        is_primary=True,
    )
    ctx_pending = KnowledgeSimilarityContext(
        entry=manager_entry,
        document=doc,
        version=ver,
        content=manager_entry,
    )
    assert ctx_pending.valid is True

    manager_ready = manager_entry.model_copy(
        update={"projection_status": "ready", "applied_content_generation": 2}
    )
    ctx_ready = KnowledgeSimilarityContext(
        entry=manager_ready,
        document=doc,
        version=ver,
        content=manager_ready,
    )
    assert ctx_ready.valid is True
    assert ctx_pending.signature == ctx_ready.signature

