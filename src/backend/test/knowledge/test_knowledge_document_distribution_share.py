"""Share lifecycle tests for the F059 canonical document model."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
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
    ShareKnowledgeDocumentCommand,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
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


async def _seed_document(
    session: AsyncSession,
    *,
    source_type: str = KnowledgeFileEntryType.MANAGER.value,
) -> None:
    session.add_all(
        [
            *[
                Knowledge(
                    id=knowledge_id,
                    tenant_id=7,
                    name=f"空间{knowledge_id}",
                    type=KnowledgeTypeEnum.SPACE.value,
                )
                for knowledge_id in (10, 20, 30, 40)
            ],
            KnowledgeDocument(
                id=91,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=501,
                content_generation=4,
            ),
            KnowledgeFile(
                id=100,
                tenant_id=7,
                original_uploader_id=501,
                original_knowledge_id=10,
                knowledge_id=20,
                file_name="canonical.pdf",
                object_name="tenant/7/canonical.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
                desired_content_generation=4,
                applied_content_generation=4,
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
    if source_type == KnowledgeFileEntryType.PUBLISH.value:
        session.add(
            KnowledgeFile(
                id=101,
                tenant_id=7,
                original_uploader_id=501,
                original_knowledge_id=10,
                knowledge_id=10,
                file_name="canonical.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
                desired_content_generation=4,
                applied_content_generation=4,
            )
        )
    await session.commit()


def _command(
    *,
    source_entry_id: int = 100,
    target_file_level_path: str = "",
    target_level: int = 0,
) -> ShareKnowledgeDocumentCommand:
    return ShareKnowledgeDocumentCommand(
        tenant_id=7,
        approval_instance_id=8001,
        document_id=91,
        source_entry_id=source_entry_id,
        target_space_id=30,
        allow_download=True,
        target_file_level_path=target_file_level_path,
        target_level=target_level,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_type", "source_entry_id"),
    [
        (KnowledgeFileEntryType.MANAGER.value, 100),
        (KnowledgeFileEntryType.PUBLISH.value, 101),
    ],
)
async def test_share_creates_payload_free_active_entry_without_moving_manager(
    async_db_session: AsyncSession,
    source_type: str,
    source_entry_id: int,
):
    await _seed_document(async_db_session, source_type=source_type)
    service = _service(async_db_session)

    result = await service.share_approved(_command(source_entry_id=source_entry_id))

    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    share = await repository.find_by_id(result.share_entry_id)
    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(91)

    assert manager.knowledge_id == 20
    assert manager.object_name == "tenant/7/canonical.pdf"
    assert document.knowledge_id == 20
    assert share.knowledge_id == 30
    assert share.entry_type == KnowledgeFileEntryType.SHARE.value
    assert share.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert share.share_source_file_id == source_entry_id
    assert share.allow_download is True
    assert share.object_name is None
    assert share.preview_file_object_name is None
    assert share.file_size == 0
    assert share.desired_content_generation == 4
    assert share.original_uploader_id == 501
    assert share.original_knowledge_id == 10


def test_share_entry_uses_selected_target_folder():
    share = KnowledgeDocumentDistributionService._create_share_entry(
        source_entry=KnowledgeFile(
            id=100,
            tenant_id=7,
            knowledge_id=20,
            file_name="canonical.pdf",
            status=KnowledgeFileStatus.SUCCESS.value,
        ),
        document=KnowledgeDocument(
            id=91,
            tenant_id=7,
            knowledge_id=20,
            content_generation=4,
        ),
        command=_command(
            target_file_level_path="/300/301",
            target_level=2,
        ),
    )

    assert share.file_level_path == "/300/301"
    assert share.level == 2


@pytest.mark.asyncio
async def test_share_permission_failure_leaves_hidden_preparing_entry(
    async_db_session: AsyncSession,
):
    await _seed_document(async_db_session)
    service = _service(
        async_db_session,
        tuple_writer=AsyncMock(side_effect=RuntimeError("FGA down")),
    )

    with pytest.raises(KnowledgeDocumentDistributionError, match="permission"):
        await service.share_approved(_command())

    entries = await KnowledgeFileRepositoryImpl(async_db_session).find_distribution_entries_by_document_id(91)
    share = next(entry for entry in entries if entry.entry_type == KnowledgeFileEntryType.SHARE.value)
    assert share.entry_status == KnowledgeFileEntryStatus.PREPARING.value


@pytest.mark.asyncio
async def test_share_approval_callback_is_idempotent(
    async_db_session: AsyncSession,
):
    await _seed_document(async_db_session)
    tuple_writer = AsyncMock()
    service = _service(async_db_session, tuple_writer=tuple_writer)

    first = await service.share_approved(_command())
    second = await service.share_approved(_command())

    assert second.share_entry_id == first.share_entry_id
    assert second.idempotent is True
    assert tuple_writer.await_count == 1


@pytest.mark.asyncio
async def test_share_cannot_be_shared_again(
    async_db_session: AsyncSession,
):
    await _seed_document(async_db_session)
    service = _service(async_db_session)
    first = await service.share_approved(_command())

    with pytest.raises(KnowledgeDocumentDistributionError, match="manager or publish"):
        await service.share_approved(
            ShareKnowledgeDocumentCommand(
                tenant_id=7,
                approval_instance_id=8002,
                document_id=91,
                source_entry_id=first.share_entry_id,
                target_space_id=40,
            )
        )


@pytest.mark.asyncio
async def test_recipient_delete_hides_only_selected_share(
    async_db_session: AsyncSession,
):
    await _seed_document(async_db_session)
    service = _service(async_db_session)
    first = await service.share_approved(_command())
    second = await service.share_approved(
        ShareKnowledgeDocumentCommand(
            tenant_id=7,
            approval_instance_id=8002,
            document_id=91,
            source_entry_id=100,
            target_space_id=40,
        )
    )

    result = await service.remove_share_entry(
        tenant_id=7,
        document_id=91,
        share_entry_id=first.share_entry_id,
        actor_entry_id=first.share_entry_id,
    )

    repository = KnowledgeFileRepositoryImpl(async_db_session)
    removed = await repository.find_by_id(first.share_entry_id)
    untouched = await repository.find_by_id(second.share_entry_id)
    manager = await repository.find_by_id(100)
    assert result.idempotent is False
    assert removed.entry_status == KnowledgeFileEntryStatus.DELETING.value
    assert untouched.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_deleting_share_blocks_recreation_until_cleanup_finishes(
    async_db_session: AsyncSession,
):
    await _seed_document(async_db_session)
    service = _service(async_db_session)
    share = await service.share_approved(_command())
    await service.remove_share_entry(
        tenant_id=7,
        document_id=91,
        share_entry_id=share.share_entry_id,
        actor_entry_id=share.share_entry_id,
    )

    with pytest.raises(
        KnowledgeDocumentDistributionError,
        match="already has an entry",
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


@pytest.mark.asyncio
async def test_manager_can_revoke_share_idempotently(
    async_db_session: AsyncSession,
):
    await _seed_document(async_db_session)
    service = _service(async_db_session)
    share = await service.share_approved(_command())

    first = await service.remove_share_entry(
        tenant_id=7,
        document_id=91,
        share_entry_id=share.share_entry_id,
        actor_entry_id=100,
    )
    second = await service.remove_share_entry(
        tenant_id=7,
        document_id=91,
        share_entry_id=share.share_entry_id,
        actor_entry_id=100,
    )

    assert first.idempotent is False
    assert second.idempotent is True
