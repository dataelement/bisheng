from datetime import datetime

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
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import (
    KnowledgeFileSimilarityCandidate,
)
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextOutbox,
)
from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationAttempt,
    KnowledgeMigrationBatch,
    KnowledgeMigrationCheckpoint,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
)
from bisheng.knowledge.domain.models.portal_recommendation_file_projection import (
    PortalRecommendationFileProjection,
)
from bisheng.knowledge.domain.repositories.implementations import (
    knowledge_migration_runtime_repository_impl as runtime_repository_module,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_runtime_repository_impl import (
    KnowledgeMigrationRuntimeRepositoryImpl,
)
from bisheng.share_link.domain.models.share_link import ShareLink


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
        KnowledgeFileSimilarityCandidate.__table__,
        KnowledgeFulltextOutbox.__table__,
        PortalRecommendationFileProjection.__table__,
        ShareLink.__table__,
        KnowledgeDocument.__table__,
        KnowledgeDocumentVersion.__table__,
        KnowledgeMigrationBatch.__table__,
        KnowledgeMigrationUnit.__table__,
        KnowledgeMigrationFile.__table__,
        KnowledgeMigrationAttempt.__table__,
    ]
    async with engine.begin() as connection:
        for table in tables:
            await connection.run_sync(table.create)
    session = AsyncSession(engine, expire_on_commit=False)
    yield session
    await session.close()
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_switch_commit", [False, True])
async def test_version_chain_switch_preserves_document_and_version_ids(
    runtime_session,
    monkeypatch,
    fail_switch_commit,
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
        checkpoint=KnowledgeMigrationCheckpoint.PLANNED.value,
        attempt_count=1,
    )
    runtime_session.add(unit)
    await runtime_session.flush()
    attempt = KnowledgeMigrationAttempt(
        batch_id=int(batch.id),
        unit_id=int(unit.id),
        round_no=1,
        attempt_no=1,
        execution_token="runtime-token",
        start_checkpoint=KnowledgeMigrationCheckpoint.PLANNED.value,
        started_at=datetime.now(),
    )
    runtime_session.add(attempt)
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
    unit_id = int(unit.id)
    prepared = await repository.prepare_target_rows(
        unit_id,
        attempt_id=int(attempt.id),
        execution_token="runtime-token",
    )
    target_ids = {int(item.control.source_file_id): int(item.target.id) for item in prepared.files}
    assert target_ids == {1001: 1001, 1002: 1002}

    if fail_switch_commit:

        async def _fail_commit():
            raise RuntimeError("injected commit failure")

        monkeypatch.setattr(runtime_session, "commit", _fail_commit)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await repository.activate_switch(
                unit_id,
                attempt_id=int(attempt.id),
                execution_token="runtime-token",
            )
        await runtime_session.rollback()
        unchanged_document = await runtime_session.get(
            KnowledgeDocument,
            501,
        )
        unchanged_versions = list(
            (
                await runtime_session.exec(
                    select(KnowledgeDocumentVersion)
                    .where(
                        KnowledgeDocumentVersion.document_id == 501
                    )
                    .order_by(KnowledgeDocumentVersion.version_no)
                )
            ).all()
        )
        unchanged_unit = await runtime_session.get(
            KnowledgeMigrationUnit,
            unit_id,
        )
        assert unchanged_document is not None
        assert unchanged_document.knowledge_id == 10
        assert [
            row.knowledge_file_id for row in unchanged_versions
        ] == [1001, 1002]
        assert unchanged_unit is not None
        assert (
            unchanged_unit.checkpoint
            == KnowledgeMigrationCheckpoint.PLANNED.value
        )
        return

    await repository.activate_switch(
        int(unit.id),
        attempt_id=int(attempt.id),
        execution_token="runtime-token",
    )

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
    assert migrated_document.content_generation == 0
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
    assert published.desired_content_generation == 0
    assert published.projection_status == "pending"
    assert manager_entries[0].desired_content_generation == 0
    assert manager_entries[0].projection_status == "pending"
    switched_unit = await runtime_session.get(
        KnowledgeMigrationUnit,
        int(unit.id),
    )
    assert switched_unit is not None
    assert switched_unit.checkpoint == KnowledgeMigrationCheckpoint.DB_SWITCHED.value
    control_checkpoints = (
        await runtime_session.exec(
            select(KnowledgeMigrationFile.checkpoint).where(KnowledgeMigrationFile.unit_id == int(unit.id))
        )
    ).all()
    assert control_checkpoints == [
        KnowledgeMigrationCheckpoint.DB_SWITCHED.value,
        KnowledgeMigrationCheckpoint.DB_SWITCHED.value,
    ]

    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.knowledge.domain.contracts.shared_space_storage import SharedContentChunk
    from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_shared_projection import (
        KnowledgeMigrationSharedProjection,
    )
    from bisheng.knowledge.domain.services.file_migration.executor import MigrationExecutionUnit
    from test.fakes.shared_storage_fakes import FakeSharedSpaceStorageWriter

    @asynccontextmanager
    async def session_factory():
        yield runtime_session

    writer = FakeSharedSpaceStorageWriter()
    writer.schema_spec = SimpleNamespace(embedding_model_id="7")
    writer.content[(1, 501, 702, 0)] = {0: {"text": "canonical content", "vector": [0.1, 0.2]}}
    loader = AsyncMock(return_value=[SharedContentChunk(chunk_index=0, text="canonical content")])
    adapter = KnowledgeMigrationSharedProjection(
        session_factory=session_factory, components_factory=lambda _: (writer, None), content_loader=loader,
    )
    execution = MigrationExecutionUnit(unit_id=unit_id, attempt_id=int(attempt.id), execution_token="runtime-token")
    real_update = writer.update_membership
    writer.update_membership = AsyncMock(side_effect=RuntimeError("ES unavailable"))
    with pytest.raises(RuntimeError, match="ES unavailable"):
        await adapter.converge_unit(execution)
    assert await runtime_session.get(KnowledgeFile, 1001) is not None
    assert (await runtime_session.get(KnowledgeMigrationUnit, unit_id)).checkpoint == "db_switched"
    writer.update_membership = real_update
    await adapter.converge_unit(execution)
    assert writer.membership_of(1, 501) == (20, 30)
    loader.assert_not_awaited()
    assert writer.content[(1, 501, 702, 0)][0]["vector"] == [0.1, 0.2]
    calls = list(writer.calls)
    await adapter.converge_unit(execution)
    assert writer.calls == calls
    assert "delete_content" not in calls

    # Resume confirmed overwrite cleanup independently of destination projection.
    unit.overwrite_snapshot = {"document": {"id": 801}}
    runtime_session.add(unit)
    await runtime_session.commit()
    writer.content[(1, 801, 901, 0)] = {0: {"text": "obsolete"}}
    delete_content = writer.delete_content
    writer.delete_content = AsyncMock(side_effect=RuntimeError("Milvus unavailable"))
    with pytest.raises(RuntimeError, match="Milvus unavailable"):
        await adapter.converge_unit(execution)
    assert await runtime_session.get(KnowledgeFile, 1001) is not None
    writer.delete_content = delete_content
    await adapter.converge_unit(execution)
    assert not any(key[1] == 801 for key in writer.content)
    assert writer.membership_of(1, 501) == (20, 30)

    await repository.cleanup_source_rows(int(unit.id))
    remaining_source_ids = (
        await runtime_session.exec(
            select(KnowledgeFile.id).where(
                KnowledgeFile.id.in_({1001, 1002})
            )
        )
    ).all()
    assert set(remaining_source_ids) == {1001, 1002}


async def test_preserve_link_creates_planned_directory_and_records_switch(runtime_session, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from bisheng.knowledge.domain.services import migration_preserve_link_operations as link_module

    monkeypatch.setattr(runtime_repository_module, "User", RuntimeUser)
    runtime_session.add(RuntimeUser(user_id=1, user_name="owner"))
    runtime_session.add(Knowledge(id=20, name="target", user_id=1, type=3, model="old-model"))
    runtime_session.add(KnowledgeFile(id=42, knowledge_id=20, user_id=1, user_name="owner",
        updater_id=1, updater_name="owner", file_name="destination", file_type=FileType.DIR.value,
        file_level_path="", level=0, status=2))
    batch = KnowledgeMigrationBatch(batch_no="link-folder", request_id="link-folder", operator_id=1,
        operator_name="admin", target_space_id=20, target_space_name="target", target_folder_id=42,
        preserve_link=True, status="running")
    runtime_session.add(batch)
    await runtime_session.flush()
    unit = KnowledgeMigrationUnit(batch_id=batch.id, unit_key="document:91", unit_type="version_chain",
        source_document_id=91, source_space_id=10, source_space_name="source", status="running", attempt_count=1,
        folder_mapping_snapshot=[{"source_folder_id": 11, "source_name": "child", "action": "planned"}])
    runtime_session.add(unit)
    await runtime_session.flush()
    attempt = KnowledgeMigrationAttempt(batch_id=batch.id, unit_id=unit.id, round_no=1, attempt_no=1,
        execution_token="link-token", start_checkpoint="planned", started_at=datetime.now())
    row = KnowledgeMigrationFile(batch_id=batch.id, unit_id=unit.id, source_file_id=100,
        source_document_id=91, source_version_no=1, is_primary=True, source_space_id=10,
        source_space_name="source", source_file_name="a.pdf", target_space_id=20, target_space_name="target",
        target_file_name="a.pdf")
    runtime_session.add_all([attempt, row])
    source_document = KnowledgeDocument(id=91, knowledge_id=10, primary_version_id=1)
    source_version = KnowledgeDocumentVersion(
        id=1, document_id=91, knowledge_file_id=100, version_no=1, is_primary=True
    )
    runtime_session.add_all([source_document, source_version])
    await runtime_session.commit()
    repository = KnowledgeMigrationRuntimeRepositoryImpl(runtime_session)
    args = {"attempt_id": attempt.id, "execution_token": "link-token"}
    folders, _, _ = await repository.prepare_preserve_link_folders(unit.id, **args)
    assert len(folders) == 1 and folders[0].file_level_path == "/42"
    created_id = folders[0].id
    retried, _, _ = await repository.prepare_preserve_link_folders(unit.id, **args)
    assert [f.id for f in retried] == [created_id]

    @asynccontextmanager
    async def session_factory():
        yield runtime_session

    monkeypatch.setattr(link_module, "get_async_db_session", session_factory)
    operations = link_module.PreserveLinkMigrationOperations(publish_service_factory=None)
    context = await operations._load_publish_context(unit.id)
    assert context["target_file_level_path"] == f"/42/{created_id}"
    assert context["target_level"] == 2
    await repository.record_preserve_link_result(unit.id,
        SimpleNamespace(document_id=91, publish_entry_id=777), **args)
    assert unit.checkpoint == row.checkpoint == "db_switched"
    assert row.target_file_id == 100
    assert row.target_resource_manifest["publish_entry_id"] == 777
    source_identity = dict(row.source_resource_manifest["shared_content"])
    runtime_session.add(KnowledgeDocument(id=92, knowledge_id=20, primary_version_id=1))
    await runtime_session.delete(source_document)
    source_version.document_id = 92
    runtime_session.add(source_version)
    runtime_session.add(
        KnowledgeFile(
            id=100,
            knowledge_id=20,
            user_id=1,
            user_name="owner",
            updater_id=1,
            updater_name="owner",
            file_name="a.pdf",
            reference_document_id=92,
            entry_type="manager",
            entry_status="active",
            status=2,
        )
    )
    await runtime_session.commit()
    await repository.record_preserve_link_result(unit.id,
        SimpleNamespace(document_id=92, publish_entry_id=777), **args)
    # 模拟发布已提交但迁移目标清单被补偿清空；来源身份仍可恢复。
    row.target_resource_manifest = None
    await repository._snapshot_source_content(unit, [row])
    assert row.target_resource_manifest["source_content"] == source_identity
    plan = await repository.shared_projection_plan(unit.id, **args)
    assert plan["document_id"] == 92
    assert plan["deleted_document_ids"] == [91]
    runtime_session.add(KnowledgeDocument(id=91, knowledge_id=10, primary_version_id=1))
    await runtime_session.commit()
    with pytest.raises(RuntimeError, match="still in use"):
        await repository.shared_projection_plan(unit.id, **args)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate_primary", [True, False])
async def test_overwrite_revalidates_full_graph_before_deletion(
    runtime_session,
    mutate_primary,
):
    target_files = [
        KnowledgeFile(
            id=3001,
            tenant_id=1,
            knowledge_id=20,
            user_id=1,
            user_name="owner",
            updater_id=1,
            updater_name="owner",
            file_name="old-v1.pdf",
            file_type=FileType.FILE.value,
            file_level_path="",
            status=KnowledgeFileStatus.SUCCESS.value,
            md5="old-v1",
        ),
        KnowledgeFile(
            id=3002,
            tenant_id=1,
            knowledge_id=20,
            user_id=1,
            user_name="owner",
            updater_id=1,
            updater_name="owner",
            file_name="old-v2.pdf",
            file_type=FileType.FILE.value,
            file_level_path="",
            status=KnowledgeFileStatus.SUCCESS.value,
            md5="old-v2",
        ),
    ]
    document = KnowledgeDocument(
        id=801,
        tenant_id=1,
        knowledge_id=20,
        file_level_path="",
        level=0,
        primary_version_id=902,
    )
    versions = [
        KnowledgeDocumentVersion(
            id=901,
            document_id=801,
            knowledge_file_id=3001,
            version_no=1,
            is_primary=False,
        ),
        KnowledgeDocumentVersion(
            id=902,
            document_id=801,
            knowledge_file_id=3002,
            version_no=2,
            is_primary=True,
        ),
    ]
    runtime_session.add_all([*target_files, document, *versions])
    await runtime_session.commit()
    unit = KnowledgeMigrationUnit(
        batch_id=1,
        unit_key="file:4001",
        source_space_id=10,
        source_space_name="来源库",
        overwrite_snapshot={
            "unit_key": "document:801",
            "document": document.model_dump(mode="json"),
            "versions": [version.model_dump(mode="json") for version in versions],
            "target_files": [{"record": file.model_dump(mode="json")} for file in target_files],
        },
    )
    repository = KnowledgeMigrationRuntimeRepositoryImpl(runtime_session)
    if mutate_primary:
        document.primary_version_id = 901
        runtime_session.add(document)
        await runtime_session.commit()
        with pytest.raises(
            RuntimeError,
            match="overwrite target document graph changed",
        ):
            await repository._apply_overwrite_switch(unit)
    else:
        await repository._apply_overwrite_switch(unit)

    remaining_files = (
        await runtime_session.exec(select(KnowledgeFile.id).where(KnowledgeFile.id.in_({3001, 3002})))
    ).all()
    remaining_versions = (
        await runtime_session.exec(
            select(KnowledgeDocumentVersion.id).where(KnowledgeDocumentVersion.document_id == 801)
        )
    ).all()
    remaining_document = await runtime_session.get(
        KnowledgeDocument,
        801,
    )
    if mutate_primary:
        assert set(remaining_files) == {3001, 3002}
        assert set(remaining_versions) == {901, 902}
        assert remaining_document is not None
    else:
        assert remaining_files == []
        assert remaining_versions == []
        assert remaining_document is None
