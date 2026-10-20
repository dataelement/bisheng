from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.channel.domain.services.information_knowledge_delivery_service import (
    InformationKnowledgeDeliveryService,
)
from bisheng.common.errcode.knowledge_space import SpaceFileNameDuplicateError


def _config():
    return SimpleNamespace(
        id="config-A",
        channel_id="channel-A",
        knowledge_space_id="12",
        folder_id="34",
        user_id=7,
        is_enabled=True,
        create_time=datetime.now() - timedelta(minutes=5),
        update_time=datetime.now() - timedelta(minutes=5),
    )


async def test_delivery_calls_existing_import_once_per_article_without_retry_mode():
    config_repo = AsyncMock()
    config_repo.find_by_id.return_value = _config()
    channel_repo = AsyncMock()
    channel_repo.find_by_id.return_value = SimpleNamespace(id="channel-A")
    channel_service = AsyncMock()
    service = InformationKnowledgeDeliveryService(
        channel_repo,
        config_repo,
        MagicMock(),
        channel_service=channel_service,
    )

    result = await service.deliver_to_config(
        2,
        "config-A",
        ["article-1", "article-2"],
        int(datetime.now().timestamp()),
    )

    assert channel_service.add_articles_to_knowledge_space.await_count == 2
    for call in channel_service.add_articles_to_knowledge_space.await_args_list:
        request = call.args[0]
        user = call.args[1]
        assert request.skip_missing_and_duplicates is False
        assert len(request.article_ids) == 1
        assert user.user_id == 7
        assert user.tenant_id == 2
    assert result["accepted"] == 2


async def test_duplicate_failure_is_terminal_and_next_article_continues():
    config_repo = AsyncMock()
    config_repo.find_by_id.return_value = _config()
    channel_repo = AsyncMock()
    channel_repo.find_by_id.return_value = SimpleNamespace(id="channel-A")
    channel_service = AsyncMock()
    channel_service.add_articles_to_knowledge_space.side_effect = [SpaceFileNameDuplicateError(), []]
    service = InformationKnowledgeDeliveryService(
        channel_repo,
        config_repo,
        MagicMock(),
        channel_service=channel_service,
    )

    result = await service.deliver_to_config(
        2,
        "config-A",
        ["article-1", "article-2"],
        int(datetime.now().timestamp()),
    )

    assert channel_service.add_articles_to_knowledge_space.await_count == 2
    assert result["accepted"] == 1
    assert result["failed"] == {"duplicate_name": 1}


async def test_delivery_revalidates_config_channel_and_effective_time():
    config = _config()
    config.update_time = datetime.now() + timedelta(minutes=5)
    config_repo = AsyncMock()
    config_repo.find_by_id.return_value = config
    channel_repo = AsyncMock()
    channel_repo.find_by_id.return_value = SimpleNamespace(id="channel-A")
    channel_service = AsyncMock()
    service = InformationKnowledgeDeliveryService(
        channel_repo,
        config_repo,
        MagicMock(),
        channel_service=channel_service,
    )

    result = await service.deliver_to_config(
        2,
        "config-A",
        ["article-1"],
        int(datetime.now().timestamp()),
    )

    assert result["result"] == "config_not_effective"
    channel_service.add_articles_to_knowledge_space.assert_not_awaited()
