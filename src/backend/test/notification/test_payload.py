# ruff: noqa: RUF001
from unittest.mock import patch

import pytest

from bisheng.notification.external._payload import (
    FORWARDABLE_ACTION_CODES,
    build_textcard,
    build_textcard_url,
)


def test_forwardable_set_has_supported_station_message_codes():
    assert FORWARDABLE_ACTION_CODES == {
        "request_channel", "approved_channel", "rejected_channel",
        "request_knowledge_space", "approved_knowledge_space", "rejected_knowledge_space",
        "request_department_knowledge_space_upload",
        "approved_department_knowledge_space_upload",
        "rejected_department_knowledge_space_upload",
        "sensitive_rejected_department_knowledge_space_upload",
        "request_menu_access",
        "approval_task_pending",
        "approval_task_rejected",
        "approval_instance_approved",
        "approval_instance_withdrawn",
        "approval_exception_cancelled",
        "approval_exception_route_missing",
        "approval_exception_approver_empty",
        "approval_execute_failed",
        "menu_grant_revoked",
        "assigned_channel_admin",
        "assigned_knowledge_space_admin",
        "revoked_channel_admin",
        "revoked_knowledge_space_admin",
        "removed_channel_member",
        "removed_knowledge_space_member",
        "channel_made_private",
        "knowledge_space_made_private",
        "channel_dismissed",
        "knowledge_space_deleted",
    }


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_url_basic(mock_settings):
    mock_settings.get_cofco_forwarding_conf.return_value.bisheng_inbox_url = "https://bisheng.cofco.com/"
    url = build_textcard_url(message_id=12345)
    assert url == "https://bisheng.cofco.com/?open-notifications=1&message-id=12345"


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_url_strips_trailing_slash(mock_settings):
    mock_settings.get_cofco_forwarding_conf.return_value.bisheng_inbox_url = "https://bisheng.cofco.com"
    url = build_textcard_url(message_id=999)
    assert url == "https://bisheng.cofco.com/?open-notifications=1&message-id=999"


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_request_channel(mock_settings):
    mock_settings.get_cofco_forwarding_conf.return_value.bisheng_inbox_url = "https://bisheng.cofco.com"
    card = build_textcard(
        message_id=1,
        action_code="request_channel",
        applicant_name="张三",
        resource_name="技术频道",
        triggered_at="2026-05-13 10:30",
    )
    assert card["title"] == "[知源] 新的频道订阅申请"
    assert "张三申请订阅频道「技术频道」" in card["description"]
    assert "需要你审批" not in card["description"]
    assert "2026-05-13 10:30" in card["description"]
    assert card["btntxt"] == "去查看"
    assert "open-notifications=1" in card["url"]


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_approved_knowledge_space(mock_settings):
    mock_settings.get_cofco_forwarding_conf.return_value.bisheng_inbox_url = "https://bisheng.cofco.com"
    card = build_textcard(
        message_id=2, action_code="approved_knowledge_space",
        applicant_name="李四", resource_name="研发知识空间", triggered_at="2026-05-13 11:00",
    )
    assert card["title"] == "[知源] 知识空间加入申请已通过"
    assert "李四通过了你对「研发知识空间」的审批申请" in card["description"]


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_withdrawn_includes_reason_and_no_extra_no_action_needed(mock_settings):
    mock_settings.get_cofco_forwarding_conf.return_value.bisheng_inbox_url = "https://bisheng.cofco.com"
    card = build_textcard(
        message_id=5,
        action_code="approval_instance_withdrawn",
        applicant_name="站内信",
        resource_name="知识空间",
        triggered_at="2026-06-01 10:05",
        reason="不看了",
    )
    assert "站内信撤回了「知识空间」的审批申请，原因：不看了" in card["description"]
    assert "无需处理" not in card["description"]


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_pending_uses_scenario_specific_prd_copy(mock_settings):
    mock_settings.get_cofco_forwarding_conf.return_value.bisheng_inbox_url = "https://bisheng.cofco.com"
    card = build_textcard(
        message_id=6,
        action_code="approval_task_pending",
        applicant_name="站内信",
        resource_name="知识空间",
        triggered_at="2026-06-01 10:06",
        scenario_code="menu_access_request",
    )
    assert "站内信申请访问菜单「知识空间」" in card["description"]
    assert "提交了「知识空间」审批申请" not in card["description"]


def test_build_textcard_unknown_action_code_raises():
    with pytest.raises(KeyError):
        build_textcard(
            message_id=3, action_code="unknown_code",
            applicant_name="A", resource_name="B", triggered_at="2026-05-13 12:00",
        )


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_truncates_long_title(mock_settings):
    """E+ API requires title ≤128 bytes and description ≤512 bytes."""
    mock_settings.get_cofco_forwarding_conf.return_value.bisheng_inbox_url = "https://bisheng.cofco.com"
    long_name = "X" * 1000
    card = build_textcard(
        message_id=4, action_code="request_channel",
        applicant_name=long_name, resource_name=long_name, triggered_at="2026-05-13 12:00",
    )
    assert len(card["title"].encode("utf-8")) <= 128
    assert len(card["description"].encode("utf-8")) <= 512
