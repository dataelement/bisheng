from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.channel import BishengInformationServiceError
from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.external.bisheng_information_client.client import BishengInformationClient


async def test_subscribe_failure_emits_collectable_error_log_and_reraises():
    http_client = SimpleNamespace(
        post=AsyncMock(return_value=SimpleNamespace(status_code=503, body={"message": "unavailable"}))
    )
    client = BishengInformationClient(
        http_client=http_client,
        get_conf=lambda: IntelligenceCenterConf(base_url="http://information.test", api_key="secret"),
    )

    with patch("bisheng.core.external.bisheng_information_client.client.logger.exception") as log_exception:
        with pytest.raises(BishengInformationServiceError):
            await client.subscribe_information_source(["source-1", "source-2"])

    log_exception.assert_called_once_with(
        "BISHENG_INFORMATION_SUBSCRIPTION_REQUEST_FAILED endpoint={} source_count={}",
        "http://information.test/information/subscribe",
        2,
    )
