import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
)
from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationBatch,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
)
from bisheng.knowledge.domain.repositories.implementations import (
    knowledge_migration_runtime_repository_impl as runtime_repository_module,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_runtime_repository_impl import (
    KnowledgeMigrationRuntimeRepositoryImpl,
)


class RuntimeUser(SQLModel, table=True):
    __tablename__ = "user"

    user_id: int | None = Field(default=None, primary_key=True)
    user_name: str
    delete: int = 0


@pytest.fixture()
async def runtime_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    tables = [
        RuntimeUser.__table__,
        Knowledge.__table__,
        KnowledgeFile.__table__,
        KnowledgeFilePdfArtifact.__table__,
        KnowledgeDocument.__table__,
        KnowledgeDocumentVersion.__table__,
        KnowledgeMigrationBatch.__table__,
        KnowledgeMigrationUnit.__table__,
        KnowledgeMigrationFile.__table__,
    ]
    async with engine.begin() as connection:
        for table in tables:
            await connection.run_sync(table.create)
    session = AsyncSession(engine, expire_on_commit=False)
    yield session
    await session.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_version_chain_switch_preserves_document_and_version_ids(
    runtime_session,
    monkeypatch,
):
    monkeypatch.setattr(runtime_repository_module, "User", RuntimeUser)
    runtime_session.add(
        RuntimeUser(
            user_id=1,
            user_name="target-owner",
        )
    )
    runtime_session.add_all(
        [
            Knowledge(
                id=10,
                user_id=1,
                name="来源库",
                type=3,
                model="embedding-model",
                collection_name="source_collection",
                index_name="source_index",
            ),
            Knowledge(
                id=20,
                user_id=1,
                name="目标库",
                type=3,
                model="embedding-model",
                collection_name="target_collection",
                index_name="target_index",
            ),
        ]
    )
    source_files = [
        KnowledgeFile(
            id=1001,
            tenant_id=1,
            knowledge_id=10,
            user_id=1,
            user_name="source-owner",
            updater_id=1,
            updater_name="source-owner",
            file_name="v1.pdf",
            file_type=FileType.FILE.value,
            file_level_path="",
            status=KnowledgeFileStatus.SUCCESS.value,
            md5="v1",
        ),
        KnowledgeFile(
            id=1002,
            tenant_id=1,
            knowledge_id=10,
            user_id=1,
            user_name="source-owner",
            updater_id=1,
            updater_name="source-owner",
            file_name="v2.pdf",
            file_type=FileType.FILE.value,
            file_level_path="",
            status=KnowledgeFileStatus.SUCCESS.value,
            md5="v2",
            reference_document_id=501,
            entry_type=KnowledgeFileEntryType.MANAGER.value,
            entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
        ),
    ]
    runtime_session.add_all(source_files)
    distribution_entry = KnowledgeFile(
        id=2001,
        tenant_id=1,
        knowledge_id=30,
        user_id=1,
        user_name="publisher",
        updater_id=1,
        updater_name="publisher",
        file_name="published-v2.pdf",
        file_type=FileType.FILE.value,
        file_level_path="",
        status=KnowledgeFileStatus.SUCCESS.value,
        reference_document_id=501,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
    )
    runtime_session.add(distribution_entry)
    document = KnowledgeDocument(
        id=501,
        tenant_id=1,
        knowledge_id=10,
        file_level_path="",
        level=0,
        primary_version_id=702,
    )
    versions = [
        KnowledgeDocumentVersion(
            id=701,
            document_id=501,
            knowledge_file_id=1001,
            version_no=1,
            is_primary=False,
        ),
        KnowledgeDocumentVersion(
            id=702,
            document_id=501,
            knowledge_file_id=1002,
            version_no=2,
            is_primary=True,
        ),
    ]
    runtime_session.add(document)
    runtime_session.add_all(versions)
    batch = KnowledgeMigrationBatch(
        batch_no="batch-runtime",
        request_id="runtime",
        operator_id=1,
        operator_name="admin",
        source_selection_snapshot=[],
        source_spaces_snapshot=[
            {"id": 10, "name": "来源库", "model": "embedding-model"}
        ],
        target_space_id=20,
        target_space_name="目标库",
        status="running",
    )
    runtime_session.add(batch)
    await runtime_session.flush()
    unit = KnowledgeMigrationUnit(
        batch_id=int(batch.id),
        unit_key="document:501",
        unit_type="version_chain",
        source_document_id=501,
        target_document_id=501,
        source_space_id=10,
        source_space_name="来源库",
        folder_mapping_snapshot=[],
        status="running",
    )
    runtime_session.add(unit)
    await runtime_session.flush()
    for source, version in zip(source_files, versions, strict=True):
        runtime_session.add(
            KnowledgeMigrationFile(
                batch_id=int(batch.id),
                unit_id=int(unit.id),
                source_file_id=int(source.id),
                source_document_id=501,
                source_version_id=int(version.id),
                source_version_no=version.version_no,
                is_primary=version.is_primary,
                source_space_id=10,
                source_space_name="来源库",
                source_file_name=source.file_name,
                target_space_id=20,
                target_space_name="目标库",
                target_file_name=source.file_name,
                status="running",
            )
        )
    await runtime_session.commit()

    repository = KnowledgeMigrationRuntimeRepositoryImpl(runtime_session)
    prepared = await repository.prepare_target_rows(int(unit.id))
    target_ids = {
        int(item.control.source_file_id): int(item.target.id)
        for item in prepared.files
    }

    await repository.activate_switch(int(unit.id))

    migrated_document = (
        await runtime_session.exec(
            select(KnowledgeDocument).where(KnowledgeDocument.id == 501)
        )
    ).one()
    migrated_versions = list(
        (
            await runtime_session.exec(
                select(KnowledgeDocumentVersion)
                .where(KnowledgeDocumentVersion.document_id == 501)
                .order_by(KnowledgeDocumentVersion.version_no)
            )
        ).all()
    )
    assert migrated_document.knowledge_id == 20
    assert migrated_document.primary_version_id == 702
    assert [row.id for row in migrated_versions] == [701, 702]
    assert [row.knowledge_file_id for row in migrated_versions] == [
        target_ids[1001],
        target_ids[1002],
    ]
    manager_entries = list(
        (
            await runtime_session.exec(
                select(KnowledgeFile).where(
                    KnowledgeFile.reference_document_id == 501,
                    KnowledgeFile.entry_type
                    == KnowledgeFileEntryType.MANAGER.value,
                    KnowledgeFile.entry_status
                    == KnowledgeFileEntryStatus.ACTIVE.value,
                )
            )
        ).all()
    )
    assert [entry.id for entry in manager_entries] == [target_ids[1002]]
    published = (
        await runtime_session.exec(
            select(KnowledgeFile).where(KnowledgeFile.id == 2001)
        )
    ).one()
    assert published.reference_document_id == 501
    assert published.entry_status == KnowledgeFileEntryStatus.ACTIVE.value

    await repository.cleanup_source_rows(int(unit.id))
    remaining_source_ids = (
        await runtime_session.exec(
            select(KnowledgeFile.id).where(
                KnowledgeFile.id.in_({1001, 1002})
            )
        )
    ).all()
    assert remaining_source_ids == []
