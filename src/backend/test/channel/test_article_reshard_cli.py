"""AC-18, AC-19, AC-25, AC-27: service configuration and CLI lifetime."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import repartition_channel_articles as entry
from test.channel.article_reshard_fake import FakeEs


def test_help_and_mode_validation():
    with pytest.raises(SystemExit) as code:
        entry.parser().parse_args(["--help"])
    assert code.value.code == 0
    with pytest.raises(SystemExit):
        entry.parser().parse_args(["--apply", "--status"])


async def test_default_uses_shared_configuration_and_closes_context(monkeypatch):
    from bisheng.common.services import config_service
    from bisheng.core.context import manager
    from bisheng.core.search.elasticsearch import manager as es_manager

    settings = SimpleNamespace(channel_article_index=SimpleNamespace(number_of_shards=5))
    monkeypatch.setattr(config_service, "settings", settings)
    initialize, close = AsyncMock(), AsyncMock()
    monkeypatch.setattr(manager, "initialize_app_context", initialize)
    monkeypatch.setattr(manager, "close_app_context", close)
    es = FakeEs()
    monkeypatch.setattr(es_manager, "get_es_connection", AsyncMock(return_value=es))
    result = await entry.run(entry.parser().parse_args(["--run-id", "test"]))
    assert result["target_shards"] == 5 and es.writes == []
    initialize.assert_awaited_once_with(config=settings, instance_role="maintenance")
    close.assert_awaited_once()


def test_normal_context_uses_search_es_even_when_telemetry_is_different():
    from bisheng.core.config.settings import Settings
    from bisheng.core.context.manager import ApplicationContextManager

    settings = Settings(
        database_url="sqlite://",
        redis_url="redis://localhost:6379/0",
        vector_stores={"elasticsearch": {"url": "http://search.invalid:9200"}},
        telemetry_elasticsearch={"url": "http://telemetry.invalid:9200"},
        openfga={"enabled": False},
    )
    context = ApplicationContextManager()
    context._register_default_contexts(settings, instance_role="maintenance")
    assert context.get_context("elasticsearch").es_hosts == "http://search.invalid:9200"
    assert context.get_context("statistics_elasticsearch").es_hosts == "http://telemetry.invalid:9200"


def test_batch_size_has_a_small_default_and_accepts_an_override():
    assert entry.parser().parse_args([]).batch_size == 5
    assert entry.parser().parse_args(["--batch-size", "1"]).batch_size == 1


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "true", "invalid"])
def test_invalid_batch_size_exits_before_initializing_runtime(monkeypatch, value):
    from unittest.mock import Mock

    run = Mock()
    monkeypatch.setattr(entry, "run", run)
    with pytest.raises(SystemExit) as error:
        entry.main(["--batch-size", value])
    assert error.value.code == 2
    run.assert_not_called()


async def test_cli_passes_batch_size_to_the_migration(monkeypatch):
    from bisheng.common.services import config_service
    from bisheng.core.context import manager
    from bisheng.core.search.elasticsearch import manager as es_manager

    settings = SimpleNamespace(channel_article_index=SimpleNamespace(number_of_shards=3))
    es = FakeEs()
    monkeypatch.setattr(config_service, "settings", settings)
    monkeypatch.setattr(manager, "initialize_app_context", AsyncMock())
    close = AsyncMock()
    monkeypatch.setattr(manager, "close_app_context", close)
    monkeypatch.setattr(es_manager, "get_es_connection", AsyncMock(return_value=es))
    migration = AsyncMock(return_value={"mode": "dry_run"})
    monkeypatch.setattr(entry, "run_migration", migration)
    await entry.run(entry.parser().parse_args(["--batch-size", "2", "--run-id", "batch-cli"]))
    assert migration.call_args.kwargs["batch_size"] == 2
    assert migration.call_args.args == (es, 3)
    close.assert_awaited_once()
