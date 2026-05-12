import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bisheng.notification.external.cofco_eplus_client import CofcoEPlusClient


@pytest.fixture
def mock_settings():
    with patch("bisheng.notification.external.cofco_eplus_client.settings") as m:
        m.get_cofco_forwarding_conf.return_value.api_base = "http://10.28.64.30:8070/qwmsg-ui"
        m.get_cofco_forwarding_conf.return_value.app_id = "bisheng"
        m.get_cofco_forwarding_conf.return_value.secret = "secret123"
        m.get_cofco_forwarding_conf.return_value.agentid = 1
        m.get_cofco_forwarding_conf.return_value.timeout_seconds = 5.0
        m.get_cofco_forwarding_conf.return_value.enable_duplicate_check = 0
        m.get_cofco_forwarding_conf.return_value.duplicate_check_interval = 1800
        yield m


@pytest.mark.asyncio
async def test_send_textcard_success_logs_nothing(mock_settings, caplog):
    """code=='0' → no warning."""
    client = CofcoEPlusClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": "0", "msg": "操作成功", "data": "[\"jobid1\"]"}

    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        await client.send_textcard(
            message_id=1, action_code="request_channel",
            touser=["U001", "U002"],
            textcard={"title": "t", "description": "d", "url": "http://x", "btntxt": "去查看"},
        )

    assert "send_textcard failed" not in caplog.text
    assert "exception" not in caplog.text.lower()


@pytest.mark.asyncio
async def test_send_textcard_code_not_zero_logs_warning(mock_settings, caplog):
    client = CofcoEPlusClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": "82001", "msg": "All touser invalid"}

    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        await client.send_textcard(
            message_id=2, action_code="approved_channel",
            touser=["U001"], textcard={"title": "t", "description": "d", "url": "u", "btntxt": "b"},
        )

    assert "82001" in caplog.text
    assert "All touser invalid" in caplog.text
    assert "forward.result" in caplog.text
    assert "message_id=2" in caplog.text


@pytest.mark.asyncio
async def test_send_textcard_exception_does_not_raise(mock_settings, caplog):
    """Network exception should be swallowed and WARN logged."""
    client = CofcoEPlusClient()
    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("network down")
        )
        await client.send_textcard(
            message_id=3, action_code="rejected_channel",
            touser=["U1"], textcard={"title": "t", "description": "d", "url": "u", "btntxt": "b"},
        )

    assert "forward.result" in caplog.text
    assert "code=exception" in caplog.text


@pytest.mark.asyncio
async def test_send_textcard_request_shape(mock_settings):
    """Verify URL / headers / body structure is correct."""
    client = CofcoEPlusClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": "0"}
    captured = {}

    async def fake_post(url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return mock_response

    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        await client.send_textcard(
            message_id=4, action_code="request_channel",
            touser=["U1", "U2"],
            textcard={"title": "t", "description": "d", "url": "u", "btntxt": "b"},
        )

    assert captured["url"] == "http://10.28.64.30:8070/qwmsg-ui/v2/message/send"
    assert captured["headers"] == {"appId": "bisheng", "secret": "secret123"}
    body = captured["json"]
    assert body["touser"] == "U1|U2"
    assert body["msgtype"] == "textcard"
    assert body["agentid"] == 1
    assert body["textcard"] == {"title": "t", "description": "d", "url": "u", "btntxt": "b"}
    assert body["enable_duplicate_check"] == 0
    assert body["duplicate_check_interval"] == 1800


@pytest.mark.asyncio
async def test_send_textcard_empty_touser_skipped(mock_settings, caplog):
    client = CofcoEPlusClient()
    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        post = AsyncMock()
        ACli.return_value.__aenter__.return_value.post = post
        await client.send_textcard(message_id=5, action_code="approved_channel", touser=[], textcard={"title": "t"})
        post.assert_not_called()


@pytest.mark.asyncio
async def test_send_textcard_success_emits_attempt_and_result(mock_settings, caplog):
    """Success path must emit attempt + result lines with message_id for troubleshooting."""
    import logging
    caplog.set_level(logging.INFO)
    client = CofcoEPlusClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": "0", "msg": "ok"}

    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        await client.send_textcard(
            message_id=42, action_code="request_channel",
            touser=["EMP001"], textcard={"title": "t", "description": "d", "url": "u", "btntxt": "b"},
        )

    assert "forward.attempt" in caplog.text
    assert "forward.result" in caplog.text
    assert "message_id=42" in caplog.text
    assert "code=0" in caplog.text
