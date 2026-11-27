import copy

import pytest

from bisheng.finetune.domain.services.legacy_dataset import classify_records, convert_legacy_records
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter


def test_conversion_preserves_system_history_input_and_original():
    rows = [
        {
            "instruction": "question",
            "input": "context",
            "output": "answer",
            "system": "policy",
            "history": [["old q", "old a"]],
        }
    ]
    original = copy.deepcopy(rows)
    assert classify_records(rows) == "legacy"
    converted = convert_legacy_records(rows)
    assert rows == original
    assert converted[0]["messages"] == [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "old q"},
        {"role": "assistant", "content": "old a"},
        {"role": "user", "content": "question\n\ncontext"},
        {"role": "assistant", "content": "answer"},
    ]
    assert classify_records(converted) == "text"


@pytest.mark.parametrize(
    "changes", [{"input": 12}, {"history": [["incomplete"]]}, {"output": ""}, {"conversations": []}]
)
def test_conversion_rejects_invalid_rows_with_position(changes):
    with pytest.raises(ValueError, match="Record 0"):
        convert_legacy_records([{"instruction": "q", "output": "a", **changes}])


def test_mixed_formats_are_not_silently_reclassified():
    with pytest.raises(ValueError, match="mixed"):
        classify_records(
            [
                {"instruction": "q", "output": "a"},
                {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]},
            ]
        )


async def test_catalog_transaction_paging_and_deleted_version_cannot_be_readded(monkeypatch, isolated_tenant_filter):
    from contextlib import asynccontextmanager

    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.finetune.domain.models.dataset import FinetuneDataset
    from bisheng.finetune.domain.models.preset_train import PresetTrain
    from bisheng.finetune.domain.repositories import dataset_catalog as module
    from bisheng.finetune.domain.repositories.dataset_catalog import DatasetCatalogRepository as repo

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(conn, tables=[PresetTrain.__table__, FinetuneDataset.__table__])
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(module, "get_async_db_session", sessions)
    try:
        with tenant_execution_scope(7):
            version = FinetuneDataset(
                id="version-a", name="first", url="one.json", report={"validated": True}, user_id=3, tenant_id=7
            )
            catalog = PresetTrain(
                id="catalog-a",
                name="first",
                url="one.json",
                data_type="text",
                version_id="version-a",
                user_id="3",
                tenant_id=7,
            )
            await repo.save(catalog, version)
            rows, total = await repo.list(data_type="text", ready_only=True)
            assert total == 1 and rows[0][1].id == "version-a"
            assert (await repo.list(data_type="video_text"))[1] == 0
            from bisheng.core.context.tenant import bypass_tenant_filter

            with bypass_tenant_filter():
                async with sessions() as session:
                    session.add(
                        FinetuneDataset(
                            id="foreign-v",
                            name="foreign",
                            url="foreign.json",
                            report={"validated": True},
                            user_id=4,
                            tenant_id=8,
                        )
                    )
                    session.add(
                        PresetTrain(
                            id="bad-link",
                            name="own-catalog",
                            url="foreign.json",
                            version_id="foreign-v",
                            data_type="text",
                            tenant_id=7,
                        )
                    )
                    await session.commit()
            # Even a corrupt cross-tenant relationship cannot become a training option.
            candidates, count = await repo.list(data_type="text", ready_only=True)
            assert count == 1 and [catalog.id for catalog, _ in candidates] == ["catalog-a"]
            await repo.delete("bad-link")
            assert await repo.delete("catalog-a")
            assert (await repo.list())[1] == 0
            assert (await repo.find("version-a", version=True, include_deleted=True)).is_deleted
            with pytest.raises(IntegrityError):
                await repo.save(
                    PresetTrain(id="another", name="duplicate", url="one.json", version_id="version-a", tenant_id=7)
                )
    finally:
        await engine.dispose()


async def test_registration_dry_run_and_apply_skip_deleted_versions(monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.finetune.domain.repositories.dataset_catalog import DatasetCatalogRepository as repo
    from bisheng.finetune.domain.services.datasets import DatasetService
    from scripts.register_f025_dataset_catalog import register

    version = SimpleNamespace(
        id="v1",
        name="historic",
        url="historic.json",
        user_id=3,
        report={"data_type": "text", "sha256": "hash"},
        create_time=datetime.now(),
    )
    stored = {}

    async def catalogs(after, limit=100):
        return []

    async def versions(after, limit=100):
        return [version] if not after else []

    async def find(identifier, version=False, include_deleted=False):
        return stored.get(identifier)

    async def save(row, version=None):
        stored[row.version_id] = row
        return row

    save_mock = AsyncMock(side_effect=save)
    monkeypatch.setattr(repo, "historical_catalogs", catalogs)
    monkeypatch.setattr(repo, "historical_versions", versions)
    monkeypatch.setattr(repo, "find", find)
    monkeypatch.setattr(repo, "save", save_mock)
    monkeypatch.setattr(
        DatasetService,
        "read_original",
        AsyncMock(
            return_value=(
                [{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}],
                "hash",
            )
        ),
    )
    assert not (await register(7))["errors"]
    save_mock.assert_not_called()
    assert not (await register(7, True))["errors"]
    assert stored["v1"].data_type == "text"
    stored["v1"].is_deleted = True
    assert (await register(7, True))["skipped"] == ["v1"]
    save_mock.assert_awaited_once()


def test_ddl_upgrade_is_repeatable_and_downgrade_retains_original_rows():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError

    from bisheng.core.database.alembic.versions import v3_1_0_f025_dataset_catalog as migration

    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE presettrain (id VARCHAR(64) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE finetune (id VARCHAR(64) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO presettrain (id) VALUES ('original')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                assert connection.execute(text("SELECT data_type, source_type, is_deleted FROM presettrain")).one() == (
                    "legacy",
                    "local",
                    0,
                )
                # Multiple historical NULLs are allowed; one non-NULL upload cannot back two jobs.
                connection.execute(text("INSERT INTO finetune (id) VALUES ('old-1'), ('old-2')"))
                connection.execute(text("INSERT INTO finetune (id, transient_upload_id) VALUES ('new', 'upload')"))
                with pytest.raises(IntegrityError):
                    connection.execute(text("INSERT INTO finetune (id, transient_upload_id) VALUES ('dup', 'upload')"))
                migration.downgrade()
                assert [column["name"] for column in inspect(connection).get_columns("presettrain")] == ["id"]
                assert connection.execute(text("SELECT id FROM presettrain")).scalar_one() == "original"
                assert connection.execute(text("SELECT COUNT(*) FROM finetune")).scalar_one() == 3
    finally:
        engine.dispose()
