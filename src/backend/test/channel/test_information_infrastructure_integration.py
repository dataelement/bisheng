from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.information_article_sync_state import InformationArticleSyncState
from bisheng.channel.domain.repositories.implementations.information_article_sync_state_repository_impl import (
    InformationArticleSyncStateRepositoryImpl,
)
from bisheng.core.config.settings import CeleryConf, IntelligenceCenterConf
from bisheng.core.database import tenant_filter
from bisheng.core.database.model_discovery import discover_sqlmodel_module_names
from bisheng.tenant.domain.services import tenant_mount_service


def test_public_state_table_has_no_tenant_or_api_key_columns():
    columns = set(InformationArticleSyncState.__table__.columns.keys())

    assert columns == {
        "source_id",
        "article_cursor_create_time",
        "processed_remote_sync_at",
        "processed_article_list_updated_at",
        "create_time",
        "update_time",
    }


def test_public_state_model_is_in_schema_bootstrap_discovery():
    assert "bisheng.channel.domain.models.information_article_sync_state" in discover_sqlmodel_module_names()


def test_channel_info_source_is_public_and_not_unmount_migrated():
    assert "channel_info_source" in tenant_filter._EXCLUDED_TABLES
    assert "channel_info_source" not in tenant_mount_service._UNMOUNT_MIGRATE_TABLES


def test_information_defaults_and_custom_schedule_override_are_preserved():
    runtime = IntelligenceCenterConf()
    custom = {
        "dispatch_information_subscription_reconcile": {
            "task": "custom.subscription.task",
            "schedule": 123.0,
        }
    }
    celery = CeleryConf(beat_schedule=custom)

    assert runtime.information_initial_article_limit == 20
    assert runtime.information_subscription_auto_unsubscribe_enabled is True
    assert runtime.information_knowledge_delivery_enabled is True
    assert celery.beat_schedule["dispatch_information_subscription_reconcile"]["task"] == "custom.subscription.task"
    assert celery.beat_schedule["dispatch_information_subscription_reconcile"]["schedule"] == 123.0


def test_legacy_information_beat_entries_are_removed_without_touching_custom_tasks():
    legacy = {
        "sync_information_article": {
            "task": "bisheng.worker.information.article.sync_information_article",
            "schedule": 42.0,
        },
        "sync_information_article_hourly": {
            "task": "bisheng.worker.information.article.sync_information_article",
            "schedule": 84.0,
        },
        "reconcile_information_subscriptions": {
            "task": "bisheng.worker.information.reconcile.reconcile_all_tenants",
            "schedule": 126.0,
        },
        "custom_task": {"task": "custom.task", "schedule": 168.0},
    }

    celery = CeleryConf(beat_schedule=legacy)

    assert "sync_information_article" not in celery.beat_schedule
    assert "sync_information_article_hourly" not in celery.beat_schedule
    assert "reconcile_information_subscriptions" not in celery.beat_schedule
    assert celery.beat_schedule["custom_task"] == {"task": "custom.task", "schedule": 168.0}


async def test_state_repository_boundary_and_compare_and_swap(tmp_path):
    database_path = tmp_path / "information-state.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(InformationArticleSyncState.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        repository = InformationArticleSyncStateRepositoryImpl(session)
        initial = await repository.create_initial_boundary_if_absent("source-A", 100)
        assert initial.article_cursor_create_time == 100
        assert await repository.commit_if_unchanged("source-A", initial, 200, 10, 20) is True

        stale = InformationArticleSyncState(source_id="source-A", article_cursor_create_time=100)
        assert await repository.commit_if_unchanged("source-A", stale, 300, 30, 40) is False
        current = await repository.find_by_source_id("source-A")
        assert current.article_cursor_create_time == 200
        assert current.processed_remote_sync_at == 10
    await engine.dispose()


async def test_state_repository_cas_refreshes_identity_map_before_compare(tmp_path):
    database_path = tmp_path / "information-state-cas.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(InformationArticleSyncState.__table__.create)

    async with AsyncSession(engine, expire_on_commit=False) as first_session:
        first_repository = InformationArticleSyncStateRepositoryImpl(first_session)
        stale = await first_repository.create_initial_boundary_if_absent("source-A", 100)
        await first_session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as second_session:
            await second_session.exec(
                update(InformationArticleSyncState)
                .where(InformationArticleSyncState.source_id == "source-A")
                .values(article_cursor_create_time=200, processed_remote_sync_at=10)
            )
            await second_session.commit()

        committed = await first_repository.commit_if_unchanged(
            "source-A",
            stale,
            300,
            30,
            40,
        )
        assert committed is False

    async with AsyncSession(engine, expire_on_commit=False) as verify_session:
        current = await verify_session.get(InformationArticleSyncState, "source-A")
        assert current.article_cursor_create_time == 200
        assert current.processed_remote_sync_at == 10
    await engine.dispose()
