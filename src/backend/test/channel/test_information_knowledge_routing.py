from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.channel.domain.services.information_knowledge_delivery_service import (
    InformationKnowledgeDeliveryService,
)
from bisheng.core.config.settings import IntelligenceCenterConf


async def test_route_main_and_sub_channel_without_cross_config_dedup():
    detected_at = int(datetime.now().timestamp())
    channel = SimpleNamespace(
        id="channel-A",
        source_list=["source-A"],
        filter_rules=[{"channel_type": "sub", "name": "important", "keywords": ["AI"]}],
    )
    main = SimpleNamespace(
        id="main",
        channel_id="channel-A",
        sub_channel_name=None,
        is_enabled=True,
        create_time=datetime.now() - timedelta(minutes=5),
        update_time=datetime.now() - timedelta(minutes=5),
    )
    sub = SimpleNamespace(
        id="sub",
        channel_id="channel-A",
        sub_channel_name="important",
        is_enabled=True,
        create_time=main.create_time,
        update_time=main.update_time,
    )
    channel_repo = AsyncMock()
    channel_repo.find_channels_referencing_source.return_value = [channel]
    config_repo = AsyncMock()
    config_repo.find_enabled_by_channel_ids.return_value = [main, sub]
    article_service = MagicMock()
    article_service.match_article_ids_sync.return_value = ["article-2"]
    dispatch = AsyncMock()
    service = InformationKnowledgeDeliveryService(channel_repo, config_repo, article_service)

    result = await service.route_current_tenant("source-A", ["article-1", "article-2"], detected_at, dispatch)

    assert dispatch.await_args_list[0].args == ("main", ["article-1", "article-2"], detected_at)
    assert dispatch.await_args_list[1].args == ("sub", ["article-2"], detected_at)
    assert result["dispatched"] == 2


async def test_route_skips_config_created_after_article_detection():
    detected_at = int(datetime.now().timestamp())
    channel = SimpleNamespace(id="channel-A", source_list=["source-A"], filter_rules=[])
    config = SimpleNamespace(
        id="new",
        channel_id="channel-A",
        sub_channel_name=None,
        is_enabled=True,
        create_time=datetime.fromtimestamp(detected_at + 10),
        update_time=datetime.fromtimestamp(detected_at + 10),
    )
    channel_repo = AsyncMock()
    channel_repo.find_channels_referencing_source.return_value = [channel]
    config_repo = AsyncMock()
    config_repo.find_enabled_by_channel_ids.return_value = [config]
    dispatch = AsyncMock()
    service = InformationKnowledgeDeliveryService(
        channel_repo,
        config_repo,
        MagicMock(),
        get_conf=lambda: IntelligenceCenterConf(information_knowledge_delivery_enabled=True),
    )

    result = await service.route_current_tenant("source-A", ["article-1"], detected_at, dispatch)

    dispatch.assert_not_awaited()
    assert result["skipped"] == 1


async def test_route_disabled_globally_does_not_dispatch():
    service = InformationKnowledgeDeliveryService(
        AsyncMock(),
        AsyncMock(),
        MagicMock(),
        get_conf=lambda: IntelligenceCenterConf(information_knowledge_delivery_enabled=False),
    )
    dispatch = AsyncMock()

    result = await service.route_current_tenant("source-A", ["article-1"], 1, dispatch)

    assert result["result"] == "disabled"
    dispatch.assert_not_awaited()
