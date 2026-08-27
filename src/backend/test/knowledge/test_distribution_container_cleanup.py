"""F098: batch cleanup of distribution entries when their container is deleted.

Deleting a folder or a knowledge space now sweeps whatever distribution
entries live inside it instead of refusing. Each entry follows exactly the
rule it would follow on its own — a manager rolls back if it can, a shortcut
is detached — and one entry that cannot be processed must not stop the rest.
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
from bisheng.knowledge.domain.services.knowledge_distribution_cleanup_service import (
    EntryCleanupAction,
    KnowledgeDistributionCleanupService,
)
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
    KnowledgeDocumentDistributionService,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
)

TENANT_ID = 7
DOCUMENT_ID = 98091
MANAGER_ID = 98100
MANAGER_SPACE = 98040
SOURCE_SPACE = 98010
SHARE_SPACE = 98030


def _distribution_service(session: AsyncSession) -> KnowledgeDocumentDistributionService:
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


def _cleanup_service(session: AsyncSession) -> KnowledgeDistributionCleanupService:
    return KnowledgeDistributionCleanupService(
        distribution_service=_distribution_service(session)
    )


def _entry(
    entry_id: int,
    space_id: int,
    entry_type: str,
    *,
    predecessor_id: int | None = None,
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
        entry_type=entry_type,
        entry_status=status,
        predecessor_logic_file_id=predecessor_id,
        projection_status=KnowledgeFileProjectionStatus.READY.value,
    )


async def _seed(
    session: AsyncSession,
    *,
    document_predecessor_id: int | None,
    extra_entries: list[KnowledgeFile],
) -> None:
    space_ids = sorted(
        {MANAGER_SPACE, SOURCE_SPACE, SHARE_SPACE, *(int(e.knowledge_id) for e in extra_entries)}
    )
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
                knowledge_id=MANAGER_SPACE,
                primary_version_id=98501,
                content_generation=3,
                lifecycle_status=KnowledgeDocumentLifecycleStatus.ACTIVE.value,
                predecessor_logic_file_id=document_predecessor_id,
            ),
            KnowledgeFile(
                id=MANAGER_ID,
                tenant_id=TENANT_ID,
                knowledge_id=MANAGER_SPACE,
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
            *extra_entries,
        ]
    )
    await session.commit()


async def _reload(session: AsyncSession, entry_id: int) -> KnowledgeFile:
    return await KnowledgeFileRepositoryImpl(session).find_by_id(entry_id)


@pytest.mark.asyncio
async def test_manager_rolls_back_when_predecessor_alive(async_db_session: AsyncSession):
    """A manager whose chain still has a live shortcut goes home, not away."""
    await _seed(
        async_db_session,
        document_predecessor_id=98101,
        extra_entries=[_entry(98101, SOURCE_SPACE, KnowledgeFileEntryType.PUBLISH.value)],
    )
    service = _cleanup_service(async_db_session)

    outcomes = await service.cleanup_entries([await _reload(async_db_session, MANAGER_ID)])

    assert [item.action for item in outcomes] == [EntryCleanupAction.ROLLBACK]
    manager = await _reload(async_db_session, MANAGER_ID)
    assert int(manager.knowledge_id) == SOURCE_SPACE


@pytest.mark.asyncio
async def test_manager_hard_deletes_without_predecessor(async_db_session: AsyncSession):
    await _seed(async_db_session, document_predecessor_id=None, extra_entries=[])
    service = _cleanup_service(async_db_session)

    outcomes = await service.cleanup_entries([await _reload(async_db_session, MANAGER_ID)])

    assert [item.action for item in outcomes] == [EntryCleanupAction.FINAL_DELETE]
    manager = await _reload(async_db_session, MANAGER_ID)
    assert manager.entry_status == KnowledgeFileEntryStatus.DELETING.value


@pytest.mark.asyncio
async def test_publish_entry_detached(async_db_session: AsyncSession):
    await _seed(
        async_db_session,
        document_predecessor_id=98101,
        extra_entries=[_entry(98101, SOURCE_SPACE, KnowledgeFileEntryType.PUBLISH.value)],
    )
    service = _cleanup_service(async_db_session)

    outcomes = await service.cleanup_entries([await _reload(async_db_session, 98101)])

    assert [item.action for item in outcomes] == [EntryCleanupAction.DETACHED]
    assert outcomes[0].degraded is False
    detached = await _reload(async_db_session, 98101)
    assert detached.entry_status == KnowledgeFileEntryStatus.DELETING.value


@pytest.mark.asyncio
async def test_share_entry_revoked(async_db_session: AsyncSession):
    await _seed(
        async_db_session,
        document_predecessor_id=None,
        extra_entries=[_entry(98201, SHARE_SPACE, KnowledgeFileEntryType.SHARE.value)],
    )
    service = _cleanup_service(async_db_session)

    outcomes = await service.cleanup_entries([await _reload(async_db_session, 98201)])

    assert [item.action for item in outcomes] == [EntryCleanupAction.SHARE_REVOKED]
    revoked = await _reload(async_db_session, 98201)
    assert revoked.entry_status == KnowledgeFileEntryStatus.DELETING.value


@pytest.mark.asyncio
async def test_business_failure_degrades_to_force_detach(async_db_session: AsyncSession):
    """A forked chain defeats strict detach; cleanup must still make progress."""
    await _seed(
        async_db_session,
        document_predecessor_id=98102,
        extra_entries=[
            _entry(98101, SOURCE_SPACE, KnowledgeFileEntryType.PUBLISH.value),
            _entry(98102, 98020, KnowledgeFileEntryType.PUBLISH.value, predecessor_id=98101),
            _entry(98103, 98021, KnowledgeFileEntryType.PUBLISH.value, predecessor_id=98101),
        ],
    )
    service = _cleanup_service(async_db_session)

    outcomes = await service.cleanup_entries([await _reload(async_db_session, 98101)])

    assert [item.action for item in outcomes] == [EntryCleanupAction.FORCE_DETACHED]
    assert outcomes[0].degraded is True
    assert (await _reload(async_db_session, 98102)).predecessor_logic_file_id is None
    assert (await _reload(async_db_session, 98103)).predecessor_logic_file_id is None


@pytest.mark.asyncio
async def test_batch_continues_past_a_failing_entry(async_db_session: AsyncSession):
    """One unprocessable entry must not strand the rest of the container."""
    await _seed(
        async_db_session,
        document_predecessor_id=None,
        extra_entries=[
            _entry(98201, SHARE_SPACE, KnowledgeFileEntryType.SHARE.value),
            _entry(
                98202,
                SHARE_SPACE,
                KnowledgeFileEntryType.SHARE.value,
                status=KnowledgeFileEntryStatus.PREPARING.value,
            ),
        ],
    )
    service = _cleanup_service(async_db_session)

    outcomes = await service.cleanup_entries(
        [
            await _reload(async_db_session, 98202),
            await _reload(async_db_session, 98201),
        ]
    )

    by_id = {item.entry_id: item for item in outcomes}
    assert by_id[98202].action == EntryCleanupAction.FAILED
    assert by_id[98202].error
    assert by_id[98201].action == EntryCleanupAction.SHARE_REVOKED


@pytest.mark.asyncio
async def test_already_deleting_entry_is_skipped(async_db_session: AsyncSession):
    await _seed(
        async_db_session,
        document_predecessor_id=None,
        extra_entries=[
            _entry(
                98101,
                SOURCE_SPACE,
                KnowledgeFileEntryType.PUBLISH.value,
                status=KnowledgeFileEntryStatus.DELETING.value,
            )
        ],
    )
    service = _cleanup_service(async_db_session)

    outcomes = await service.cleanup_entries([await _reload(async_db_session, 98101)])

    assert [item.action for item in outcomes] == [EntryCleanupAction.SKIPPED]
