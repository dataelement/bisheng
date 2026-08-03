import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_source_repository_impl import (
    KnowledgeMigrationSourceRepositoryImpl,
)


def _node(
    *,
    file_id: int,
    space_id: int,
    name: str,
    file_type: int,
    path: str,
    md5: str = "",
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=1,
        knowledge_id=space_id,
        user_id=1,
        user_name="owner",
        updater_id=1,
        updater_name="owner",
        file_name=name,
        file_type=file_type,
        file_level_path=path,
        status=KnowledgeFileStatus.SUCCESS.value,
        md5=md5,
    )


@pytest.mark.asyncio
async def test_source_and_target_scans_use_keyset_pages():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFile.__table__.create)
    session = AsyncSession(engine, expire_on_commit=False)
    session.add_all(
        [
            _node(
                file_id=10,
                space_id=10,
                name="来源目录",
                file_type=FileType.DIR.value,
                path="",
            ),
            _node(
                file_id=11,
                space_id=10,
                name="a.pdf",
                file_type=FileType.FILE.value,
                path="/10",
            ),
            _node(
                file_id=12,
                space_id=10,
                name="b.pdf",
                file_type=FileType.FILE.value,
                path="/10/sub",
            ),
            _node(
                file_id=21,
                space_id=20,
                name="目标目录",
                file_type=FileType.DIR.value,
                path="",
            ),
            _node(
                file_id=22,
                space_id=20,
                name="other.pdf",
                file_type=FileType.FILE.value,
                path="/21",
                md5=" same-md5 ",
            ),
            _node(
                file_id=23,
                space_id=20,
                name="a.pdf",
                file_type=FileType.FILE.value,
                path="/21",
                md5="different",
            ),
        ]
    )
    await session.commit()
    repository = KnowledgeMigrationSourceRepositoryImpl(session)
    selection = [
        {
            "space_id": 10,
            "nodes": [
                {
                    "node_id": 10,
                    "node_type": "folder",
                    "file_level_path": "",
                }
            ],
        }
    ]

    first_page = await repository.expand_selection_page(
        selection,
        after_id=0,
        limit=1,
    )
    second_page = await repository.expand_selection_page(
        selection,
        after_id=int(first_page[-1].id),
        limit=1,
    )
    folders = await repository.list_target_folders_page(
        20,
        parent_path="",
        after_id=0,
        limit=1,
    )
    conflicts = await repository.list_target_conflict_candidates_page(
        20,
        md5_values={"same-md5"},
        parent_paths={"/21"},
        after_id=0,
        limit=10,
    )

    assert [int(row.id) for row in first_page] == [11]
    assert [int(row.id) for row in second_page] == [12]
    assert [int(row.id) for row in folders] == [21]
    assert [int(row.id) for row in conflicts] == [22, 23]

    await session.close()
    await engine.dispose()
