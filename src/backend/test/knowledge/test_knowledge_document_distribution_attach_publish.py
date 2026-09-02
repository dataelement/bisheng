"""In-place conversion of a lower-space duplicate into a publish entry."""

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
    AttachExistingAsPublishCommand,
    KnowledgeDocumentDistributionError,
    KnowledgeDocumentDistributionService,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
)


def _service(session: AsyncSession) -> KnowledgeDocumentDistributionService:
    file_repository = KnowledgeFileRepositoryImpl(session)
    return KnowledgeDocumentDistributionService(
        session=session,
        document_repository=KnowledgeDocumentRepositoryImpl(session),
        version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
        file_repository=file_repository,
        permission_activation_service=KnowledgeDocumentPermissionActivationService(
            file_repository=file_repository,
            tuple_writer=AsyncMock(),
        ),
        permission_snapshot_loader=AsyncMock(return_value=[]),
    )


async def _seed_spaces(session: AsyncSession, *space_ids: int) -> None:
    session.add_all(
        [
            Knowledge(
                id=space_id,
                tenant_id=7,
                name=f"空间{space_id}",
                type=KnowledgeTypeEnum.SPACE.value,
            )
            for space_id in space_ids
        ]
    )


async def _seed_independent_files(session: AsyncSession) -> None:
    await _seed_spaces(session, 10, 20, 30)
    session.add_all(
        [
            KnowledgeFile(
                id=100,
                tenant_id=7,
                user_id=501,
                knowledge_id=10,
                file_name="same.pdf",
                object_name="tenant/7/public.pdf",
                preview_file_object_name="tenant/7/public-preview.pdf",
                file_size=2048,
                md5="same-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeFile(
                id=200,
                tenant_id=7,
                user_id=502,
                knowledge_id=20,
                file_name="same.pdf",
                object_name="tenant/7/department.pdf",
                preview_file_object_name="tenant/7/department-preview.pdf",
                file_size=2048,
                md5="same-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
                file_encoding="GF-STD-SC-20260500000001",
            ),
        ]
    )
    await session.commit()


def _command(*, origin_file_id: int = 100, source_file_id: int = 200) -> AttachExistingAsPublishCommand:
    return AttachExistingAsPublishCommand(
        tenant_id=7,
        origin_file_id=origin_file_id,
        source_file_id=source_file_id,
    )


@pytest.mark.asyncio
async def test_attach_converts_lower_file_in_place_and_keeps_origin_physical(
    async_db_session: AsyncSession,
):
    await _seed_independent_files(async_db_session)
    service = _service(async_db_session)

    result = await service.attach_existing_as_publish(_command())

    origin = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(100)
    source = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(200)
    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(result.document_id)

    assert result.idempotent is False
    assert result.publish_entry_id == 200
    assert result.manager_file_id == 100
    assert result.retained_history_file_ids == ()
    assert origin.knowledge_id == 10
    assert origin.entry_type == KnowledgeFileEntryType.MANAGER.value
    assert origin.md5 == "same-md5"
    assert origin.object_name == "tenant/7/public.pdf"
    assert source.knowledge_id == 20
    assert source.entry_type == KnowledgeFileEntryType.PUBLISH.value
    assert source.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    assert source.allow_download is False
    assert source.md5 is None
    assert source.file_size == 0
    assert source.object_name is None
    assert source.preview_file_object_name is None
    assert source.file_encoding == "GF-STD-SC-20260500000001"
    assert int(source.reference_document_id) == result.document_id
    assert int(document.knowledge_id) == 10
    assert int(document.predecessor_logic_file_id) == 200
    assert source.predecessor_logic_file_id is None


@pytest.mark.asyncio
async def test_attach_is_idempotent_when_source_is_already_the_publish_entry(
    async_db_session: AsyncSession,
):
    await _seed_independent_files(async_db_session)
    service = _service(async_db_session)
    first = await service.attach_existing_as_publish(_command())

    second = await service.attach_existing_as_publish(_command())

    assert second.idempotent is True
    assert second.document_id == first.document_id
    assert second.publish_entry_id == 200


@pytest.mark.asyncio
async def test_attach_keeps_unique_history_as_new_primary_on_the_lower_document(
    async_db_session: AsyncSession,
):
    await _seed_spaces(async_db_session, 10, 20)
    async_db_session.add_all(
        [
            KnowledgeFile(
                id=100,
                tenant_id=7,
                knowledge_id=10,
                file_name="same.pdf",
                object_name="tenant/7/public.pdf",
                file_size=10,
                md5="same-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeDocument(
                id=2000,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=2002,
            ),
            KnowledgeFile(
                id=201,
                tenant_id=7,
                knowledge_id=20,
                file_name="old.pdf",
                object_name="tenant/7/old.pdf",
                file_size=8,
                md5="unique-history",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeFile(
                id=202,
                tenant_id=7,
                knowledge_id=20,
                file_name="same.pdf",
                object_name="tenant/7/department.pdf",
                file_size=10,
                md5="same-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeDocumentVersion(
                id=2001,
                document_id=2000,
                knowledge_file_id=201,
                version_no=1,
                is_primary=False,
            ),
            KnowledgeDocumentVersion(
                id=2002,
                document_id=2000,
                knowledge_file_id=202,
                version_no=2,
                is_primary=True,
            ),
        ]
    )
    await async_db_session.commit()
    service = _service(async_db_session)

    result = await service.attach_existing_as_publish(_command(source_file_id=202))

    assert result.retained_history_file_ids == (201,)
    publish = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(202)
    history = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(201)
    lower_document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(2000)
    lower_versions = await KnowledgeDocumentVersionRepositoryImpl(async_db_session).find_by_document_id(2000)

    assert publish.entry_type == KnowledgeFileEntryType.PUBLISH.value
    assert publish.md5 is None
    assert history.md5 == "unique-history"
    assert history.object_name == "tenant/7/old.pdf"
    assert int(lower_document.primary_version_id) == 2001
    assert [int(item.knowledge_file_id) for item in lower_versions] == [201]
    assert lower_versions[0].is_primary is True


@pytest.mark.asyncio
async def test_attach_appends_a_second_lower_space_at_the_predecessor_tail(
    async_db_session: AsyncSession,
):
    await _seed_independent_files(async_db_session)
    async_db_session.add(
        KnowledgeFile(
            id=300,
            tenant_id=7,
            knowledge_id=30,
            file_name="same.pdf",
            object_name="tenant/7/personal.pdf",
            file_size=2048,
            md5="same-md5",
            status=KnowledgeFileStatus.SUCCESS.value,
        )
    )
    await async_db_session.commit()
    service = _service(async_db_session)

    await service.attach_existing_as_publish(_command())
    second = await service.attach_existing_as_publish(_command(source_file_id=300))

    document = await KnowledgeDocumentRepositoryImpl(async_db_session).find_by_id(second.document_id)
    department = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(200)
    personal = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(300)

    assert int(document.predecessor_logic_file_id) == 200
    assert int(department.predecessor_logic_file_id) == 300
    assert personal.predecessor_logic_file_id is None
    assert personal.entry_type == KnowledgeFileEntryType.PUBLISH.value
    assert personal.allow_download is False


@pytest.mark.asyncio
async def test_attach_rejects_share_entries_and_same_space_files(
    async_db_session: AsyncSession,
):
    await _seed_independent_files(async_db_session)
    async_db_session.add(
        KnowledgeFile(
            id=210,
            tenant_id=7,
            knowledge_id=20,
            file_name="shared.pdf",
            status=KnowledgeFileStatus.SUCCESS.value,
            reference_document_id=91,
            entry_type=KnowledgeFileEntryType.SHARE.value,
            entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
            projection_status=KnowledgeFileProjectionStatus.READY.value,
        )
    )
    await async_db_session.commit()
    service = _service(async_db_session)

    with pytest.raises(KnowledgeDocumentDistributionError, match="source entry is a share"):
        await service.attach_existing_as_publish(_command(source_file_id=210))

    async_db_session.add(
        KnowledgeFile(
            id=110,
            tenant_id=7,
            knowledge_id=10,
            file_name="same.pdf",
            object_name="tenant/7/public-dup.pdf",
            file_size=2048,
            md5="same-md5",
            status=KnowledgeFileStatus.SUCCESS.value,
        )
    )
    await async_db_session.commit()
    with pytest.raises(KnowledgeDocumentDistributionError, match="different spaces"):
        await service.attach_existing_as_publish(_command(source_file_id=110))


@pytest.mark.asyncio
async def test_attach_rejects_a_manager_that_already_has_distribution_dependents(
    async_db_session: AsyncSession,
):
    await _seed_spaces(async_db_session, 10, 20, 40)
    async_db_session.add_all(
        [
            KnowledgeFile(
                id=100,
                tenant_id=7,
                knowledge_id=10,
                file_name="same.pdf",
                object_name="tenant/7/public.pdf",
                file_size=10,
                md5="same-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeDocument(
                id=91,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=501,
            ),
            KnowledgeFile(
                id=200,
                tenant_id=7,
                knowledge_id=20,
                file_name="same.pdf",
                object_name="tenant/7/department.pdf",
                file_size=10,
                md5="same-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
            ),
            KnowledgeFile(
                id=400,
                tenant_id=7,
                knowledge_id=40,
                file_name="same.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
            ),
            KnowledgeDocumentVersion(
                id=501,
                document_id=91,
                knowledge_file_id=200,
                version_no=1,
                is_primary=True,
            ),
        ]
    )
    await async_db_session.commit()
    service = _service(async_db_session)

    with pytest.raises(KnowledgeDocumentDistributionError, match="distribution dependents"):
        await service.attach_existing_as_publish(_command())
