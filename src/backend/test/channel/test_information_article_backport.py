"""Regression coverage for the COFCO article-sync backport and worker wiring."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

import bisheng.worker.information.article as article_worker
from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.repositories.implementations.information_article_sync_state_repository_impl import (
    InformationArticleSyncStateRepositoryImpl,
)
from bisheng.channel.domain.services.article_es_service import ArticleBulkWriteResult
from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.database.alembic.versions import v3_0_0_cofco_923_information_cursor as migration
from bisheng.core.external.bisheng_information_client.client import BishengInformationClient


class ArticleStore:
    def __init__(self):
        self.ids: set[str] = set()
        self.fail_ids: set[str] = set()

    async def mget_existing_ids(self, article_ids):
        return self.ids.intersection(article_ids)

    async def bulk_index_articles_detailed(self, articles_by_id):
        success_ids = set(articles_by_id) - self.fail_ids
        self.ids.update(success_ids)
        return ArticleBulkWriteResult(success_ids, dict.fromkeys(self.fail_ids, "failed"))

    async def refresh_index(self):
        return None


class InformationServer:
    """HTTP double with publication ordering distinct from ingestion ordering."""

    def __init__(self):
        self.today = int(datetime.now(UTC).timestamp())
        self.last_sync_at = self.today - 86400
        self.article_list_updated_at = 1
        self.article_requests: list[tuple[str, dict]] = []
        self.bootstrap_articles = [self.article(f"article-{index}", 500 - index, 2000 - index) for index in range(36)]
        self.new_articles: list[dict] = []

    @staticmethod
    def article(article_id, create_time, publish_date):
        return {
            "id": article_id,
            "title": article_id,
            "original_url": f"https://example.test/{article_id}",
            "create_time": create_time,
            "publish_date": publish_date,
        }

    async def get(self, endpoint, *, params, **kwargs):
        if endpoint.endswith("/subscriptions"):
            assert params == {"page": 1, "page_size": 100}
            data = [
                {
                    "id": "source-A",
                    "source_id": "external-A",
                    "business_type": "website",
                    "name": "A",
                    "last_sync_at": self.last_sync_at,
                    "article_list_updated_at": self.article_list_updated_at,
                }
            ]
            total = 1
        else:
            self.article_requests.append((endpoint, params.copy()))
            if endpoint.endswith("/bootstrap"):
                assert params == {"limit": 36}
                articles = self.bootstrap_articles
                # A historical article outside the latest published set was ingested last.
                watermark = 600
            else:
                assert params["return_information"] == "false"
                assert params["min_create_time"] == 600
                articles = self.new_articles
                watermark = 601
            data = {"articles": articles, "snapshot_max_create_time": watermark}
            total = len(articles)
        return SimpleNamespace(
            status_code=200,
            body={
                "code": 200,
                "data": data,
                "totalCount": total,
                "currentPage": 1,
                "PageSize": params.get("page_size", 36),
            },
        )


async def _run_public_poll():
    fresh = {}
    updated = []

    async def collect(client, source_id, article_ids, detected_at):
        fresh.setdefault(source_id, []).extend(article_ids)

    async def update_display(source_id, article_service):
        updated.append(source_id)

    with (
        patch.object(article_worker, "_dispatch_new_articles", side_effect=collect),
        patch.object(article_worker, "_update_channel_display_time", side_effect=update_display),
    ):
        await article_worker._sync_information_articles_async()
    return fresh, updated


async def test_worker_retries_late_remote_sync_then_bootstraps_and_polls_incrementally(tmp_path):
    """AC-C1, AC-C2: late remote readiness cannot freeze today's local progress."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'articles.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(ChannelInfoSource.__table__.create)

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async with session_factory() as session:
        session.add(ChannelInfoSource(id="source-A", source_name="A", source_type="website", tenant_id=1))
        await session.commit()

    server = InformationServer()
    client = BishengInformationClient(server, IntelligenceCenterConf)
    store = ArticleStore()
    lock = MagicMock(acquire=MagicMock(return_value=True), refresh=MagicMock(return_value=True))
    try:
        with (
            patch("bisheng.core.database.get_async_db_session", session_factory),
            patch("bisheng.channel.domain.services.article_es_service.ArticleEsService", return_value=store),
            patch.object(article_worker, "get_bisheng_information_client", AsyncMock(return_value=client)),
            patch.object(article_worker, "_new_source_lock", return_value=lock),
        ):
            assert await _run_public_poll() == ({}, [])
            assert server.article_requests == []

            server.last_sync_at = server.today
            fresh, updated = await _run_public_poll()
            assert updated == ["source-A"]
            assert len(fresh["source-A"]) == 36
            assert len(store.ids) == 36
            async with session_factory() as session:
                state = await session.get(ChannelInfoSource, "source-A")
                assert state.article_cursor_create_time == 600
                assert state.processed_article_list_updated_at == 1

            assert await _run_public_poll() == ({}, [])
            assert len(server.article_requests) == 1

            server.article_list_updated_at = 2
            server.new_articles = [server.article("new-article", 601, 2001)]
            fresh, updated = await _run_public_poll()
            assert fresh == {"source-A": ["new-article"]}
            assert updated == ["source-A"]
            assert len(store.ids) == 37
            async with session_factory() as session:
                state = await session.get(ChannelInfoSource, "source-A")
                assert state.article_cursor_create_time == 601
                assert state.processed_article_list_updated_at == 2
            assert lock.release.call_count == 4
    finally:
        await engine.dispose()


async def test_failed_bootstrap_keeps_null_cursor_and_retries(tmp_path):
    """AC-C3: partial indexing never commits the bootstrap watermark."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(ChannelInfoSource.__table__.create)

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async with session_factory() as session:
        session.add(ChannelInfoSource(id="source-A", source_name="A", source_type="website", tenant_id=1))
        await session.commit()
    server = InformationServer()
    server.last_sync_at = server.today
    client = BishengInformationClient(server, IntelligenceCenterConf)
    store = ArticleStore()
    store.fail_ids = {"article-0"}
    lock = MagicMock(acquire=MagicMock(return_value=True), refresh=MagicMock(return_value=True))
    try:
        with (
            patch("bisheng.core.database.get_async_db_session", session_factory),
            patch("bisheng.channel.domain.services.article_es_service.ArticleEsService", return_value=store),
            patch.object(article_worker, "get_bisheng_information_client", AsyncMock(return_value=client)),
            patch.object(article_worker, "_new_source_lock", return_value=lock),
        ):
            fresh, updated = await _run_public_poll()
            assert len(fresh["source-A"]) == 35
            assert updated == []
            async with session_factory() as session:
                state = await session.get(ChannelInfoSource, "source-A")
                assert state.article_cursor_create_time is None
                assert state.processed_remote_sync_at is None

            store.fail_ids.clear()
            fresh, updated = await _run_public_poll()
            assert fresh == {"source-A": ["article-0"]}
            assert updated == ["source-A"]
            async with session_factory() as session:
                state = await session.get(ChannelInfoSource, "source-A")
                assert state.article_cursor_create_time == 600
            assert all(endpoint.endswith("/bootstrap") for endpoint, _ in server.article_requests)
    finally:
        await engine.dispose()


async def test_state_cas_rejects_progress_changed_in_another_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cas.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(ChannelInfoSource.__table__.create)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as first:
            first.add(ChannelInfoSource(id="source-A", source_name="A", source_type="website", tenant_id=1))
            await first.commit()
            repo = InformationArticleSyncStateRepositoryImpl(first)
            stale = await repo.find_by_source_id("source-A")
            async with AsyncSession(engine) as second:
                await second.exec(
                    update(ChannelInfoSource)
                    .where(ChannelInfoSource.id == "source-A")
                    .values(
                        article_cursor_create_time=600,
                        processed_remote_sync_at=10,
                    )
                )
                await second.commit()
            assert await repo.commit_if_unchanged("source-A", stale, 700, 20, 30) is False
        async with AsyncSession(engine) as session:
            state = await session.get(ChannelInfoSource, "source-A")
            assert state.article_cursor_create_time == 600
    finally:
        await engine.dispose()


async def test_public_worker_dispatches_new_ids_to_route_task():
    with patch("bisheng.worker.information.knowledge_delivery.route_new_information_articles.apply_async") as dispatch:
        await article_worker._dispatch_new_articles(
            SimpleNamespace(conf=IntelligenceCenterConf()), "source-A", ["new-article"], 100
        )
    dispatch.assert_called_once_with(args=("source-A", ["new-article"], 100))


async def test_public_worker_does_not_read_or_write_source_without_lock():
    lock = MagicMock(acquire=MagicMock(return_value=False), redis_available=True)
    with (
        patch.object(article_worker, "_new_source_lock", return_value=lock),
        patch("bisheng.core.database.get_async_db_session") as session,
    ):
        await article_worker._sync_one_source(SimpleNamespace(), SimpleNamespace(id="source-A"))
    session.assert_not_called()
    lock.release.assert_not_called()


def test_existing_source_table_upgrade_adds_nullable_progress_and_is_idempotent():
    """AC-C5: old sources retain null progress and bootstrap after schema upgrade."""
    engine = create_engine("sqlite://")
    metadata = MetaData()
    legacy = Table("channel_info_source", metadata, Column("id", String(36), primary_key=True))
    try:
        with engine.begin() as connection:
            metadata.create_all(connection)
            connection.execute(legacy.insert().values(id="source-A"))
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
                migration.upgrade()
            columns = {column["name"]: column for column in inspect(connection).get_columns(legacy.name)}
            assert set(migration._COLUMNS).issubset(columns)
            assert all(columns[name]["nullable"] for name in migration._COLUMNS)
            upgraded = Table(legacy.name, MetaData(), autoload_with=connection)
            row = connection.execute(upgraded.select()).mappings().one()
            assert row["id"] == "source-A"
            assert all(row[name] is None for name in migration._COLUMNS)
    finally:
        engine.dispose()
