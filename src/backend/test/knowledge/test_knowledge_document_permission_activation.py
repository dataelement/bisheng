"""Failure-injection tests for the F059 permission activation saga."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationError,
    KnowledgeDocumentPermissionActivationService,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation


def _preparing_entry(
    *,
    entry_id: int = 101,
    file_level_path: str | None = None,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=entry_id,
        tenant_id=7,
        knowledge_id=10,
        file_name="logical.pdf",
        file_size=0,
        reference_document_id=91,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        entry_status=KnowledgeFileEntryStatus.PREPARING.value,
        file_level_path=file_level_path,
    )


@pytest.mark.asyncio
async def test_fga_failure_keeps_preparing_entry_hidden(
    async_db_session: AsyncSession,
):
    entry = _preparing_entry()
    async_db_session.add(entry)
    await async_db_session.commit()
    writer = AsyncMock(side_effect=RuntimeError("OpenFGA unavailable"))
    service = KnowledgeDocumentPermissionActivationService(
        file_repository=KnowledgeFileRepositoryImpl(async_db_session),
        tuple_writer=writer,
    )

    with pytest.raises(
        KnowledgeDocumentPermissionActivationError,
        match="prewrite",
    ):
        await service.prewrite_and_activate(entry_id=101)

    refreshed = await KnowledgeFileRepositoryImpl(async_db_session).find_by_id(101)
    assert refreshed.entry_status == KnowledgeFileEntryStatus.PREPARING.value


@pytest.mark.asyncio
async def test_parent_and_explicit_tuples_are_prebuilt_before_activation(
    async_db_session: AsyncSession,
):
    entry = _preparing_entry(file_level_path="/88")
    async_db_session.add(entry)
    await async_db_session.commit()
    writer = AsyncMock()
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    service = KnowledgeDocumentPermissionActivationService(
        file_repository=repository,
        tuple_writer=writer,
    )
    explicit = TupleOperation(
        action="write",
        user="user:7",
        relation="manager",
        object="knowledge_file:101",
    )

    activated = await service.prewrite_and_activate(
        entry_id=101,
        explicit_operations=[explicit],
    )

    assert activated is True
    operations = writer.await_args.args[0]
    assert operations == [
        TupleOperation(
            action="write",
            user="folder:88",
            relation="parent",
            object="knowledge_file:101",
        ),
        explicit,
    ]
    refreshed = await repository.find_by_id(101)
    assert refreshed.entry_status == KnowledgeFileEntryStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_activation_is_idempotent_after_entry_is_active(
    async_db_session: AsyncSession,
):
    entry = _preparing_entry()
    entry.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
    async_db_session.add(entry)
    await async_db_session.commit()
    writer = AsyncMock()
    service = KnowledgeDocumentPermissionActivationService(
        file_repository=KnowledgeFileRepositoryImpl(async_db_session),
        tuple_writer=writer,
    )

    activated = await service.prewrite_and_activate(entry_id=101)

    assert activated is False
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleting_entry_revokes_same_parent_and_explicit_tuples(
    async_db_session: AsyncSession,
):
    entry = _preparing_entry()
    entry.entry_status = KnowledgeFileEntryStatus.DELETING.value
    async_db_session.add(entry)
    await async_db_session.commit()
    writer = AsyncMock()
    service = KnowledgeDocumentPermissionActivationService(
        file_repository=KnowledgeFileRepositoryImpl(async_db_session),
        tuple_writer=writer,
    )
    explicit = TupleOperation(
        action="write",
        user="user:7",
        relation="manager",
        object="knowledge_file:101",
    )

    revoked = await service.revoke_deleting_entry(
        entry_id=101,
        explicit_operations=[explicit],
    )

    assert revoked is True
    assert writer.await_args.args[0] == [
        TupleOperation(
            action="delete",
            user="knowledge_space:10",
            relation="parent",
            object="knowledge_file:101",
        ),
        TupleOperation(
            action="delete",
            user="user:7",
            relation="manager",
            object="knowledge_file:101",
        ),
    ]


@pytest.mark.asyncio
async def test_age_scan_returns_preparing_and_deleting_entries_only(
    async_db_session: AsyncSession,
):
    old = datetime(2026, 7, 27, 10, 0, 0)
    async_db_session.add_all(
        [
            _preparing_entry(entry_id=101),
            KnowledgeFile(
                **{
                    **_preparing_entry(entry_id=102).model_dump(
                        exclude={"id", "create_time", "update_time"}
                    ),
                    "id": 102,
                    "entry_status": KnowledgeFileEntryStatus.DELETING.value,
                }
            ),
            KnowledgeFile(
                **{
                    **_preparing_entry(entry_id=103).model_dump(
                        exclude={"id", "create_time", "update_time"}
                    ),
                    "id": 103,
                    "entry_status": KnowledgeFileEntryStatus.ACTIVE.value,
                }
            ),
        ]
    )
    await async_db_session.commit()
    await async_db_session.execute(
        KnowledgeFile.__table__.update().values(update_time=old)
    )
    await async_db_session.commit()

    candidates = await KnowledgeFileRepositoryImpl(
        async_db_session
    ).find_permission_reconcile_candidates(
        older_than=old + timedelta(minutes=1),
        limit=20,
    )

    assert [entry.id for entry in candidates] == [101, 102]
