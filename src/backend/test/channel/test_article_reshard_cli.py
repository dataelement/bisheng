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
