"""Knowledge-space delete adapters must preserve F059 lifecycle boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import (
    KnowledgeDocumentActiveShareError,
    KnowledgeDocumentDownloadDeniedError,
    KnowledgeDocumentEntryTypeInvalidError,
    KnowledgeDocumentManagerRequiredError,
    KnowledgeDocumentStateConflictError,
)
from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
)
from bisheng.knowledge.domain.schemas.knowledge_document_distribution_schema import (
    KnowledgeDocumentEntryCapabilities,
    ResolvedKnowledgeDocumentEntry,
)
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
    DeleteManagerResult,
    KnowledgeDocumentDistributionError,
    RemoveShareEntryResult,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


def _service() -> KnowledgeSpaceService:
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=UserPayload(
            user_id=11,
            user_name="tester",
            tenant_id=7,
        ),
    )
    service.document_distribution_service = SimpleNamespace(
        remove_share_entry=AsyncMock(),
        delete_manager=AsyncMock(),
        file_repository=SimpleNamespace(
            find_distribution_entries_by_document_id=AsyncMock()
        ),
    )
    service._enqueue_document_distribution_projection = AsyncMock()
    return service


def _entry(
    entry_type: KnowledgeFileEntryType,
    *,
    file_id: int = 101,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=7,
        knowledge_id=20,
        file_name="distributed.pdf",
        file_type=1,
        reference_document_id=91,
        entry_type=entry_type.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
    )


async def test_share_direct_delete_routes_to_distribution_lifecycle() -> None:
    service = _service()
    share = _entry(KnowledgeFileEntryType.SHARE)
    service.document_distribution_service.remove_share_entry.return_value = (
        RemoveShareEntryResult(
            document_id=91,
            share_entry_id=101,
            idempotent=False,
        )
    )

    handled = await service._handle_distribution_file_delete(share)

    assert handled is True
    service.document_distribution_service.remove_share_entry.assert_awaited_once_with(
        tenant_id=7,
        document_id=91,
        share_entry_id=101,
        actor_entry_id=101,
    )
    service.document_distribution_service.delete_manager.assert_not_awaited()
    service._enqueue_document_distribution_projection.assert_awaited_once_with(
        tenant_id=7,
        entry_ids=[101],
    )


async def test_publish_direct_delete_is_always_rejected() -> None:
    service = _service()

    with pytest.raises(KnowledgeDocumentEntryTypeInvalidError):
        await service._handle_distribution_file_delete(
            _entry(KnowledgeFileEntryType.PUBLISH)
        )

    service.document_distribution_service.remove_share_entry.assert_not_awaited()
    service.document_distribution_service.delete_manager.assert_not_awaited()


async def test_manager_delete_maps_active_share_conflict_to_18099() -> None:
    service = _service()
    service.document_distribution_service.delete_manager.side_effect = (
        KnowledgeDocumentDistributionError(
            "active shares must be revoked before final manager deletion"
        )
    )

    with pytest.raises(KnowledgeDocumentActiveShareError) as exc_info:
        await service._handle_distribution_file_delete(
            _entry(KnowledgeFileEntryType.MANAGER)
        )

    assert exc_info.value.code == 18099


async def test_manager_delete_enqueues_all_due_document_entries() -> None:
    service = _service()
    service.document_distribution_service.delete_manager.return_value = (
        DeleteManagerResult(
            document_id=91,
            manager_file_id=101,
            action="rollback",
            tombstone_entry_id=102,
        )
    )

    handled = await service._handle_distribution_file_delete(
        _entry(KnowledgeFileEntryType.MANAGER)
    )

    assert handled is True
    service._enqueue_document_distribution_projection.assert_awaited_once_with(
        tenant_id=7,
        entry_ids=None,
    )


def test_container_delete_rejects_any_distribution_state() -> None:
    ordinary = KnowledgeFile(
        id=1,
        tenant_id=7,
        knowledge_id=20,
        file_name="ordinary.pdf",
        file_type=1,
    )
    deleting_share = _entry(KnowledgeFileEntryType.SHARE, file_id=2)
    deleting_share.entry_status = KnowledgeFileEntryStatus.DELETING.value

    KnowledgeSpaceService._ensure_container_has_no_distribution_entries(
        [ordinary]
    )
    with pytest.raises(KnowledgeDocumentStateConflictError) as exc_info:
        KnowledgeSpaceService._ensure_container_has_no_distribution_entries(
            [ordinary, deleting_share]
        )

    assert exc_info.value.code == 18098


async def test_delete_space_routes_to_retirement_without_distribution_blocker() -> None:
    service = _service()
    service.knowledge_space_retirement_service = SimpleNamespace(
        retire=AsyncMock(
            return_value=SimpleNamespace(entry_ids=[101, 102])
        )
    )
    service._require_permission_id = AsyncMock()
    service._send_space_event_notification = AsyncMock()
    service._list_space_child_resources = AsyncMock(
        side_effect=AssertionError("whole-space deletion must not run the 18098 blocker")
    )
    space = Knowledge(
        id=20,
        tenant_id=7,
        name="待删除知识库",
        type=KnowledgeTypeEnum.SPACE.value,
        state=KnowledgeState.PUBLISHED.value,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_members_by_space",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.audit_delete_knowledge_space",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.telemetry_delete_knowledge"
        ),
    ):
        await service.delete_space(20, migrate_free_space=False)

    service.knowledge_space_retirement_service.retire.assert_awaited_once_with(
        tenant_id=7,
        space_id=20,
    )
    service._list_space_child_resources.assert_not_awaited()


async def test_manager_can_list_and_revoke_share_entries() -> None:
    service = _service()
    manager = _entry(KnowledgeFileEntryType.MANAGER, file_id=100)
    share = _entry(KnowledgeFileEntryType.SHARE, file_id=101)
    share.knowledge_id = 30
    share.allow_download = True
    service._get_file_for_action = AsyncMock(return_value=manager)
    service._require_permission_id = AsyncMock()
    (
        service.document_distribution_service.file_repository
        .find_distribution_entries_by_document_id
    ).return_value = [manager, share]
    service.document_distribution_service.remove_share_entry.return_value = (
        RemoveShareEntryResult(
            document_id=91,
            share_entry_id=101,
            idempotent=False,
        )
    )

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "KnowledgeDao.aget_list_by_ids",
        new=AsyncMock(
            return_value=[
                SimpleNamespace(id=30, name="接收部门知识库")
            ]
        ),
    ):
        listed = await service.list_document_share_entries(
            source_file_id=100
        )
    revoked = await service.revoke_document_share(
        source_file_id=100,
        share_entry_id=101,
    )

    assert listed == {
        "data": [
            {
                "entry_id": 101,
                "target_space_id": 30,
                "target_space_name": "接收部门知识库",
                "allow_download": True,
                "entry_status": KnowledgeFileEntryStatus.ACTIVE.value,
                "create_time": None,
            }
        ],
        "total": 1,
    }
    assert revoked["share_entry_id"] == 101
    service.document_distribution_service.remove_share_entry.assert_awaited_once_with(
        tenant_id=7,
        document_id=91,
        share_entry_id=101,
        actor_entry_id=100,
    )


async def test_portal_download_resolves_logical_entry_to_canonical_content() -> None:
    service = _service()
    share = _entry(KnowledgeFileEntryType.SHARE, file_id=101)
    manager = _entry(KnowledgeFileEntryType.MANAGER, file_id=100)
    manager.knowledge_id = 20
    manager.object_name = "tenant/7/canonical.pdf"
    service._get_file_for_action = AsyncMock(return_value=share)
    service.document_entry_resolver = SimpleNamespace(
        resolve=AsyncMock(
            return_value=ResolvedKnowledgeDocumentEntry(
                tenant_id=7,
                requested_space_id=20,
                entry_file_id=101,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                canonical_document_id=91,
                canonical_version_id=501,
                content_file_id=100,
                manager_file_id=100,
                manager_space_id=20,
                capabilities=KnowledgeDocumentEntryCapabilities(
                    can_view=True,
                    can_download=True,
                ),
            )
        )
    )

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "KnowledgeFileDao.query_by_id",
        new=AsyncMock(return_value=manager),
    ):
        content = await service.resolve_shougang_portal_download_content(
            space_id=20,
            file_id=101,
        )

    assert content.id == 100


async def test_portal_download_denies_share_policy_before_physical_lookup() -> None:
    service = _service()
    share = _entry(KnowledgeFileEntryType.SHARE, file_id=101)
    service._get_file_for_action = AsyncMock(return_value=share)
    service.document_entry_resolver = SimpleNamespace(
        resolve=AsyncMock(
            return_value=ResolvedKnowledgeDocumentEntry(
                tenant_id=7,
                requested_space_id=20,
                entry_file_id=101,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                canonical_document_id=91,
                canonical_version_id=501,
                content_file_id=100,
                manager_file_id=100,
                manager_space_id=20,
                capabilities=KnowledgeDocumentEntryCapabilities(
                    can_view=True,
                    can_download=False,
                ),
            )
        )
    )

    with pytest.raises(KnowledgeDocumentDownloadDeniedError):
        await service.resolve_shougang_portal_download_content(
            space_id=20,
            file_id=101,
        )


@pytest.mark.parametrize(
    "entry_type",
    [
        KnowledgeFileEntryType.PUBLISH,
        KnowledgeFileEntryType.SHARE,
    ],
)
async def test_canonical_write_gate_rejects_non_manager_entry(
    entry_type: KnowledgeFileEntryType,
) -> None:
    service = _service()
    entry = _entry(entry_type)
    service.document_entry_resolver = SimpleNamespace(
        resolve=AsyncMock(
            return_value=ResolvedKnowledgeDocumentEntry(
                tenant_id=7,
                requested_space_id=20,
                entry_file_id=101,
                entry_type=entry_type.value,
                canonical_document_id=91,
                canonical_version_id=501,
                content_file_id=100,
                manager_file_id=100,
                manager_space_id=30,
                capabilities=KnowledgeDocumentEntryCapabilities(
                    can_view=True,
                    can_edit_content=False,
                ),
            )
        )
    )

    with pytest.raises(KnowledgeDocumentManagerRequiredError) as exc_info:
        await service._require_document_content_manager(entry)

    assert exc_info.value.code == 18096


async def test_canonical_write_gate_allows_authorized_active_manager() -> None:
    service = _service()
    manager = _entry(KnowledgeFileEntryType.MANAGER, file_id=100)
    service.document_entry_resolver = SimpleNamespace(
        resolve=AsyncMock(
            return_value=ResolvedKnowledgeDocumentEntry(
                tenant_id=7,
                requested_space_id=20,
                entry_file_id=100,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                canonical_document_id=91,
                canonical_version_id=501,
                content_file_id=100,
                manager_file_id=100,
                manager_space_id=20,
                capabilities=KnowledgeDocumentEntryCapabilities(
                    can_view=True,
                    can_edit_content=True,
                ),
            )
        )
    )

    resolved = await service._require_document_content_manager(manager)

    assert resolved.entry_file_id == 100


async def test_legacy_file_tag_api_rejects_share_entry_before_writing(
    monkeypatch,
) -> None:
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

    share = _entry(KnowledgeFileEntryType.SHARE)
    monkeypatch.setattr(
        KnowledgeService,
        "_get_writable_knowledge",
        AsyncMock(return_value=SimpleNamespace(id=20)),
    )
    monkeypatch.setattr(
        KnowledgeService,
        "_validate_knowledge_tag_ids",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeFileDao.query_by_id",
        AsyncMock(return_value=share),
    )
    write_tags = AsyncMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.TagDao.aupdate_resource_tags",
        write_tags,
    )

    with pytest.raises(KnowledgeDocumentManagerRequiredError):
        await KnowledgeService.update_file_tags(
            _service().login_user,
            knowledge_id=20,
            file_id=101,
            tag_ids=[1],
        )

    write_tags.assert_not_awaited()
