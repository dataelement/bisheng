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
