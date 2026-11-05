"""Folder bookkeeping survives generic edits without leaking or resurrecting rows."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeMetadataFieldNotExistError
from bisheng.common.errcode.knowledge_space import SpaceFileChangeConflictError, SpaceFolderNotFoundError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileRead
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_schema import ModifyKnowledgeFileMetaDataReq
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService


@pytest.fixture
async def folder_metadata_db():
    context = set_current_tenant_id(42)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=[KnowledgeFile.__table__])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        row = KnowledgeFile(
            id=41,
            tenant_id=42,
            knowledge_id=7,
            user_id=9,
            file_type=0,
            file_name="folder",
            status=2,
            user_metadata={"department": {"field_value": "old"}},
        )
        session.add(row)
        await session.commit()
    try:
        yield engine, row
    finally:
        await engine.dispose()
        current_tenant_id.reset(context)


async def _marker(engine, *, status=2):
    async with AsyncSession(engine) as session:
        await session.execute(
            update(KnowledgeFile)
            .where(KnowledgeFile.tenant_id == 42, KnowledgeFile.id == 41)
            .values(
                status=status,
                user_metadata={
                    "_folder_delete": {"operation_id": "latest", "phase": "running" if status == 8 else "failed"}
                },
            )
        )
        await session.commit()


async def test_stale_update_cannot_clear_active_deletion(folder_metadata_db):
    """AC-05: old detached editor snapshot cannot clear a new delete marker."""
    engine, stale = folder_metadata_db
    await _marker(engine, status=8)
    stale.user_metadata = {"department": {"field_value": "edited"}}
    async with AsyncSession(engine) as session:
        with pytest.raises(SpaceFileChangeConflictError):
            await KnowledgeFileRepositoryImpl(session).update(stale)
    async with AsyncSession(engine) as session:
        row = await session.get(KnowledgeFile, 41)
        assert row.status == 8
        assert row.user_metadata["_folder_delete"]["operation_id"] == "latest"


async def test_generic_update_preserves_latest_terminal_marker(folder_metadata_db):
    """AC-05: replace user fields, retaining database's attempt instead of an old/forged one."""
    engine, stale = folder_metadata_db
    await _marker(engine)
    stale.user_metadata = {"department": {"field_value": "edited"}, "_folder_delete": {"operation_id": "forged"}}
    async with AsyncSession(engine) as session:
        row = await KnowledgeFileRepositoryImpl(session).update(stale)
        assert row.user_metadata["_folder_delete"]["operation_id"] == "latest"
        assert row.user_metadata["department"]["field_value"] == "edited"


async def test_update_cannot_resurrect_deleted_folder(folder_metadata_db):
    """AC-03: detached stale edit must not reinsert a hard-deleted directory."""
    engine, stale = folder_metadata_db
    async with AsyncSession(engine) as session:
        await session.execute(delete(KnowledgeFile).where(KnowledgeFile.tenant_id == 42, KnowledgeFile.id == 41))
        await session.commit()
    async with AsyncSession(engine) as session:
        with pytest.raises(SpaceFolderNotFoundError):
            await KnowledgeFileRepositoryImpl(session).update(stale)


def test_public_read_strips_private_marker_without_mutating_storage():
    """AC-07: public read excludes initiator/token and leaves ORM data intact."""
    row = KnowledgeFile(
        id=41,
        tenant_id=42,
        knowledge_id=7,
        file_type=0,
        file_name="folder",
        user_metadata={
            "department": {"field_value": "ops"},
            "_folder_delete": {"operation_id": "private", "initiator_user_id": 999},
        },
    )
    assert KnowledgeFileRead.model_validate(row).model_dump()["user_metadata"] == {"department": {"field_value": "ops"}}
    assert "_folder_delete" in row.user_metadata


async def test_metadata_listing_hides_reserved_key(folder_metadata_db):
    """AC-07: separate metadata endpoint cannot bypass serialization protection."""
    engine, _ = folder_metadata_db
    await _marker(engine)
    async with AsyncSession(engine) as session:
        data = await KnowledgeFileRepositoryImpl(session).get_user_metadata_by_knowledge_file_ids(7, [41])
    assert data[41] == {}


async def test_editor_cannot_address_reserved_key(monkeypatch):
    """AC-07: callers cannot overwrite or delete server-owned bookkeeping."""
    row = KnowledgeFile(
        id=41,
        tenant_id=42,
        knowledge_id=7,
        file_type=0,
        file_name="folder",
        status=2,
        user_metadata={"_folder_delete": {"operation_id": "private", "phase": "failed"}},
    )
    files = SimpleNamespace(find_by_id=AsyncMock(return_value=row), update=AsyncMock(return_value=row))
    space = SimpleNamespace(id=7, metadata_fields=[{"field_name": "department", "field_type": "string"}])
    service = KnowledgeFileService(files, SimpleNamespace(find_by_id=AsyncMock(return_value=space)))
    monkeypatch.setattr(service, "_ensure_knowledge_access", AsyncMock())
    monkeypatch.setattr(service, "modify_milvus_file_user_metadata", AsyncMock())
    monkeypatch.setattr(service, "modify_elasticsearch_file_user_metadata", AsyncMock())
    req = ModifyKnowledgeFileMetaDataReq(
        knowledge_file_id=41, user_metadata_list=[{"field_name": "_folder_delete", "field_value": "forged"}]
    )
    with pytest.raises(KnowledgeMetadataFieldNotExistError):
        await service.modify_file_user_metadata(SimpleNamespace(user_id=9), req)
    files.update.assert_not_awaited()


def test_parse_bulk_update_never_changes_folder_status(monkeypatch):
    """AC-02: parse workers cannot overwrite a directory's deleting state."""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlmodel import Session

    import bisheng.knowledge.domain.models.knowledge_file as module

    context = set_current_tenant_id(42)
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[KnowledgeFile.__table__])
    with Session(engine) as session:
        session.add_all(
            [
                KnowledgeFile(id=41, tenant_id=42, knowledge_id=7, file_type=0, file_name="folder", status=8),
                KnowledgeFile(id=42, tenant_id=42, knowledge_id=7, file_type=1, file_name="file", status=2),
            ]
        )
        session.commit()

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(module, "get_sync_db_session", sessions)
    try:
        module.KnowledgeFileDao.update_status_bulk([41, 42], module.KnowledgeFileStatus.FAILED)
        with Session(engine) as session:
            assert session.get(KnowledgeFile, 41).status == 8
            assert session.get(KnowledgeFile, 42).status == 3
    finally:
        engine.dispose()
        current_tenant_id.reset(context)


@pytest.mark.parametrize("action", ["add", "modify", "delete"])
async def test_batch_metadata_does_not_flush_other_folders_before_their_fence(folder_metadata_db, monkeypatch, action):
    """AC-05: the first save must not flush an unguarded attached later row."""
    from bisheng.open_endpoints.domain.schemas.knowledge import DeleteUserMetadataReq

    engine, _ = folder_metadata_db
    async with AsyncSession(engine) as session:
        session.add(
            KnowledgeFile(
                id=42,
                tenant_id=42,
                knowledge_id=7,
                user_id=9,
                file_type=0,
                file_name="later",
                status=2,
                user_metadata={"department": {"field_value": "old"}},
            )
        )
        await session.commit()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        repository = KnowledgeFileRepositoryImpl(session)
        original_update = repository.update
        first = True

        async def interleave_claim(row):
            nonlocal first
            if first:
                first = False
                async with AsyncSession(engine) as claim, claim.begin():
                    await claim.execute(
                        update(KnowledgeFile)
                        .where(KnowledgeFile.tenant_id == 42, KnowledgeFile.id == 42)
                        .values(
                            status=8,
                            user_metadata={
                                "department": {"field_value": "old"},
                                "_folder_delete": {"operation_id": "latest", "phase": "running"},
                            },
                        )
                    )
            return await original_update(row)

        monkeypatch.setattr(repository, "update", interleave_claim)
        space = SimpleNamespace(
            id=7, metadata_fields=[{"field_name": name, "field_type": "string"} for name in ("department", "category")]
        )
        service = KnowledgeFileService(repository, SimpleNamespace(find_by_id=AsyncMock(return_value=space)))
        monkeypatch.setattr(service, "_ensure_knowledge_access", AsyncMock())
        monkeypatch.setattr(service, "modify_milvus_file_user_metadata", AsyncMock())
        monkeypatch.setattr(service, "modify_elasticsearch_file_user_metadata", AsyncMock())
        user = SimpleNamespace(user_id=9)
        with pytest.raises(SpaceFileChangeConflictError):
            if action == "delete":
                requests = [
                    DeleteUserMetadataReq(knowledge_file_id=fid, field_names=["department"]) for fid in (41, 42)
                ]
                await service.batch_delete_file_user_metadata(user, 7, requests)
            else:
                name = "category" if action == "add" else "department"
                requests = [
                    ModifyKnowledgeFileMetaDataReq(
                        knowledge_file_id=fid, user_metadata_list=[{"field_name": name, "field_value": "edited"}]
                    )
                    for fid in (41, 42)
                ]
                method = service.add_file_user_metadata if action == "add" else service.batch_modify_file_user_metadata
                await method(user, 7, requests)
    async with AsyncSession(engine) as session:
        row = await session.get(KnowledgeFile, 42)
        assert row.status == 8
        assert row.user_metadata["_folder_delete"]["operation_id"] == "latest"
        assert row.user_metadata["department"]["field_value"] == "old"
        assert "category" not in row.user_metadata


def test_legacy_list_response_hides_private_marker():
    """AC-07: legacy list/infinitescroll DTO cannot bypass the public read serializer."""
    from bisheng.api.v1.schema.knowledge import KnowledgeFileResp

    row = KnowledgeFileResp(
        id=41,
        knowledge_id=7,
        file_type=0,
        file_name="folder",
        user_metadata={"department": {"field_value": "ops"}, "_folder_delete": {"operation_id": "secret"}},
    )
    assert row.model_dump()["user_metadata"] == {"department": {"field_value": "ops"}}


@pytest.mark.parametrize("action", ["add", "modify", "delete"])
async def test_batch_metadata_cannot_edit_another_spaces_folder(folder_metadata_db, monkeypatch, action):
    """AC-07: authorizing the URL space never authorizes supplied IDs from another space."""
    from bisheng.common.errcode.knowledge import KnowledgeFileNotExistError
    from bisheng.open_endpoints.domain.schemas.knowledge import DeleteUserMetadataReq

    engine, _ = folder_metadata_db
    async with AsyncSession(engine) as session:
        session.add(
            KnowledgeFile(
                id=42,
                tenant_id=42,
                knowledge_id=8,
                user_id=9,
                file_type=0,
                file_name="other-space",
                status=2,
                user_metadata={"department": {"field_value": "old"}},
            )
        )
        await session.commit()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        repository = KnowledgeFileRepositoryImpl(session)
        space = SimpleNamespace(
            id=7, metadata_fields=[{"field_name": name, "field_type": "string"} for name in ("department", "category")]
        )
        service = KnowledgeFileService(repository, SimpleNamespace(find_by_id=AsyncMock(return_value=space)))
        monkeypatch.setattr(service, "_ensure_knowledge_access", AsyncMock())
        monkeypatch.setattr(service, "modify_milvus_file_user_metadata", AsyncMock())
        monkeypatch.setattr(service, "modify_elasticsearch_file_user_metadata", AsyncMock())
        user = SimpleNamespace(user_id=9)
        with pytest.raises(KnowledgeFileNotExistError):
            if action == "delete":
                await service.batch_delete_file_user_metadata(
                    user, 7, [DeleteUserMetadataReq(knowledge_file_id=42, field_names=["department"])]
                )
            else:
                method = service.add_file_user_metadata if action == "add" else service.batch_modify_file_user_metadata
                await method(
                    user,
                    7,
                    [
                        ModifyKnowledgeFileMetaDataReq(
                            knowledge_file_id=42,
                            user_metadata_list=[
                                {"field_name": "category" if action == "add" else "department", "field_value": "edited"}
                            ],
                        )
                    ],
                )
    async with AsyncSession(engine) as session:
        assert (await session.get(KnowledgeFile, 42)).user_metadata == {"department": {"field_value": "old"}}


async def test_deleting_folder_filter_and_total_remain_consistent(folder_metadata_db, monkeypatch):
    """AC-02: including deleting folders in filtered data also includes them in its total."""
    from contextlib import asynccontextmanager

    from sqlmodel import select

    import bisheng.knowledge.domain.models.knowledge_file as module

    engine, _ = folder_metadata_db
    await _marker(engine, status=8)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(module, "get_async_db_session", sessions)
    async with sessions() as session:
        stmt = module.KnowledgeFileDao._build_file_filters_statement(
            select(KnowledgeFile).where(KnowledgeFile.knowledge_id == 7), status=[3]
        )
        rows = (await session.exec(stmt)).all()
    count = await module.KnowledgeFileDao.async_count_file_by_filters(7, status=[3])
    assert count == len(rows) == 1
