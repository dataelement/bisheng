"""Tests for ShougangMADPClient business-level response handling."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# The shared conftest pre-mocks bisheng.common.services.config_service.
# We need the real module to instantiate settings for the client.
_mocked_modules = [
    "bisheng.common.services",
    "bisheng.common.services.base",
    "bisheng.common.services.config_service",
]
_stashed_mocks = {name: sys.modules.pop(name, None) for name in _mocked_modules}
sys.modules["bisheng.common.services.telemetry"] = MagicMock()
sys.modules["bisheng.common.services.telemetry.telemetry_service"] = MagicMock()

from bisheng.notification.external.shougang_madp_client import ShougangMADPClient

for name, mock in _stashed_mocks.items():
    if mock is not None:
        sys.modules[name] = mock


def _make_conf(**overrides):
    conf = MagicMock()
    conf.api_url = "https://example.com/push"
    conf.id = "corp-id"
    conf.agentid = "1000001"
    conf.key = "secret-key"
    conf.msg_type = "text"
    conf.sys_id = "1"
    conf.timeout_seconds = 5
    for key, value in overrides.items():
        setattr(conf, key, value)
    return conf


def test_check_business_success_http_error():
    ok, err = ShougangMADPClient._check_business_success(500, '{"code": 0}')
    assert ok is False
    assert err is None


def test_check_business_success_empty_body():
    ok, err = ShougangMADPClient._check_business_success(200, "")
    assert ok is True
    assert err is None


def test_check_business_success_json_with_code_zero():
    ok, err = ShougangMADPClient._check_business_success(200, '{"code": 0, "data": {}}')
    assert ok is True
    assert err is None


def test_check_business_success_json_with_code_nonzero():
    ok, err = ShougangMADPClient._check_business_success(200, '{"code": -1, "msg": "invalid user"}')
    assert ok is False
    assert err == "code=-1 msg=invalid user"


def test_check_business_success_json_with_errcode_nonzero():
    ok, err = ShougangMADPClient._check_business_success(200, '{"errcode": 40014}')
    assert ok is False
    assert err == "errcode=40014"


def test_check_business_success_json_with_success_false():
    ok, err = ShougangMADPClient._check_business_success(200, '{"success": false, "message": "busy"}')
    assert ok is False
    assert err == "success=false"


def test_check_business_success_json_with_status_failed():
    ok, err = ShougangMADPClient._check_business_success(200, '{"status": "failed"}')
    assert ok is False
    assert err == "status=failed"


def test_check_business_success_non_json_body():
    ok, err = ShougangMADPClient._check_business_success(200, "OK")
    assert ok is True
    assert err is None


def test_check_business_success_unwraps_json_string_data_field():
    """Shougang MADP wraps the real WeChat response in a JSON-string ``data`` field."""
    body = (
        '{"meta":{"message":"操作成功!","success":true},'
        '"data":"{\\"errcode\\":60020,\\"errmsg\\":\\"not allow to access from your ip\\"}",'
        '"success":true}'
    )
    ok, err = ShougangMADPClient._check_business_success(200, body)
    assert ok is False
    assert "errcode=60020" in err


def test_check_business_success_data_dict_with_success():
    ok, err = ShougangMADPClient._check_business_success(
        200, '{"code": 0, "data": {"errcode": 0, "msg": "ok"}}'
    )
    assert ok is True
    assert err is None


@pytest.mark.asyncio
async def test_push_text_message_treats_http_200_with_business_error_as_failure():
    conf = _make_conf()
    response = MagicMock()
    response.status_code = 200
    response.text = '{"code": -1, "msg": "user not found"}'

    client = ShougangMADPClient()
    with patch("bisheng.notification.external.shougang_madp_client.settings") as mock_settings:
        mock_settings.get_shougang_wechat_message_push_conf.return_value = conf
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response):
            success, error = await client.push_text_message(
                outbox_id=1,
                user_ids=["wx001"],
                body="hello",
            )

    assert success is False
    assert "code=-1" in error


@pytest.mark.asyncio
async def test_push_text_message_treats_http_200_with_code_zero_as_success():
    conf = _make_conf()
    response = MagicMock()
    response.status_code = 200
    response.text = '{"code": 0, "data": {"msgId": "123"}}'

    client = ShougangMADPClient()
    with patch("bisheng.notification.external.shougang_madp_client.settings") as mock_settings:
        mock_settings.get_shougang_wechat_message_push_conf.return_value = conf
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response):
            success, error = await client.push_text_message(
                outbox_id=2,
                user_ids=["wx001"],
                body="hello",
            )

    assert success is True
    assert error is None
