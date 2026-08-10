from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.constants.enums.knowledge_parse_priority import KnowledgeParsePriority
from bisheng.common.errcode.knowledge import KnowledgeFileNotExistError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_parse_priority_snapshot_service import (
    KnowledgeParsePrioritySnapshotService,
)


def _file(file_id: int, *, user_id: int | None = 7, priority: str | None = None) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=1,
        user_id=user_id,
        knowledge_id=9,
        file_name=f"{file_id}.pdf",
        parse_priority=priority,
    )


@pytest.mark.asyncio
async def test_repository_first_writer_wins_under_concurrent_calls(tmp_path) -> None:
    db_path = tmp_path / "parse-priority.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"timeout": 10})
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFile.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as setup_session:
        setup_session.add(_file(1))
        await setup_session.commit()

    async with (
        AsyncSession(engine, expire_on_commit=False) as first_session,
        AsyncSession(engine, expire_on_commit=False) as second_session,
    ):
        first, second = await asyncio.gather(
            KnowledgeFileRepositoryImpl(first_session).set_parse_priority_if_unset(1, "high"),
            KnowledgeFileRepositoryImpl(second_session).set_parse_priority_if_unset(1, "low"),
        )

    assert first is not None and second is not None
    assert first.parse_priority in {"high", "low"}
    assert second.parse_priority == first.parse_priority
    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_repeated_call_does_not_overwrite_snapshot(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'repeat.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFile.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(_file(2))
        await session.commit()
        repository = KnowledgeFileRepositoryImpl(session)

        assert (await repository.set_parse_priority_if_unset(2, "medium")).parse_priority == "medium"
        assert (await repository.set_parse_priority_if_unset(2, "high")).parse_priority == "medium"
        assert await repository.set_parse_priority_if_unset(999, "low") is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_rolls_back_and_propagates_database_failure() -> None:
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("database unavailable")
    repository = KnowledgeFileRepositoryImpl(session)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await repository.set_parse_priority_if_unset(2, "medium")

    session.rollback.assert_awaited_once()


class FakeFileRepository:
    def __init__(self, files: list[KnowledgeFile]):
        self.files = {int(file.id): file for file in files}
        self.set_calls: list[tuple[int, str]] = []

    async def find_by_ids(self, file_ids: list[int]) -> list[KnowledgeFile]:
        return [self.files[file_id] for file_id in file_ids if file_id in self.files]

    async def set_parse_priority_if_unset(self, file_id: int, priority: str) -> KnowledgeFile | None:
        self.set_calls.append((file_id, priority))
        file = self.files.get(file_id)
        if file is not None and file.parse_priority is None:
            file.parse_priority = priority
        return file


@pytest.mark.asyncio
async def test_snapshot_reuses_existing_value_without_resolving_role() -> None:
    repository = FakeFileRepository([_file(3, priority="low")])
    priority_service = AsyncMock()
    service = KnowledgeParsePrioritySnapshotService(repository, priority_service)

    result = await service.get_or_create(file_id=3, operator_user_id=99)

    assert result is KnowledgeParsePriority.LOW
    priority_service.resolve.assert_not_called()
    assert repository.set_calls == []


@pytest.mark.asyncio
async def test_snapshot_uses_operator_for_new_file_and_uploader_for_legacy_file() -> None:
    repository = FakeFileRepository([_file(4, user_id=7), _file(5, user_id=8)])
    priority_service = AsyncMock()
    priority_service.resolve = AsyncMock(side_effect=[KnowledgeParsePriority.HIGH, KnowledgeParsePriority.MEDIUM])
    service = KnowledgeParsePrioritySnapshotService(repository, priority_service)

    assert (
        await service.get_or_create(file_id=4, operator_user_id=99, operator_is_global_super=True)
        is KnowledgeParsePriority.HIGH
    )
    assert await service.get_or_create(file_id=5) is KnowledgeParsePriority.MEDIUM
    assert priority_service.resolve.await_args_list[0].kwargs["user_id"] == 99
    assert priority_service.resolve.await_args_list[1].kwargs["user_id"] == 8


@pytest.mark.asyncio
async def test_snapshot_batch_resolves_same_user_once_and_missing_uploader_as_low() -> None:
    repository = FakeFileRepository([_file(6, user_id=7), _file(7, user_id=7), _file(8, user_id=None)])
    priority_service = AsyncMock()
    priority_service.resolve = AsyncMock(side_effect=[KnowledgeParsePriority.MEDIUM, KnowledgeParsePriority.LOW])
    service = KnowledgeParsePrioritySnapshotService(repository, priority_service)

    result = await service.get_or_create_batch(file_ids=[6, 7, 8])

    assert result == {
        6: KnowledgeParsePriority.MEDIUM,
        7: KnowledgeParsePriority.MEDIUM,
        8: KnowledgeParsePriority.LOW,
    }
    assert priority_service.resolve.await_count == 2


@pytest.mark.asyncio
async def test_snapshot_propagates_persistence_errors_and_missing_file() -> None:
    repository = FakeFileRepository([_file(9)])
    priority_service = AsyncMock()
    priority_service.resolve = AsyncMock(return_value=KnowledgeParsePriority.LOW)
    service = KnowledgeParsePrioritySnapshotService(repository, priority_service)
    repository.set_parse_priority_if_unset = AsyncMock(side_effect=RuntimeError("db unavailable"))

    with pytest.raises(RuntimeError, match="db unavailable"):
        await service.get_or_create(file_id=9)
    with pytest.raises(KnowledgeFileNotExistError):
        await service.get_or_create(file_id=999)
