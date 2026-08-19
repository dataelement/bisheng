"""Transactional publish lifecycle tests for F059."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTagLink
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
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
    PUBLISH_DUPLICATE_CONTENT_MESSAGE,
    KnowledgeDocumentDistributionError,
    KnowledgeDocumentDistributionService,
    PublishKnowledgeDocumentCommand,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services.permission_service import PermissionService


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
                name="来源空间",
                type=KnowledgeTypeEnum.SPACE.value,
            ),
            Knowledge(
                id=20,
                tenant_id=7,
                name="目标空间",
                type=KnowledgeTypeEnum.SPACE.value,
            ),
            KnowledgeDocument(
                id=91,
                tenant_id=7,
                knowledge_id=10,
                primary_version_id=501,
                content_generation=3,
            ),
            KnowledgeFile(
                id=99,
                tenant_id=7,
                original_uploader_id=501,
                original_knowledge_id=10,
                knowledge_id=10,
                file_name="v1.pdf",
                object_name="tenant/7/v1.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeFile(
                id=100,
                tenant_id=7,
                user_id=501,
                original_uploader_id=501,
                original_knowledge_id=10,
                knowledge_id=10,
                file_name="canonical.pdf",
                object_name="tenant/7/canonical.pdf",
                preview_file_object_name="tenant/7/canonical-preview.pdf",
                file_size=1024,
                md5="abc",
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
                id=500,
                document_id=91,
                knowledge_file_id=99,
                version_no=1,
                is_primary=False,
            ),
            KnowledgeDocumentVersion(
                id=501,
                document_id=91,
                knowledge_file_id=100,
                version_no=2,
                is_primary=True,
            ),
        ]
    )
    await session.commit()


async def _seed_ordinary_file(
    session: AsyncSession,
    *,
    original_uploader_id: int | None = None,
    original_knowledge_id: int | None = None,
) -> None:
    session.add_all(
        [
            Knowledge(
                id=10,
                tenant_id=7,
                name="来源空间",
                type=KnowledgeTypeEnum.SPACE.value,
            ),
            Knowledge(
                id=20,
                tenant_id=7,
                name="目标空间",
                type=KnowledgeTypeEnum.SPACE.value,
            ),
            KnowledgeFile(
                id=100,
                tenant_id=7,
                user_id=501,
                original_uploader_id=original_uploader_id,
                original_knowledge_id=original_knowledge_id,
                knowledge_id=10,
                file_name="ordinary.pdf",
                object_name="tenant/7/ordinary.pdf",
                file_size=1024,
                md5="ordinary-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
                file_level_path="/8",
                level=2,
            ),
        ]
    )
    await session.commit()


def _command() -> PublishKnowledgeDocumentCommand:
    return PublishKnowledgeDocumentCommand(
        tenant_id=7,
        approval_instance_id=7001,
        document_id=91,
        source_entry_id=100,
        target_space_id=20,
        target_file_level_path="/88",
        target_level=2,
    )


@pytest.mark.asyncio
async def test_initial_upload_permission_initialization_keeps_parent_and_uploader_owner():
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=501)

    with patch.object(
        service,
        '_write_resource_parent_tuple',
        new_callable=AsyncMock,
    ) as write_parent, patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
        new_callable=AsyncMock,
    ) as write_owner:
        await service._initialize_child_resource_permissions(
            object_type='knowledge_file',
            object_id=100,
            parent_type='knowledge_space',
            parent_id=10,
        )

    write_parent.assert_awaited_once_with(
        'knowledge_file',
        100,
        'knowledge_space',
        10,
    )
    write_owner.assert_awaited_once_with(
        501,
        'knowledge_file',
        '100',
        enforce_fga_success=True,
    )


@pytest.mark.asyncio
async def test_publish_submission_identity_keeps_source_as_ordinary_file(
    async_db_session: AsyncSession,
):
    await _seed_ordinary_file(async_db_session)
    service = _service(async_db_session)

    identity = await service.ensure_document_identity(
        tenant_id=7,
        source_file_id=100,
    )

    file_repository = KnowledgeFileRepositoryImpl(async_db_session)
    version_repository = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    source = await file_repository.find_by_id(100)
    version = await version_repository.find_by_knowledge_file_id(100)
    assert identity.document_id == version.document_id
    assert identity.manager_file_id == 100
    assert source.reference_document_id is None
    assert source.entry_type is None
    assert source.entry_status is None
    assert source.original_uploader_id == 501
    assert source.original_knowledge_id == 10


@pytest.mark.asyncio
async def test_document_identity_does_not_overwrite_existing_original_origin(
    async_db_session: AsyncSession,
):
    await _seed_ordinary_file(
        async_db_session,
        original_uploader_id=401,
        original_knowledge_id=5,
    )

    await _service(async_db_session).ensure_document_identity(
        tenant_id=7,
        source_file_id=100,
    )

    source = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(100)
    assert source.original_uploader_id == 401
    assert source.original_knowledge_id == 5


@pytest.mark.asyncio
async def test_publish_approved_activates_expected_identity_before_transfer(
    async_db_session: AsyncSession,
):
    await _seed_ordinary_file(async_db_session)
    service = _service(async_db_session)
    identity = await service.ensure_document_identity(
        tenant_id=7,
        source_file_id=100,
    )

    activated = await service.normalize_manager(
        tenant_id=7,
        source_file_id=100,
        expected_document_id=identity.document_id,
    )
    result = await service.publish_approved(
        PublishKnowledgeDocumentCommand(
            tenant_id=7,
            approval_instance_id=7001,
            document_id=identity.document_id,
            source_entry_id=100,
            target_space_id=20,
        )
    )

    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    publish = await repository.find_by_id(result.publish_entry_id)
    assert activated.document_id == identity.document_id
    assert manager.knowledge_id == 20
    assert manager.entry_type == KnowledgeFileEntryType.MANAGER.value
    assert publish.knowledge_id == 10
    assert publish.entry_type == KnowledgeFileEntryType.PUBLISH.value
    assert manager.original_uploader_id == 501
    assert manager.original_knowledge_id == 10
    assert publish.original_uploader_id == 501
    assert publish.original_knowledge_id == 10


@pytest.mark.asyncio
async def test_manager_activation_rejects_stale_document_identity(
    async_db_session: AsyncSession,
):
    await _seed_ordinary_file(async_db_session)
    service = _service(async_db_session)
    identity = await service.ensure_document_identity(
        tenant_id=7,
        source_file_id=100,
    )

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match="canonical document has changed",
    ):
        await service.normalize_manager(
            tenant_id=7,
            source_file_id=100,
            expected_document_id=identity.document_id + 1,
        )

    source = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(100)
    assert source.reference_document_id is None
    assert source.entry_type is None
    assert source.entry_status is None


@pytest.mark.asyncio
async def test_unapproved_legacy_manager_cleanup_is_safe_and_idempotent(
    async_db_session: AsyncSession,
):
    await _seed_ordinary_file(async_db_session)
    service = _service(async_db_session)
    identity = await service.normalize_manager(
        tenant_id=7,
        source_file_id=100,
    )

    cleaned = await service.restore_unapproved_manager(
        tenant_id=7,
        document_id=identity.document_id,
        source_file_id=100,
    )
    repeated = await service.restore_unapproved_manager(
        tenant_id=7,
        document_id=identity.document_id,
        source_file_id=100,
    )

    source = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(100)
    version = await KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    ).find_by_knowledge_file_id(100)
    assert cleaned is True
    assert repeated is False
    assert source.reference_document_id is None
    assert source.entry_type is None
    assert source.entry_status is None
    assert version.document_id == identity.document_id


@pytest.mark.asyncio
async def test_unapproved_cleanup_does_not_demote_distributed_manager(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    async_db_session.add(
        KnowledgeFile(
            id=101,
            tenant_id=7,
            knowledge_id=30,
            file_name="canonical.pdf",
            status=KnowledgeFileStatus.SUCCESS.value,
            reference_document_id=91,
            entry_type=KnowledgeFileEntryType.SHARE.value,
            entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
        )
    )
    await async_db_session.commit()

    cleaned = await _service(async_db_session).restore_unapproved_manager(
        tenant_id=7,
        document_id=91,
        source_file_id=100,
    )

    manager = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(100)
    assert cleaned is False
    assert manager.entry_type == KnowledgeFileEntryType.MANAGER.value
    assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_publish_moves_manager_and_creates_payload_free_source_entry(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    tuple_writer = AsyncMock()
    service = _service(async_db_session, tuple_writer=tuple_writer)

    result = await service.publish_approved(_command())

    assert result.manager_file_id == 100
    assert result.publish_entry_id != 100
    assert result.idempotent is False

    file_repository = KnowledgeFileRepositoryImpl(async_db_session)
    document_repository = KnowledgeDocumentRepositoryImpl(async_db_session)
    version_repository = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    manager = await file_repository.find_by_id(100)
    publish = await file_repository.find_by_id(result.publish_entry_id)
    document = await document_repository.find_by_id(91)
    versions = await version_repository.find_by_document_id(91)
    physical_files = [
        await file_repository.find_by_id(version.knowledge_file_id)
        for version in versions
    ]

    assert manager.knowledge_id == 20
    assert manager.file_level_path == "/88"
    assert manager.object_name == "tenant/7/canonical.pdf"
    assert manager.projection_previous_file_id == publish.id
    assert publish.knowledge_id == 10
    assert manager.original_uploader_id == 501
    assert manager.original_knowledge_id == 10
    assert publish.original_uploader_id == 501
    assert publish.original_knowledge_id == 10
    assert publish.file_level_path == "/8"
    assert publish.entry_type == KnowledgeFileEntryType.PUBLISH.value
    assert publish.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert publish.object_name is None
    assert publish.preview_file_object_name is None
    assert publish.file_size == 0
    assert publish.md5 is None
    assert publish.approval_instance_id == 7001
    assert document.knowledge_id == 20
    assert document.predecessor_logic_file_id == publish.id
    assert document.content_generation == 4
    assert {file.knowledge_id for file in physical_files} == {20}
    assert len(versions) == 2
    assert tuple_writer.await_count == 2


@pytest.mark.asyncio
async def test_publish_owner_fallback_follows_target_knowledge_creator(
    async_db_session: AsyncSession,
    mock_openfga,
):
    await _seed_manager(async_db_session)
    source_space = await async_db_session.get(Knowledge, 10)
    target_space = await async_db_session.get(Knowledge, 20)
    source_space.user_id = 501
    target_space.user_id = 602
    async_db_session.add_all([source_space, target_space])
    await async_db_session.commit()

    tuple_writer = AsyncMock()
    permission_snapshot_loader = AsyncMock(return_value=[
        TupleOperation(
            action='write',
            user='user:501',
            relation='owner',
            object='knowledge_file:100',
        ),
    ])
    result = await _service(
        async_db_session,
        tuple_writer=tuple_writer,
        permission_snapshot_loader=permission_snapshot_loader,
    ).publish_approved(_command())

    manager = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(100)
    assert manager.user_id == 501
    assert manager.knowledge_id == 20

    prewrite_operations = tuple_writer.await_args_list[0].args[0]
    cleanup_operations = tuple_writer.await_args_list[1].args[0]
    assert TupleOperation(
        action='write',
        user='folder:88',
        relation='parent',
        object='knowledge_file:100',
    ) in prewrite_operations
    assert TupleOperation(
        action='write',
        user='user:501',
        relation='owner',
        object=f'knowledge_file:{result.publish_entry_id}',
    ) in prewrite_operations
    assert TupleOperation(
        action='delete',
        user='user:501',
        relation='owner',
        object='knowledge_file:100',
    ) in cleanup_operations

    async def load_files(file_ids):
        repository = KnowledgeFileRepositoryImpl(async_db_session)
        return [
            file_record
            for file_id in file_ids
            if (file_record := await repository.find_by_id(int(file_id))) is not None
        ]

    async def load_knowledge(knowledge_id):
        return await async_db_session.get(Knowledge, int(knowledge_id))

    with patch.object(
        KnowledgeFileDao,
        'aget_file_by_ids',
        new_callable=AsyncMock,
        side_effect=load_files,
    ), patch.object(
        KnowledgeDao,
        'aquery_by_id',
        new_callable=AsyncMock,
        side_effect=load_knowledge,
    ), patch.object(
        PermissionService,
        '_get_fga',
        return_value=mock_openfga,
    ), patch(
        'bisheng.permission.domain.services.permission_cache.PermissionCache.get_check',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.permission.domain.services.permission_cache.PermissionCache.set_check',
        new_callable=AsyncMock,
    ):
        uploader_allowed = await PermissionService.check(
            user_id=501,
            relation='can_delete',
            object_type='knowledge_file',
            object_id='100',
        )
        target_creator_allowed = await PermissionService.check(
            user_id=602,
            relation='can_delete',
            object_type='knowledge_file',
            object_id='100',
        )

    assert uploader_allowed is False
    assert target_creator_allowed is True


@pytest.mark.asyncio
async def test_permission_prewrite_failure_keeps_old_manager_and_hidden_preparing_entry(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    tuple_writer = AsyncMock(side_effect=RuntimeError("FGA down"))
    service = _service(async_db_session, tuple_writer=tuple_writer)

    with pytest.raises(KnowledgeDocumentDistributionError, match="prewrite"):
        await service.publish_approved(_command())

    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    entries = await repository.find_distribution_entries_by_document_id(91)

    assert manager.knowledge_id == 10
    assert manager.entry_type == KnowledgeFileEntryType.MANAGER.value
    assert manager.entry_status == (
        KnowledgeFileEntryStatus.PREPARING.value
    )
    preparing = [
        entry
        for entry in entries
        if entry.approval_instance_id == 7001
        and entry.entry_type == KnowledgeFileEntryType.PUBLISH.value
    ]
    assert len(preparing) == 1
    assert preparing[0].entry_status == KnowledgeFileEntryStatus.PREPARING.value


@pytest.mark.asyncio
async def test_repeated_approved_callback_is_idempotent(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    tuple_writer = AsyncMock()
    service = _service(async_db_session, tuple_writer=tuple_writer)

    first = await service.publish_approved(_command())
    second = await service.publish_approved(_command())

    assert second.publish_entry_id == first.publish_entry_id
    assert second.manager_file_id == first.manager_file_id
    assert second.idempotent is True
    assert tuple_writer.await_count == 2


@pytest.mark.asyncio
async def test_publish_rejects_non_manager_source(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    source = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(100)
    source.entry_type = KnowledgeFileEntryType.SHARE.value
    async_db_session.add(source)
    await async_db_session.commit()

    with pytest.raises(KnowledgeDocumentDistributionError, match="manager"):
        await _service(async_db_session).publish_approved(_command())


@pytest.mark.asyncio
async def test_publish_approved_rejects_duplicate_content_before_preparing(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    async_db_session.add(
        KnowledgeFile(
            id=300,
            tenant_id=7,
            knowledge_id=20,
            file_name="已存在.pdf",
            md5="abc",
            status=KnowledgeFileStatus.SUCCESS.value,
        )
    )
    await async_db_session.commit()
    tuple_writer = AsyncMock()

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match=PUBLISH_DUPLICATE_CONTENT_MESSAGE,
    ):
        await _service(
            async_db_session,
            tuple_writer=tuple_writer,
        ).publish_approved(_command())

    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    entries = await repository.find_distribution_entries_by_document_id(91)
    assert manager.knowledge_id == 10
    assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert [entry.entry_type for entry in entries] == [
        KnowledgeFileEntryType.MANAGER.value
    ]
    tuple_writer.assert_not_awaited()


@pytest.mark.parametrize("source_md5", [None, "different-md5"])
@pytest.mark.asyncio
async def test_publish_allows_missing_md5_or_same_name_with_different_content(
    async_db_session: AsyncSession,
    source_md5: str | None,
):
    await _seed_manager(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    manager.md5 = source_md5
    async_db_session.add(manager)
    async_db_session.add(
        KnowledgeFile(
            id=300,
            tenant_id=7,
            knowledge_id=20,
            file_name="canonical.pdf",
            md5="abc",
            status=KnowledgeFileStatus.SUCCESS.value,
        )
    )
    await async_db_session.commit()

    result = await _service(async_db_session).publish_approved(_command())

    assert result.target_space_id == 20
    assert (await repository.find_by_id(100)).knowledge_id == 20


@pytest.mark.asyncio
async def test_publish_late_duplicate_conflict_restores_visible_source_state(
    async_db_session: AsyncSession,
    monkeypatch,
):
    await _seed_manager(async_db_session)
    tuple_writer = AsyncMock()
    service = _service(async_db_session, tuple_writer=tuple_writer)
    duplicate_checks = AsyncMock(
        side_effect=[
            None,
            KnowledgeDocumentDistributionError(
                PUBLISH_DUPLICATE_CONTENT_MESSAGE
            ),
        ]
    )
    monkeypatch.setattr(
        service,
        "_ensure_publish_target_content_not_duplicate",
        duplicate_checks,
        raising=False,
    )

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match=PUBLISH_DUPLICATE_CONTENT_MESSAGE,
    ):
        await service.publish_approved(_command())

    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    entries = await repository.find_distribution_entries_by_document_id(91)
    assert manager.knowledge_id == 10
    assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert manager.approval_instance_id is None
    assert [entry.entry_type for entry in entries] == [
        KnowledgeFileEntryType.MANAGER.value
    ]
    assert duplicate_checks.await_count == 2
    assert duplicate_checks.await_args_list[1].kwargs == {
        "lock_target_space": True,
        "source_md5": "abc",
    }
    assert tuple_writer.await_count == 2
    cleanup_operations = tuple_writer.await_args_list[1].args[0]
    assert cleanup_operations
    assert {operation.action for operation in cleanup_operations} == {"delete"}


@pytest.mark.asyncio
async def test_switch_primary_moves_manager_identity_without_changing_logical_entries(
    async_db_session: AsyncSession,
):
    connection = await async_db_session.connection()
    await connection.run_sync(
        lambda sync_connection: TagLink.__table__.create(
            sync_connection,
            checkfirst=True,
        )
    )
    await connection.run_sync(
        lambda sync_connection: ReviewTagLink.__table__.create(
            sync_connection,
            checkfirst=True,
        )
    )
    await _seed_manager(async_db_session)
    resource_type = ResourceTypeEnum.SPACE_FILE.value
    async_db_session.add_all(
        [
            KnowledgeFile(
                id=101,
                tenant_id=7,
                knowledge_id=30,
                file_name="canonical.pdf",
                file_type=1,
                status=KnowledgeFileStatus.SUCCESS.value,
                file_level_path="/30",
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                desired_content_generation=3,
                applied_content_generation=3,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
            ),
            KnowledgeFile(
                id=102,
                tenant_id=7,
                knowledge_id=40,
                file_name="canonical.pdf",
                file_type=1,
                status=KnowledgeFileStatus.SUCCESS.value,
                file_level_path="/40",
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                allow_download=True,
                desired_content_generation=3,
                applied_content_generation=3,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
            ),
            TagLink(
                tag_id=701,
                resource_id="100",
                resource_type=resource_type,
                user_id=11,
                tenant_id=7,
            ),
            TagLink(
                tag_id=799,
                resource_id="99",
                resource_type=resource_type,
                user_id=12,
                tenant_id=7,
            ),
            ReviewTagLink(
                tag_id=801,
                resource_id="100",
                resource_type=resource_type,
                user_id=11,
                tenant_id=7,
                remark="source review tag",
            ),
            ReviewTagLink(
                tag_id=899,
                resource_id="99",
                resource_type=resource_type,
                user_id=12,
                tenant_id=7,
                remark="stale target tag",
            ),
        ]
    )
    await async_db_session.commit()
    tuple_writer = AsyncMock()
    permission_snapshot_loader = AsyncMock(
        return_value=[
            TupleOperation(
                action="write",
                user="user:11",
                relation="editor",
                object="knowledge_file:100",
            )
        ]
    )
    service = _service(
        async_db_session,
        tuple_writer=tuple_writer,
        permission_snapshot_loader=permission_snapshot_loader,
    )

    result = await service.switch_primary_manager(
        tenant_id=7,
        document_id=91,
        current_manager_file_id=100,
        target_version_id=500,
    )

    file_repository = KnowledgeFileRepositoryImpl(async_db_session)
    version_repository = KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    )
    document_repository = KnowledgeDocumentRepositoryImpl(async_db_session)
    old_manager = await file_repository.find_by_id(100)
    new_manager = await file_repository.find_by_id(99)
    publish = await file_repository.find_by_id(101)
    share = await file_repository.find_by_id(102)
    document = await document_repository.find_by_id(91)
    versions = await version_repository.find_by_document_id(91)
    target_tag_links = list(
        (
            await async_db_session.execute(
                select(TagLink).where(
                    TagLink.resource_id == "99",
                    TagLink.resource_type == resource_type,
                )
            )
        )
        .scalars()
        .all()
    )
    target_review_tag_links = list(
        (
            await async_db_session.execute(
                select(ReviewTagLink).where(
                    ReviewTagLink.resource_id == "99",
                    ReviewTagLink.resource_type == resource_type,
                )
            )
        )
        .scalars()
        .all()
    )

    assert result.manager_file_id == 99
    assert result.previous_manager_file_id == 100
    assert document.primary_version_id == 500
    assert document.content_generation == 4
    assert [(item.id, item.is_primary) for item in versions] == [
        (500, True),
        (501, False),
    ]
    assert new_manager.entry_type == KnowledgeFileEntryType.MANAGER.value
    assert new_manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert new_manager.reference_document_id == 91
    assert new_manager.file_level_path == "/8"
    assert new_manager.projection_previous_file_id == 100
    assert new_manager.file_name == "v1.pdf"
    assert old_manager.entry_type is None
    assert old_manager.entry_status is None
    assert old_manager.reference_document_id is None
    assert publish.id == 101
    assert publish.file_level_path == "/30"
    assert publish.file_name == "v1.pdf"
    assert share.id == 102
    assert share.file_level_path == "/40"
    assert share.file_name == "v1.pdf"
    assert share.allow_download is True
    assert {
        new_manager.desired_content_generation,
        publish.desired_content_generation,
        share.desired_content_generation,
    } == {4}
    assert [item.tag_id for item in target_tag_links] == [701]
    assert [item.tag_id for item in target_review_tag_links] == [801]
    assert target_review_tag_links[0].remark == "source review tag"
    assert tuple_writer.await_count == 2


@pytest.mark.asyncio
async def test_switch_primary_rejects_name_conflict_before_permission_prewrite(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    async_db_session.add(
        KnowledgeFile(
            id=110,
            tenant_id=7,
            knowledge_id=10,
            file_name="v1.pdf",
            file_type=1,
            status=KnowledgeFileStatus.SUCCESS.value,
            file_level_path="/8",
        )
    )
    await async_db_session.commit()
    tuple_writer = AsyncMock()
    service = _service(async_db_session, tuple_writer=tuple_writer)

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match="name conflict",
    ):
        await service.switch_primary_manager(
            tenant_id=7,
            document_id=91,
            current_manager_file_id=100,
            target_version_id=500,
        )

    document = await KnowledgeDocumentRepositoryImpl(
        async_db_session
    ).find_by_id(91)
    assert document.primary_version_id == 501
    tuple_writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_merge_migrates_existing_version_row_without_copy(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    source_versions = await KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    ).find_by_document_id(91)
    await async_db_session.delete(source_versions[0])
    await async_db_session.commit()
    async_db_session.add_all(
        [
            KnowledgeDocument(
                id=92,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=601,
                content_generation=2,
            ),
            KnowledgeFile(
                id=200,
                tenant_id=7,
                knowledge_id=20,
                file_name="target-v1.pdf",
                object_name="tenant/7/target-v1.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeDocumentVersion(
                id=601,
                document_id=92,
                knowledge_file_id=200,
                version_no=1,
                is_primary=True,
            ),
        ]
    )
    await async_db_session.commit()
    command = PublishKnowledgeDocumentCommand(
        tenant_id=7,
        approval_instance_id=7002,
        document_id=91,
        source_entry_id=100,
        target_space_id=20,
        target_file_level_path="/88",
        target_level=2,
        target_document_id=92,
    )
    service = _service(async_db_session)

    first = await service.publish_approved(command)
    second = await service.publish_approved(command)

    document_repository = KnowledgeDocumentRepositoryImpl(async_db_session)
    file_repository = KnowledgeFileRepositoryImpl(async_db_session)
    version_repository = KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    )
    source_document = await document_repository.find_by_id(91)
    target_document = await document_repository.find_by_id(92)
    versions = await version_repository.find_by_document_id(92)
    manager = await file_repository.find_by_id(100)
    old_target = await file_repository.find_by_id(200)
    publish = await file_repository.find_by_id(first.publish_entry_id)

    assert source_document is None
    assert target_document.primary_version_id == 501
    assert target_document.predecessor_logic_file_id == publish.id
    assert [(item.knowledge_file_id, item.version_no, item.is_primary) for item in versions] == [
        (200, 1, False),
        (100, 2, True),
    ]
    assert manager.reference_document_id == 92
    assert manager.entry_type == KnowledgeFileEntryType.MANAGER.value
    assert manager.knowledge_id == 20
    assert manager.object_name == "tenant/7/canonical.pdf"
    assert old_target.reference_document_id is None
    assert old_target.entry_type is None
    assert old_target.object_name == "tenant/7/target-v1.pdf"
    assert publish.reference_document_id == 92
    assert publish.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert first.document_id == 92
    assert second.document_id == 92
    assert second.idempotent is True


@pytest.mark.asyncio
async def test_publish_merge_rejects_distributed_target(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    source_versions = await KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    ).find_by_document_id(91)
    await async_db_session.delete(source_versions[0])
    await async_db_session.commit()
    async_db_session.add_all(
        [
            KnowledgeDocument(
                id=92,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=601,
            ),
            KnowledgeFile(
                id=200,
                tenant_id=7,
                knowledge_id=20,
                file_name="target-v1.pdf",
                object_name="tenant/7/target-v1.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=92,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
            ),
            KnowledgeFile(
                id=201,
                tenant_id=7,
                knowledge_id=30,
                file_name="target-v1.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=92,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
            ),
            KnowledgeDocumentVersion(
                id=601,
                document_id=92,
                knowledge_file_id=200,
                version_no=1,
                is_primary=True,
            ),
        ]
    )
    await async_db_session.commit()

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match="distributed target",
    ):
        await _service(async_db_session).publish_approved(
            PublishKnowledgeDocumentCommand(
                tenant_id=7,
                approval_instance_id=7002,
                document_id=91,
                source_entry_id=100,
                target_space_id=20,
                target_document_id=92,
            )
        )


@pytest.mark.asyncio
async def test_publish_merge_rejects_duplicate_current_target_content(
    async_db_session: AsyncSession,
):
    await _seed_manager(async_db_session)
    source_versions = await KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    ).find_by_document_id(91)
    await async_db_session.delete(source_versions[0])
    async_db_session.add_all(
        [
            KnowledgeDocument(
                id=92,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=601,
            ),
            KnowledgeFile(
                id=200,
                tenant_id=7,
                knowledge_id=20,
                file_name="target-v1.pdf",
                object_name="tenant/7/target-v1.pdf",
                md5="abc",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeDocumentVersion(
                id=601,
                document_id=92,
                knowledge_file_id=200,
                version_no=1,
                is_primary=True,
            ),
        ]
    )
    await async_db_session.commit()

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match=PUBLISH_DUPLICATE_CONTENT_MESSAGE,
    ):
        await _service(async_db_session).publish_approved(
            PublishKnowledgeDocumentCommand(
                tenant_id=7,
                approval_instance_id=7002,
                document_id=91,
                source_entry_id=100,
                target_space_id=20,
                target_document_id=92,
            )
        )

    assert (
        await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(91)
    ) is not None
    source_version = await KnowledgeDocumentVersionRepositoryImpl(
        async_db_session
    ).find_by_knowledge_file_id(100)
    assert source_version.document_id == 91
