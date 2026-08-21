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
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation


def _service(
    session: AsyncSession,
    *,
    tuple_writer=AsyncMock(),
    permission_snapshot_loader=AsyncMock(return_value=[]),
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
        permission_snapshot_loader=permission_snapshot_loader,
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
            Knowledge(
                id=40,
                tenant_id=7,
                name="二次发布目标库",
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


async def _publish_to_department_then_public(
    service: KnowledgeDocumentDistributionService,
):
    first = await service.publish_approved(
        _publish_command(
            approval_instance_id=7001,
            source_space=10,
            target_space=20,
            target_path="/18",
        )
    )
    second = await service.publish_approved(
        _publish_command(
            approval_instance_id=7002,
            source_space=20,
            target_space=40,
            target_path="/28",
        )
    )
    return first, second


@pytest.mark.asyncio
async def test_delete_manager_rolls_back_to_publish_predecessor_and_keeps_share_active(
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
    tuple_writer = AsyncMock()

    async def permission_snapshot_loader(file_id: int):
        if file_id == 100:
            users = ["user:shared", "user:old-manager"]
        elif file_id == published.publish_entry_id:
            users = ["user:shared", "user:restored-manager"]
        else:
            users = []
        return [
            TupleOperation(
                action="write",
                user=user,
                relation="viewer",
                object=f"knowledge_file:{file_id}",
            )
            for user in users
        ]

    service.permission_snapshot_loader = permission_snapshot_loader
    service.permission_activation_service.tuple_writer = tuple_writer
    assert (
        await service.preflight_delete_entry(
            tenant_id=7,
            document_id=91,
            entry_id=100,
        )
        == "rollback"
    )

    first = await service.delete_manager(
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
    versions = await KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    ).find_by_document_id(91)
    assert first.action == "rollback"
    assert document.lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value
    assert document.knowledge_id == 10
    assert document.predecessor_logic_file_id is None
    assert manager.knowledge_id == 10
    assert manager.object_name == "tenant/7/canonical.pdf"
    assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert [version.knowledge_file_id for version in versions] == [100]
    assert predecessor.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert share.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert predecessor.projection_status == KnowledgeFileProjectionStatus.PENDING.value
    cleanup_operations = tuple_writer.await_args_list[-1].args[0]
    assert any(
        operation.action == "delete"
        and operation.user == "user:old-manager"
        and operation.relation == "viewer"
        and operation.object == "knowledge_file:100"
        for operation in cleanup_operations
    )
    assert not any(
        operation.action == "delete"
        and operation.user == "user:shared"
        and operation.relation == "viewer"
        and operation.object == "knowledge_file:100"
        for operation in cleanup_operations
    )


@pytest.mark.asyncio
async def test_multi_hop_manager_delete_rolls_back_one_level_and_preserves_identity(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    service = _service(async_db_session)
    first_publish, second_publish = await _publish_to_department_then_public(service)
    shared = await service.share_approved(
        ShareKnowledgeDocumentCommand(
            tenant_id=7,
            approval_instance_id=8001,
            document_id=91,
            source_entry_id=100,
            target_space_id=30,
        )
    )

    result = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
    )

    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(91)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    first_entry = await repository.find_by_id(first_publish.publish_entry_id)
    second_entry = await repository.find_by_id(second_publish.publish_entry_id)
    share = await repository.find_by_id(shared.share_entry_id)
    versions = await KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    ).find_by_document_id(91)
    assert result.action == "rollback"
    assert document.knowledge_id == 20
    assert document.predecessor_logic_file_id == first_publish.publish_entry_id
    assert manager.id == 100
    assert manager.knowledge_id == 20
    assert manager.object_name == "tenant/7/canonical.pdf"
    assert [version.knowledge_file_id for version in versions] == [100]
    assert first_entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert second_entry.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert share.entry_status == KnowledgeFileEntryStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_delete_publish_entry_rewires_chain_and_manager_delete_skips_it(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    service = _service(async_db_session)
    first_publish, second_publish = await _publish_to_department_then_public(service)

    removed = await service.remove_publish_entry(
        tenant_id=7,
        document_id=91,
        publish_entry_id=second_publish.publish_entry_id,
    )
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    after_entry_delete_document = await KnowledgeDocumentRepositoryImpl(
        async_db_session
    ).find_by_id(91)
    after_entry_delete_manager = await repository.find_by_id(100)
    deleted_publish = await repository.find_by_id(second_publish.publish_entry_id)
    assert after_entry_delete_document.knowledge_id == 40
    assert (
        after_entry_delete_document.predecessor_logic_file_id
        == first_publish.publish_entry_id
    )
    assert after_entry_delete_manager.knowledge_id == 40
    assert after_entry_delete_manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert deleted_publish.entry_status == KnowledgeFileEntryStatus.DELETING.value

    result = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
    )

    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(91)
    manager = await repository.find_by_id(100)
    deleted_publish = await repository.find_by_id(second_publish.publish_entry_id)
    restored_publish = await repository.find_by_id(first_publish.publish_entry_id)
    assert removed.idempotent is False
    assert result.action == "rollback"
    assert document.knowledge_id == 10
    assert document.predecessor_logic_file_id is None
    assert manager.knowledge_id == 10
    assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert deleted_publish.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert restored_publish.entry_status == KnowledgeFileEntryStatus.DELETING.value


@pytest.mark.asyncio
async def test_delete_all_publish_entries_then_manager_uses_final_delete(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    service = _service(async_db_session)
    first_publish, second_publish = await _publish_to_department_then_public(service)
    shared = await service.share_approved(
        ShareKnowledgeDocumentCommand(
            tenant_id=7,
            approval_instance_id=8001,
            document_id=91,
            source_entry_id=100,
            target_space_id=30,
        )
    )
    for entry_id in (
        second_publish.publish_entry_id,
        first_publish.publish_entry_id,
    ):
        await service.remove_publish_entry(
            tenant_id=7,
            document_id=91,
            publish_entry_id=entry_id,
        )

    result = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
    )

    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(91)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    share = await repository.find_by_id(shared.share_entry_id)
    assert result.action == "final_delete"
    assert document.lifecycle_status == KnowledgeDocumentLifecycleStatus.DELETING.value
    assert document.predecessor_logic_file_id is None
    assert manager.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert share.entry_status == KnowledgeFileEntryStatus.INVALID.value


@pytest.mark.asyncio
async def test_manager_delete_fails_closed_when_publish_chain_contains_cycle(
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
    publish = await repository.find_by_id(published.publish_entry_id)
    publish.predecessor_logic_file_id = int(publish.id)
    async_db_session.add(publish)
    await async_db_session.commit()

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match="contains a cycle",
    ):
        await service.delete_manager(
            tenant_id=7,
            document_id=91,
            manager_file_id=100,
        )

    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(91)
    manager = await repository.find_by_id(100)
    assert document.lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value
    assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_manager_rollback_revalidates_candidate_after_concurrent_publish_delete(
    async_db_session: AsyncSession,
):
    armed = False
    tuple_writer = AsyncMock()
    service: KnowledgeDocumentDistributionService

    async def permission_snapshot_loader(file_id: int):
        nonlocal armed
        if armed:
            armed = False
            await service.remove_publish_entry(
                tenant_id=7,
                document_id=91,
                publish_entry_id=file_id,
            )
        return []

    await _seed_manager(async_db_session)
    service = _service(
        async_db_session,
        tuple_writer=tuple_writer,
        permission_snapshot_loader=permission_snapshot_loader,
    )
    first_publish, second_publish = await _publish_to_department_then_public(service)
    tuple_writer.reset_mock()
    armed = True

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match="rollback state changed concurrently",
    ):
        await service.delete_manager(
            tenant_id=7,
            document_id=91,
            manager_file_id=100,
        )

    manager_permission_calls = [
        call.args[0]
        for call in tuple_writer.await_args_list
        if call.args[0]
        and all(operation.object == "knowledge_file:100" for operation in call.args[0])
    ]
    assert len(manager_permission_calls) == 2
    assert {operation.action for operation in manager_permission_calls[0]} == {"write"}
    assert {operation.action for operation in manager_permission_calls[1]} == {"delete"}
    assert {
        (operation.user, operation.relation, operation.object)
        for operation in manager_permission_calls[0]
    } == {
        (operation.user, operation.relation, operation.object)
        for operation in manager_permission_calls[1]
    }

    resumed = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
    )
    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(91)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    first_entry = await repository.find_by_id(first_publish.publish_entry_id)
    second_entry = await repository.find_by_id(second_publish.publish_entry_id)
    assert resumed.action == "rollback"
    assert document.knowledge_id == 10
    assert document.predecessor_logic_file_id is None
    assert manager.knowledge_id == 10
    assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert first_entry.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert second_entry.entry_status == KnowledgeFileEntryStatus.DELETING.value


@pytest.mark.asyncio
async def test_delete_manager_resumes_preparing_rollback_state(
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
    assert result.action == "rollback"
    assert document.lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value
    assert document.knowledge_id == 10
    assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert predecessor.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert tombstone.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert preparing_share.entry_status == KnowledgeFileEntryStatus.PREPARING.value


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
