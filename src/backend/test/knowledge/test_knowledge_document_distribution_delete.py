"""Manager termination and recoverable final-delete tests for F059."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
    KnowledgeDocumentDistributionError,
    KnowledgeDocumentDistributionService,
    PublishKnowledgeDocumentCommand,
    ShareKnowledgeDocumentCommand,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
)
from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
    KnowledgeDocumentProjectionService,
)
from bisheng.knowledge.domain.services.knowledge_space_retirement_service import (
    KnowledgeSpaceRetirementService,
)


def _service(
    session: AsyncSession,
    *,
    tuple_writer=AsyncMock(),
) -> KnowledgeDocumentDistributionService:
    file_repository = KnowledgeFileRepositoryImpl(session)
    return KnowledgeDocumentDistributionService(
        session=session,
        document_repository=KnowledgeDocumentRepositoryImpl(session),
        version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
        file_repository=file_repository,
        permission_activation_service=KnowledgeDocumentPermissionActivationService(
            file_repository=file_repository,
            tuple_writer=tuple_writer,
        ),
        permission_snapshot_loader=AsyncMock(return_value=[]),
    )


async def _seed_manager(session: AsyncSession) -> None:
    session.add_all(
        [
            Knowledge(
                id=10,
                tenant_id=7,
                name="管理库",
                type=KnowledgeTypeEnum.SPACE.value,
                state=KnowledgeState.PUBLISHED.value,
            ),
            Knowledge(
                id=20,
                tenant_id=7,
                name="发布目标库",
                type=KnowledgeTypeEnum.SPACE.value,
                state=KnowledgeState.PUBLISHED.value,
            ),
            Knowledge(
                id=30,
                tenant_id=7,
                name="分享目标库",
                type=KnowledgeTypeEnum.SPACE.value,
                state=KnowledgeState.PUBLISHED.value,
            ),
            KnowledgeDocument(
                id=91,
                tenant_id=7,
                knowledge_id=10,
                primary_version_id=501,
                content_generation=3,
            ),
            KnowledgeFile(
                id=100,
                tenant_id=7,
                knowledge_id=10,
                file_name="canonical.pdf",
                object_name="tenant/7/canonical.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                file_level_path="/8",
                level=2,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
                desired_content_generation=3,
                applied_content_generation=3,
            ),
            KnowledgeDocumentVersion(
                id=501,
                document_id=91,
                knowledge_file_id=100,
                version_no=1,
                is_primary=True,
            ),
        ]
    )
    await session.commit()


def _publish_command(
    *,
    approval_instance_id: int,
    source_space: int,
    target_space: int,
    target_path: str,
) -> PublishKnowledgeDocumentCommand:
    return PublishKnowledgeDocumentCommand(
        tenant_id=7,
        approval_instance_id=approval_instance_id,
        document_id=91,
        source_entry_id=100,
        target_space_id=target_space,
        target_file_level_path=target_path,
        target_level=2,
    )


@pytest.mark.asyncio
async def test_delete_manager_invalidates_publish_predecessor_and_active_share(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    service = _service(async_db_session)
    published = await service.publish_approved(
        _publish_command(
            approval_instance_id=7001,
            source_space=10,
            target_space=20,
            target_path="/18",
        )
    )
    shared = await service.share_approved(
        ShareKnowledgeDocumentCommand(
            tenant_id=7,
            approval_instance_id=8001,
            document_id=91,
            source_entry_id=100,
            target_space_id=30,
        )
    )
    assert (
        await service.preflight_delete_entry(
            tenant_id=7,
            document_id=91,
            entry_id=100,
        )
        == "final_delete"
    )

    first = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
    )
    second = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
    )

    document = await KnowledgeDocumentRepositoryImpl(
        async_db_session
    ).find_by_id(91)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    predecessor = await repository.find_by_id(
        published.publish_entry_id
    )
    share = await repository.find_by_id(shared.share_entry_id)
    assert first.action == "final_delete"
    assert second.idempotent is True
    assert document.lifecycle_status == KnowledgeDocumentLifecycleStatus.DELETING.value
    assert document.knowledge_id == 20
    assert document.predecessor_logic_file_id == published.publish_entry_id
    assert manager.knowledge_id == 20
    assert manager.object_name == "tenant/7/canonical.pdf"
    assert manager.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert predecessor.entry_status == KnowledgeFileEntryStatus.INVALID.value
    assert share.entry_status == KnowledgeFileEntryStatus.INVALID.value
    assert predecessor.projection_status == KnowledgeFileProjectionStatus.PENDING.value
    assert share.projection_status == KnowledgeFileProjectionStatus.PENDING.value


@pytest.mark.asyncio
async def test_delete_manager_turns_legacy_rollback_state_into_cleanup(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    service = _service(async_db_session)
    published = await service.publish_approved(
        _publish_command(
            approval_instance_id=7001,
            source_space=10,
            target_space=20,
            target_path="/18",
        )
    )
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    manager.entry_status = KnowledgeFileEntryStatus.PREPARING.value
    tombstone = KnowledgeFile(
        id=102,
        tenant_id=7,
        knowledge_id=20,
        file_name="canonical.pdf",
        status=KnowledgeFileStatus.SUCCESS.value,
        reference_document_id=91,
        entry_type=KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
        entry_status=KnowledgeFileEntryStatus.PREPARING.value,
        projection_previous_file_id=100,
        projection_status=KnowledgeFileProjectionStatus.PENDING.value,
    )
    preparing_share = KnowledgeFile(
        id=103,
        tenant_id=7,
        knowledge_id=30,
        file_name="canonical.pdf",
        status=KnowledgeFileStatus.SUCCESS.value,
        reference_document_id=91,
        entry_type=KnowledgeFileEntryType.SHARE.value,
        entry_status=KnowledgeFileEntryStatus.PREPARING.value,
        approval_instance_id=8002,
        projection_status=KnowledgeFileProjectionStatus.PENDING.value,
    )
    async_db_session.add_all([manager, tombstone, preparing_share])
    await async_db_session.commit()

    result = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
    )

    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(91)
    manager = await repository.find_by_id(100)
    predecessor = await repository.find_by_id(published.publish_entry_id)
    tombstone = await repository.find_by_id(102)
    preparing_share = await repository.find_by_id(103)
    assert result.action == "final_delete"
    assert document.lifecycle_status == KnowledgeDocumentLifecycleStatus.DELETING.value
    assert document.knowledge_id == 20
    assert manager.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert predecessor.entry_status == KnowledgeFileEntryStatus.INVALID.value
    assert tombstone.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert preparing_share.entry_status == KnowledgeFileEntryStatus.DELETING.value

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match="canonical document has no active manager",
    ):
        await service.share_approved(
            ShareKnowledgeDocumentCommand(
                tenant_id=7,
                approval_instance_id=8002,
                document_id=91,
                source_entry_id=100,
                target_space_id=30,
            )
        )
    assert (
        await repository.find_by_id(103)
    ).entry_status == KnowledgeFileEntryStatus.DELETING.value


@pytest.mark.asyncio
async def test_final_delete_keeps_physical_cleanup_facts_until_worker_finishes(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    service = _service(async_db_session)

    first = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
    )
    second = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
    )

    document = await KnowledgeDocumentRepositoryImpl(
        async_db_session
    ).find_by_id(91)
    manager = await KnowledgeFileRepositoryImpl(
        async_db_session
    ).find_by_id(100)
    versions = await KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    ).find_by_document_id(91)
    assert first.action == "final_delete"
    assert second.idempotent is True
    assert document.lifecycle_status == (
        KnowledgeDocumentLifecycleStatus.DELETING.value
    )
    assert manager.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert manager.object_name == "tenant/7/canonical.pdf"
    assert [version.knowledge_file_id for version in versions] == [100]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retiring_space_id", "expected_document_status", "expected_remote_status"),
    [
        (
            10,
            KnowledgeDocumentLifecycleStatus.DELETING.value,
            KnowledgeFileEntryStatus.INVALID.value,
        ),
        (
            20,
            KnowledgeDocumentLifecycleStatus.ACTIVE.value,
            KnowledgeFileEntryStatus.DELETING.value,
        ),
    ],
)
async def test_space_retirement_invalidates_only_when_manager_space_is_deleted(
    async_db_session: AsyncSession,
    retiring_space_id: int,
    expected_document_status: str,
    expected_remote_status: str,
):
    await _seed_manager(async_db_session)
    async_db_session.add_all(
        [
            KnowledgeFile(
                id=101,
                tenant_id=7,
                knowledge_id=20,
                file_name="canonical.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
                desired_content_generation=3,
                applied_content_generation=3,
            ),
        ]
    )
    await async_db_session.commit()

    result = await KnowledgeSpaceRetirementService(
        session=async_db_session
    ).retire(tenant_id=7, space_id=retiring_space_id)

    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(91)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    remote = await repository.find_by_id(101)
    retired_space = await async_db_session.get(Knowledge, retiring_space_id)
    assert result.idempotent is False
    assert retired_space.state == KnowledgeState.DELETING.value
    assert document.lifecycle_status == expected_document_status
    if retiring_space_id == 10:
        assert manager.entry_status == KnowledgeFileEntryStatus.DELETING.value
    else:
        assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert remote.entry_status == expected_remote_status


@pytest.mark.asyncio
async def test_approved_cannot_create_entry_after_target_space_starts_retiring(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    target = await async_db_session.get(Knowledge, 30)
    target.state = KnowledgeState.DELETING.value
    async_db_session.add(target)
    await async_db_session.commit()

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match="no longer published",
    ):
        await _service(async_db_session).share_approved(
            ShareKnowledgeDocumentCommand(
                tenant_id=7,
                approval_instance_id=8002,
                document_id=91,
                source_entry_id=100,
                target_space_id=30,
            )
        )

    entries = await KnowledgeFileRepositoryImpl(
        async_db_session
    ).find_distribution_entries_by_document_id(91)
    assert [item.id for item in entries] == [100]


@pytest.mark.asyncio
async def test_invalid_projection_cleanup_failure_remains_retryable(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    invalid = KnowledgeFile(
        id=101,
        tenant_id=7,
        knowledge_id=20,
        file_name="canonical.pdf",
        status=KnowledgeFileStatus.SUCCESS.value,
        reference_document_id=91,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        entry_status=KnowledgeFileEntryStatus.INVALID.value,
        projection_status=KnowledgeFileProjectionStatus.PENDING.value,
        desired_entry_generation=2,
        applied_entry_generation=1,
    )
    async_db_session.add(invalid)
    await async_db_session.commit()
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    cleaner = AsyncMock(side_effect=RuntimeError("ES unavailable"))
    finalizer = AsyncMock()
    service = KnowledgeDocumentProjectionService(
        session=async_db_session,
        file_repository=repository,
        document_repository=KnowledgeDocumentRepositoryImpl(async_db_session),
        version_repository=KnowledgeDocumentVersionRepositoryImpl(async_db_session),
        projection_cleaner=cleaner,
        deleting_entry_finalizer=finalizer,
    )
    started = datetime.now()

    with pytest.raises(RuntimeError, match="ES unavailable"):
        await service.process_entry(
            tenant_id=7,
            entry_id=101,
            lease_owner="first",
            now=started,
        )
    failed = await repository.find_by_id(101)
    assert failed.projection_status == KnowledgeFileProjectionStatus.FAILED.value

    cleaner.side_effect = None
    result = await service.process_entry(
        tenant_id=7,
        entry_id=101,
        lease_owner="retry",
        now=started + timedelta(seconds=10),
    )
    assert result.status == "cleaned"
    finalizer.assert_awaited_once()
