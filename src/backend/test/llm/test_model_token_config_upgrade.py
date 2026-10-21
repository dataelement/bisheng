"""Run with --confcutdir=test/llm; use real SQLite transactions and JSON columns."""

import importlib.util
import json
import sys
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import JSON, Column
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

source = Path(__file__).parents[2] / "bisheng/llm/domain/services/model_token_config_upgrade.py"
spec = importlib.util.spec_from_file_location("token_upgrade_under_test", source)
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class Provider(SQLModel, table=True):
    id: int = Field(primary_key=True)
    tenant_id: int
    type: str
    limit_flag: bool = True
    limit: int = 50


class Model(SQLModel, table=True):
    id: int = Field(primary_key=True)
    tenant_id: int
    server_id: int
    model_type: str = "llm"
    config: dict | None = Field(default=None, sa_column=Column(JSON))
    status: int = 0
    name: str = "original-name"


@pytest.mark.parametrize("provider,key", [("qwen", "max_tokens"), ("qianfan", "max_tokens"), ("ollama", "num_ctx")])
@pytest.mark.parametrize("serialized", [True, False])
def test_legacy_priority_is_preserved_and_transform_is_idempotent(provider, key, serialized):
    params = {key: 999, "temperature": 0.2}
    old = {"max_tokens": 2048, "enable_web_search": True, "user_kwargs": json.dumps(params) if serialized else params}
    updated = upgrade.transform_token_config(old, provider)
    assert json.loads(updated["user_kwargs"]) == {key: 2048, "temperature": 0.2}
    assert updated["enable_web_search"] is True
    assert "max_tokens" not in updated
    assert old["max_tokens"] == 2048
    assert upgrade.transform_token_config(updated, provider) is None


@pytest.mark.parametrize("limit", [None, "", 0])
def test_inactive_legacy_field_preserves_existing_advanced_value(limit):
    assert upgrade.transform_token_config({"max_tokens": limit, "user_kwargs": '{"max_tokens":256}'}, "openai") == {
        "user_kwargs": '{"max_tokens":256}'
    }


@pytest.mark.parametrize(
    "config",
    [
        {"max_tokens": 10, "user_kwargs": "{bad"},
        {"max_tokens": 10, "user_kwargs": "[]"},
        {"max_tokens": 0, "user_kwargs": '{"temperature":NaN}'},
        {"max_tokens": -1},
        {"max_tokens": True},
        {"max_tokens": 2.5},
    ],
)
def test_invalid_saved_values_require_review(config):
    with pytest.raises(ValueError):
        upgrade.transform_token_config(config, "openai")


@pytest_asyncio.fixture
async def database(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "models.db"))
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def get_session():
        async with sessions() as session:
            yield session

    for name in ["bisheng", "bisheng.core", "bisheng.core.context", "bisheng.llm", "bisheng.llm.domain"]:
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setitem(sys.modules, "bisheng.core.database", SimpleNamespace(get_async_db_session=get_session))
    monkeypatch.setitem(sys.modules, "bisheng.core.context.tenant", SimpleNamespace(bypass_tenant_filter=nullcontext))
    monkeypatch.setitem(sys.modules, "bisheng.llm.domain.models", SimpleNamespace(LLMModel=Model, LLMServer=Provider))
    async with sessions() as session:
        session.add_all(
            [
                Provider(id=1, tenant_id=1, type="qwen"),
                Provider(id=2, tenant_id=2, type="ollama"),
                Model(
                    id=11, tenant_id=1, server_id=1, config={"max_tokens": 200, "user_kwargs": '{"temperature":0.2}'}
                ),
                Model(id=22, tenant_id=2, server_id=2, config={"max_tokens": 300}),
                Model(id=33, tenant_id=1, server_id=1, model_type="embedding", config={"max_tokens": 400}),
            ]
        )
        await session.commit()
    yield sessions
    await engine.dispose()


async def snapshots(sessions):
    async with sessions() as session:
        models = (await session.exec(select(Model).order_by(Model.id))).all()
        providers = (await session.exec(select(Provider).order_by(Provider.id))).all()
        return [m.model_dump() for m in models], [p.model_dump() for p in providers]


async def test_dry_run_scope_backup_apply_rerun_and_restore(database, tmp_path):
    original_models, original_providers = await snapshots(database)
    preview = await upgrade.migrate_model_token_configs(tenant_ids=[1])
    assert preview["planned"] == 1 and preview["migrated"] == 0
    assert (await snapshots(database))[0] == original_models
    backup = tmp_path / "before.json"
    result = await upgrade.migrate_model_token_configs(apply=True, tenant_ids=[1], backup_file=str(backup))
    assert result["migrated"] == 1
    assert backup.stat().st_mode & 0o777 == 0o600
    migrated, providers = await snapshots(database)
    assert providers == original_providers
    assert migrated[0] == {**original_models[0], "config": {"user_kwargs": '{"temperature": 0.2, "max_tokens": 200}'}}
    assert migrated[1:] == original_models[1:]
    assert (await upgrade.migrate_model_token_configs(apply=True, tenant_ids=[1], backup_file=str(backup)))[
        "planned"
    ] == 0
    restored = await upgrade.migrate_model_token_configs(
        apply=True, tenant_ids=[1], restore_backup=str(backup), backup_file=str(tmp_path / "restore-before.json")
    )
    assert restored["migrated"] == 1
    assert await snapshots(database) == (original_models, original_providers)


async def test_invalid_row_blocks_whole_batch_and_leaves_no_backup(database, tmp_path):
    async with database() as session:
        model = await session.get(Model, 22)
        model.config = {"max_tokens": 20, "user_kwargs": "[invalid"}
        session.add(model)
        await session.commit()
    before = await snapshots(database)
    path = tmp_path / "blocked.json"
    report = await upgrade.migrate_model_token_configs(apply=True, backup_file=str(path))
    assert report["errors"] and report["migrated"] == 0
    assert not path.exists()
    assert await snapshots(database) == before


async def test_existing_backup_blocks_writes(database, tmp_path):
    before = await snapshots(database)
    backup = tmp_path / "existing.json"
    backup.write_text("existing backup")
    with pytest.raises(FileExistsError):
        await upgrade.migrate_model_token_configs(apply=True, backup_file=str(backup))
    assert await snapshots(database) == before
    assert backup.read_text() == "existing backup"


async def test_restore_preserves_later_edits_and_new_rows(database, tmp_path):
    backup = tmp_path / "before.json"
    await upgrade.migrate_model_token_configs(apply=True, backup_file=str(backup))
    async with database() as session:
        model = await session.get(Model, 11)
        model.config = {"user_kwargs": '{"max_tokens":999}'}
        session.add(model)
        session.add(Model(id=44, tenant_id=1, server_id=1, config={"user_kwargs": "{}"}))
        await session.commit()
    before = await snapshots(database)
    result = await upgrade.migrate_model_token_configs(
        apply=True, restore_backup=str(backup), backup_file=str(tmp_path / "restore-blocked.json")
    )
    assert result["errors"] and result["migrated"] == 0
    assert await snapshots(database) == before


async def test_database_failure_rolls_back_and_keeps_recovery_backup(database, tmp_path, monkeypatch):
    before = await snapshots(database)

    async def fail_commit(self):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    path = tmp_path / "recovery.json"
    with pytest.raises(RuntimeError):
        await upgrade.migrate_model_token_configs(apply=True, backup_file=str(path))
    assert await snapshots(database) == before
    assert len(json.loads(path.read_text())["rows"]) == 2
