import pytest
from unittest.mock import patch
from bisheng.notification.external._payload import (
    FORWARDABLE_ACTION_CODES,
    build_textcard,
    build_textcard_url,
)


def test_forwardable_set_has_six_codes():
    assert FORWARDABLE_ACTION_CODES == {
        "request_channel", "approved_channel", "rejected_channel",
        "request_knowledge_space", "approved_knowledge_space", "rejected_knowledge_space",
    }


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_url_basic(mock_settings):
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com/"
    url = build_textcard_url(message_id=12345)
    assert url == "https://bisheng.cofco.com/?open-notifications=1&message-id=12345"


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_url_strips_trailing_slash(mock_settings):
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com"
    url = build_textcard_url(message_id=999)
    assert url == "https://bisheng.cofco.com/?open-notifications=1&message-id=999"


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_request_channel(mock_settings):
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com"
    card = build_textcard(
        message_id=1,
        action_code="request_channel",
        applicant_name="张三",
        resource_name="技术频道",
        triggered_at="2026-05-13 10:30",
    )
    assert card["title"] == "[知源] 新的频道订阅申请"
    assert "张三 申请订阅频道「技术频道」" in card["description"]
    assert "需要你审批" in card["description"]
    assert "2026-05-13 10:30" in card["description"]
    assert card["btntxt"] == "去查看"
    assert "open-notifications=1" in card["url"]


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_approved_knowledge_space(mock_settings):
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com"
    card = build_textcard(
        message_id=2, action_code="approved_knowledge_space",
        applicant_name="李四", resource_name="研发知识空间", triggered_at="2026-05-13 11:00",
    )
    assert card["title"] == "[知源] 知识空间加入申请已通过"
    assert "你加入知识空间「研发知识空间」的申请" in card["description"]
    assert "已通过" in card["description"]


def test_build_textcard_unknown_action_code_raises():
    with pytest.raises(KeyError):
        build_textcard(
            message_id=3, action_code="unknown_code",
            applicant_name="A", resource_name="B", triggered_at="2026-05-13 12:00",
        )


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_truncates_long_title(mock_settings):
    """E+ API requires title ≤128 bytes and description ≤512 bytes."""
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com"
    long_name = "X" * 1000
    card = build_textcard(
        message_id=4, action_code="request_channel",
        applicant_name=long_name, resource_name=long_name, triggered_at="2026-05-13 12:00",
    )
    assert len(card["title"].encode("utf-8")) <= 128
    assert len(card["description"].encode("utf-8")) <= 512
