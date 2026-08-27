"""F098: degraded chain detach used when normal rewiring cannot be validated.

The strict path (``remove_publish_entry``) refuses to touch a chain it cannot
prove is unambiguous, which is right for a user-initiated delete. Container
deletes cannot afford that refusal: one unprovable chain would leave a
knowledge space stuck in retirement forever, so they fall back to these
semantics — relink whatever points at the entry, then let it go.
"""

from __future__ import annotations

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
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
)

TENANT_ID = 7
DOCUMENT_ID = 98091
MANAGER_ID = 98100


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


def _publish_entry(
    entry_id: int,
    space_id: int,
    predecessor_id: int | None,
    *,
    status: str = KnowledgeFileEntryStatus.ACTIVE.value,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=entry_id,
        tenant_id=TENANT_ID,
        knowledge_id=space_id,
        file_name="canonical.pdf",
        file_size=0,
        status=KnowledgeFileStatus.SUCCESS.value,
        file_level_path="/8",
        level=2,
        reference_document_id=DOCUMENT_ID,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        entry_status=status,
        predecessor_logic_file_id=predecessor_id,
        projection_status=KnowledgeFileProjectionStatus.READY.value,
    )


async def _seed_chain(
    session: AsyncSession,
    *,
    manager_space: int,
    document_predecessor_id: int | None,
    publish_entries: list[KnowledgeFile],
) -> None:
    """Seed a document whose manager sits in ``manager_space`` plus its chain."""
    space_ids = sorted({manager_space, *(int(item.knowledge_id) for item in publish_entries)})
    session.add_all(
        [
            Knowledge(
                id=space_id,
                tenant_id=TENANT_ID,
                name=f"库{space_id}",
                type=KnowledgeTypeEnum.SPACE.value,
                state=KnowledgeState.PUBLISHED.value,
            )
            for space_id in space_ids
        ]
    )
    session.add_all(
        [
            KnowledgeDocument(
                id=DOCUMENT_ID,
                tenant_id=TENANT_ID,
                knowledge_id=manager_space,
                primary_version_id=98501,
                content_generation=3,
                lifecycle_status=KnowledgeDocumentLifecycleStatus.ACTIVE.value,
                predecessor_logic_file_id=document_predecessor_id,
            ),
            KnowledgeFile(
                id=MANAGER_ID,
                tenant_id=TENANT_ID,
                knowledge_id=manager_space,
                file_name="canonical.pdf",
                object_name="tenant/7/canonical.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                file_level_path="/8",
                level=2,
                reference_document_id=DOCUMENT_ID,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
                desired_content_generation=3,
                applied_content_generation=3,
            ),
            KnowledgeDocumentVersion(
                id=98501,
                document_id=DOCUMENT_ID,
                knowledge_file_id=MANAGER_ID,
                version_no=1,
                is_primary=True,
            ),
            *publish_entries,
        ]
    )
    await session.commit()


async def _reload(session: AsyncSession, entry_id: int) -> KnowledgeFile:
    return await KnowledgeFileRepositoryImpl(session).find_by_id(entry_id)


async def _reload_document(session: AsyncSession) -> KnowledgeDocument:
    return await KnowledgeDocumentRepositoryImpl(session).find_by_id(DOCUMENT_ID)


@pytest.mark.asyncio
async def test_force_detach_relinks_successor(async_db_session: AsyncSession):
    """Chain document -> B -> A. Dropping A leaves B pointing past it."""
    await _seed_chain(
        async_db_session,
        manager_space=98040,
        document_predecessor_id=98102,
        publish_entries=[
            _publish_entry(98101, 98010, None),
            _publish_entry(98102, 98020, 98101),
        ],
    )
    service = _service(async_db_session)

    result = await service.force_detach_publish_entry(
        tenant_id=TENANT_ID,
        document_id=DOCUMENT_ID,
        publish_entry_id=98101,
    )

    assert result.idempotent is False
    successor = await _reload(async_db_session, 98102)
    assert successor.predecessor_logic_file_id is None
    document = await _reload_document(async_db_session)
    assert int(document.predecessor_logic_file_id) == 98102
    detached = await _reload(async_db_session, 98101)
    assert detached.entry_status == KnowledgeFileEntryStatus.DELETING.value


@pytest.mark.asyncio
async def test_force_detach_relinks_document_pointer(async_db_session: AsyncSession):
    """Chain document -> B -> A. Dropping B moves the document pointer back."""
    await _seed_chain(
        async_db_session,
        manager_space=98040,
        document_predecessor_id=98102,
        publish_entries=[
            _publish_entry(98101, 98010, None),
            _publish_entry(98102, 98020, 98101),
        ],
    )
    service = _service(async_db_session)

    await service.force_detach_publish_entry(
        tenant_id=TENANT_ID,
        document_id=DOCUMENT_ID,
        publish_entry_id=98102,
    )

    document = await _reload_document(async_db_session)
    assert int(document.predecessor_logic_file_id) == 98101


@pytest.mark.asyncio
async def test_force_detach_tolerates_ambiguous_chain(async_db_session: AsyncSession):
    """A fork defeats the strict path; the degraded one relinks every successor."""
    await _seed_chain(
        async_db_session,
        manager_space=98040,
        document_predecessor_id=98102,
        publish_entries=[
            _publish_entry(98101, 98010, None),
            _publish_entry(98102, 98020, 98101),
            _publish_entry(98103, 98030, 98101),
        ],
    )
    service = _service(async_db_session)

    with pytest.raises(KnowledgeDocumentDistributionError):
        await service.remove_publish_entry(
            tenant_id=TENANT_ID,
            document_id=DOCUMENT_ID,
            publish_entry_id=98101,
        )
    await async_db_session.rollback()

    await service.force_detach_publish_entry(
        tenant_id=TENANT_ID,
        document_id=DOCUMENT_ID,
        publish_entry_id=98101,
    )

    assert (await _reload(async_db_session, 98102)).predecessor_logic_file_id is None
    assert (await _reload(async_db_session, 98103)).predecessor_logic_file_id is None
    assert (await _reload(async_db_session, 98101)).entry_status == (
        KnowledgeFileEntryStatus.DELETING.value
    )


@pytest.mark.asyncio
async def test_force_detach_is_idempotent(async_db_session: AsyncSession):
    await _seed_chain(
        async_db_session,
        manager_space=98040,
        document_predecessor_id=98101,
        publish_entries=[
            _publish_entry(
                98101,
                98010,
                None,
                status=KnowledgeFileEntryStatus.DELETING.value,
            )
        ],
    )
    service = _service(async_db_session)

    result = await service.force_detach_publish_entry(
        tenant_id=TENANT_ID,
        document_id=DOCUMENT_ID,
        publish_entry_id=98101,
    )

    assert result.idempotent is True
