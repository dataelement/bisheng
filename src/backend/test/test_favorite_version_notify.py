"""版本管理变更 → 收藏站内信 的单元测试。

覆盖三条版本变更路径都会通知收藏了受影响文件的用户：
  - 共享方法 _notify_favorite_version_changed：按 file_id 去重、用 VERSION action_code、
    message_service 缺失时不发。
  - set_primary_version（设为主版本）：实际切换时通知「新主 + 旧主」；已是主版本则不发。
  - merge_source_document_into_current（关联其他版本/关联文档）：通知「被吸收的源文件 + 旧主」。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.services.favorite_notify import (
    FAVORITE_SOURCE_PRIMARY_VERSION_CHANGED,
    FAVORITE_SOURCE_VERSION_LINKED,
)
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

SUCCESS = KnowledgeFileStatus.SUCCESS.value
_AUDIT = "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service.KnowledgeAuditTelemetryService"


def _svc(user_id=9):
    s = KnowledgeVersionService.__new__(KnowledgeVersionService)
    s.login_user = SimpleNamespace(user_id=user_id, user_name="editor", tenant_id=1)
    s.request = None
    s.message_service = object()  # truthy sentinel
    s.version_repo = AsyncMock()
    s.doc_repo = AsyncMock()
    s.knowledge_file_repo = AsyncMock()
    s.similar_candidate_repo = None  # _delete_similarity_candidate_cache_by_file_ids no-ops
    return s


# ── 共享方法 _notify_favorite_version_changed ─────────────────────────────

@pytest.mark.asyncio
async def test_notify_version_changed_dedups_and_uses_version_action():
    s = _svc()
    with patch(
        "bisheng.knowledge.domain.services.knowledge_version_service."
        "enqueue_favorite_change_events"
    ) as enqueue:
        await s._notify_favorite_version_changed(
            [(101, "a.pdf", 3), (102, "", 3), (101, "dup", 3)],
            action_code=FAVORITE_SOURCE_VERSION_LINKED,
            before_value="V1",
            after_value="V2",
        )
    events = enqueue.call_args.args[0]
    assert len(events) == 2
    assert {event.action_code for event in events} == {
        FAVORITE_SOURCE_VERSION_LINKED
    }
    assert sorted(event.source_file_id for event in events) == [101, 102]
    assert all(event.actor_user_id == 9 for event in events)


@pytest.mark.asyncio
async def test_notify_version_changed_noop_for_equal_version_values():
    s = _svc()
    with patch(
        "bisheng.knowledge.domain.services.knowledge_version_service."
        "enqueue_favorite_change_events"
    ) as enqueue:
        await s._notify_favorite_version_changed(
            [(101, "a", 3)],
            action_code=FAVORITE_SOURCE_PRIMARY_VERSION_CHANGED,
            before_value="V2",
            after_value="V2",
        )
    enqueue.assert_not_called()


# ── set_primary_version 门控 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_primary_notifies_promoted_and_demoted():
    s = _svc()
    target_version = SimpleNamespace(id=5, document_id=77, knowledge_file_id=101, is_primary=False, version_no=2)
    target_kf = SimpleNamespace(id=101, file_name="new.pdf", knowledge_id=3, status=SUCCESS)
    old_primary = SimpleNamespace(id=4, knowledge_file_id=100, version_no=1)
    current_kf = SimpleNamespace(
        id=100,
        file_name="old.pdf",
        knowledge_id=3,
        status=SUCCESS,
        reference_document_id=None,
        entry_type=None,
    )
    s.doc_repo.find_by_id = AsyncMock(
        return_value=SimpleNamespace(id=77, primary_version_id=4)
    )
    s.version_repo.find_by_id = AsyncMock(
        side_effect=lambda version_id: target_version if version_id == 5 else old_primary
    )
    s.knowledge_file_repo.find_by_id = AsyncMock(
        side_effect=lambda file_id: target_kf if file_id == 101 else current_kf
    )
    s.version_repo.find_primary = AsyncMock(return_value=old_primary)

    with patch.object(KnowledgeVersionService, "_require_version_management_enabled", new=AsyncMock()), \
         patch(f"{_AUDIT}.audit_set_primary_version", new=MagicMock()), \
         patch.object(KnowledgeVersionService, "_notify_favorite_version_changed", new=AsyncMock()) as notify:
        await s.set_primary_version(5)

    notify.assert_awaited_once()
    affected = notify.await_args.args[0]
    fids = [fid for fid, _, _ in affected]
    assert 101 in fids and 100 in fids  # 新主 + 旧主
    assert (101, "new.pdf", 3) in affected
    assert notify.await_args.kwargs["action_code"] == FAVORITE_SOURCE_PRIMARY_VERSION_CHANGED


@pytest.mark.asyncio
async def test_set_primary_no_notify_when_already_primary():
    s = _svc()
    target_version = SimpleNamespace(id=5, document_id=77, knowledge_file_id=101, is_primary=True, version_no=1)
    target_kf = SimpleNamespace(
        id=101,
        file_name="x.pdf",
        knowledge_id=3,
        status=SUCCESS,
        reference_document_id=None,
        entry_type=None,
    )
    s.doc_repo.find_by_id = AsyncMock(
        return_value=SimpleNamespace(id=77, primary_version_id=5)
    )
    s.version_repo.find_by_id = AsyncMock(return_value=target_version)
    s.knowledge_file_repo.find_by_id = AsyncMock(return_value=target_kf)

    with patch.object(KnowledgeVersionService, "_require_version_management_enabled", new=AsyncMock()), \
         patch(f"{_AUDIT}.audit_set_primary_version", new=MagicMock()), \
         patch.object(KnowledgeVersionService, "_notify_favorite_version_changed", new=AsyncMock()) as notify:
        await s.set_primary_version(5)

    notify.assert_not_awaited()  # 已是主版本，无变化不发


# ── merge_source_document_into_current（关联其他版本） ─────────────────────

@pytest.mark.asyncio
async def test_merge_notifies_source_and_demoted_primary():
    s = _svc()
    current_kf = SimpleNamespace(id=1, file_name="cur.pdf", knowledge_id=3, status=SUCCESS, md5="cur")
    current_v = SimpleNamespace(id=2, document_id=77, knowledge_file_id=1)
    source_doc = SimpleNamespace(id=88, knowledge_id=3)
    source_version = SimpleNamespace(id=9, knowledge_file_id=201, document_id=88)
    source_kf = SimpleNamespace(
        id=201,
        file_name="src.pdf",
        knowledge_id=3,
        status=SUCCESS,
        md5="abc",
        similar_status=1,
    )
    old_primary = SimpleNamespace(id=4, knowledge_file_id=100)
    saved = SimpleNamespace(id=50)

    s.knowledge_file_repo.find_by_id = AsyncMock(side_effect=lambda fid: {1: current_kf, 201: source_kf}.get(fid))
    s.knowledge_file_repo.find_by_ids = AsyncMock(return_value=[])
    s.version_repo.find_by_knowledge_file_id = AsyncMock(return_value=current_v)
    s.doc_repo.find_by_id = AsyncMock(return_value=source_doc)
    # find_by_document_id: source_document_id=88 -> [source_version]; target_doc_id=77 -> [] (existing)
    s.version_repo.find_by_document_id = AsyncMock(side_effect=lambda did: [source_version] if did == 88 else [])
    s.version_repo.find_primary = AsyncMock(return_value=old_primary)
    s.version_repo.next_version_no = AsyncMock(return_value=2)
    s.version_repo.save = AsyncMock(return_value=saved)

    with patch.object(KnowledgeVersionService, "_require_version_management_enabled", new=AsyncMock()), \
         patch(f"{_AUDIT}.audit_link_file_version", new=MagicMock()), \
         patch.object(KnowledgeVersionService, "_notify_favorite_version_changed", new=AsyncMock()) as notify:
        await s.merge_source_document_into_current(
            current_knowledge_file_id=1, source_document_id=88, force=True
        )

    notify.assert_awaited_once()
    affected = notify.await_args.args[0]
    fids = [fid for fid, _, _ in affected]
    assert 201 in fids and 100 in fids  # 被吸收的源文件 + 旧主
    assert (201, "src.pdf", 3) in affected
