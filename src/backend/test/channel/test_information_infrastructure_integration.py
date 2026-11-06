from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.repositories.implementations.information_article_sync_state_repository_impl import (
    InformationArticleSyncStateRepositoryImpl,
)
from bisheng.core.config.settings import CeleryConf, IntelligenceCenterConf
from bisheng.core.database import tenant_filter
from bisheng.tenant.domain.services import tenant_mount_service


def test_channel_info_source_contains_public_sync_state_columns():
    columns = set(ChannelInfoSource.__table__.columns.keys())

    assert {
        "article_cursor_create_time",
        "processed_remote_sync_at",
        "processed_article_list_updated_at",
    }.issubset(columns)
    assert "source_id" not in columns


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

    assert runtime.information_initial_article_limit == 36
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
        await connection.run_sync(ChannelInfoSource.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(ChannelInfoSource(id="source-A", source_name="A", source_type="website"))
        await session.commit()
        repository = InformationArticleSyncStateRepositoryImpl(session)
        initial = await repository.find_by_source_id("source-A")
        assert initial is not None
        assert initial.article_cursor_create_time is None
        assert await repository.commit_if_unchanged("source-A", initial, 200, 10, 20) is True

        stale = ChannelInfoSource(id="source-A", source_name="A", source_type="website")
        assert await repository.commit_if_unchanged("source-A", stale, 300, 30, 40) is False
        current = await repository.find_by_source_id("source-A")
        assert current.article_cursor_create_time == 200
        assert current.processed_remote_sync_at == 10
    await engine.dispose()


async def test_state_repository_cas_refreshes_identity_map_before_compare(tmp_path):
    database_path = tmp_path / "information-state-cas.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(ChannelInfoSource.__table__.create)

    async with AsyncSession(engine, expire_on_commit=False) as first_session:
        first_session.add(
            ChannelInfoSource(
                id="source-A",
                source_name="A",
                source_type="website",
                article_cursor_create_time=100,
            )
        )
        await first_session.commit()
        first_repository = InformationArticleSyncStateRepositoryImpl(first_session)
        stale = await first_repository.find_by_source_id("source-A")
        assert stale is not None

        async with AsyncSession(engine, expire_on_commit=False) as second_session:
            await second_session.exec(
                update(ChannelInfoSource)
                .where(ChannelInfoSource.id == "source-A")
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
        current = await verify_session.get(ChannelInfoSource, "source-A")
        assert current.article_cursor_create_time == 200
        assert current.processed_remote_sync_at == 10
    await engine.dispose()
