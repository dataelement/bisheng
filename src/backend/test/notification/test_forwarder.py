from unittest.mock import MagicMock, patch

import pytest

from bisheng.notification.forwarder import maybe_forward_external, resolve_eplus_recipient

# ---- resolve_eplus_recipient ----

@patch("bisheng.notification.forwarder.UserDao")
def test_resolve_returns_none_when_user_missing(UserDao):
    UserDao.get_user.return_value = None
    rid, reason = resolve_eplus_recipient(123)
    assert rid is None
    assert reason == "user_not_found"


@patch("bisheng.notification.forwarder.settings")
@patch("bisheng.notification.forwarder.UserDao")
def test_resolve_returns_none_when_source_not_in_allowed(UserDao, mock_settings):
    mock_settings.get_cofco_forwarding_conf.return_value.user_sources = ["cofco_eplus", "wecom"]
    user = MagicMock(source="local", external_id="X1")
    UserDao.get_user.return_value = user
    rid, reason = resolve_eplus_recipient(123)
    assert rid is None
    assert "not_in_allowed_sources" in reason


@patch("bisheng.notification.forwarder.settings")
@patch("bisheng.notification.forwarder.UserDao")
def test_resolve_returns_none_when_external_id_empty(UserDao, mock_settings):
    mock_settings.get_cofco_forwarding_conf.return_value.user_sources = ["cofco_eplus", "wecom"]
    user = MagicMock(source="cofco_eplus", external_id="")
    UserDao.get_user.return_value = user
    rid, reason = resolve_eplus_recipient(123)
    assert rid is None
    assert reason == "external_id_empty"


@patch("bisheng.notification.forwarder.settings")
@patch("bisheng.notification.forwarder.UserDao")
def test_resolve_returns_external_id_for_cofco_eplus(UserDao, mock_settings):
    mock_settings.get_cofco_forwarding_conf.return_value.user_sources = ["cofco_eplus", "wecom"]
    user = MagicMock(source="cofco_eplus", external_id="EMP001")
    UserDao.get_user.return_value = user
    rid, reason = resolve_eplus_recipient(123)
    assert rid == "EMP001"
    assert reason == ""


@patch("bisheng.notification.forwarder.settings")
@patch("bisheng.notification.forwarder.UserDao")
def test_resolve_returns_external_id_for_wecom_source(UserDao, mock_settings):
    """The real production case: cofco customer's users have source='wecom'."""
    mock_settings.get_cofco_forwarding_conf.return_value.user_sources = ["cofco_eplus", "wecom"]
    user = MagicMock(source="wecom", external_id="EMP002")
    UserDao.get_user.return_value = user
    rid, reason = resolve_eplus_recipient(123)
    assert rid == "EMP002"
    assert reason == ""


# ---- maybe_forward_external ----

@pytest.fixture
def fake_msg():
    m = MagicMock()
    m.id = 100
    m.action_code = "request_channel"
    m.receiver = [5]
    m.create_time = MagicMock()
    m.create_time.strftime.return_value = "2026-05-13 10:00"
    return m


@patch("bisheng.notification.forwarder._fire_and_forget")
@patch("bisheng.notification.forwarder.settings")
def test_forward_skipped_when_disabled(mock_settings, mock_fire, fake_msg):
    mock_settings.get_cofco_forwarding_conf.return_value.enabled = False
    maybe_forward_external(fake_msg)
    mock_fire.assert_not_called()


@patch("bisheng.notification.forwarder._fire_and_forget")
@patch("bisheng.notification.forwarder.settings")
def test_forward_skipped_when_action_code_not_forwardable(mock_settings, mock_fire, fake_msg):
    mock_settings.get_cofco_forwarding_conf.return_value.enabled = True
    fake_msg.action_code = "some_other_code"
    maybe_forward_external(fake_msg)
    mock_fire.assert_not_called()


@patch("bisheng.notification.forwarder._fire_and_forget")
@patch("bisheng.notification.forwarder.resolve_eplus_recipient")
@patch("bisheng.notification.forwarder.settings")
def test_forward_skipped_when_all_recipients_unresolved(
    mock_settings, mock_resolve, mock_fire, fake_msg,
):
    mock_settings.get_cofco_forwarding_conf.return_value.enabled = True
    mock_resolve.return_value = (None, "external_id_empty")
    maybe_forward_external(fake_msg)
    mock_fire.assert_not_called()


@patch("bisheng.notification.external._payload.settings")
@patch("bisheng.notification.forwarder._fire_and_forget")
@patch("bisheng.notification.forwarder._extract_payload_fields")
@patch("bisheng.notification.forwarder.resolve_eplus_recipient")
@patch("bisheng.notification.forwarder.settings")
def test_forward_schedules_fire_and_forget(
    mock_settings, mock_resolve, mock_extract, mock_fire, mock_payload_settings, fake_msg,
):
    mock_settings.get_cofco_forwarding_conf.return_value.enabled = True
    mock_resolve.return_value = ("EMP001", "")
    mock_extract.return_value = ("张三", "技术频道", "", "")
    mock_payload_settings.get_cofco_forwarding_conf.return_value.bisheng_inbox_url = "https://bisheng.cofco.com"

    maybe_forward_external(fake_msg)

    mock_fire.assert_called_once()
    # _fire_and_forget receives a coroutine object — close it to avoid the
    # "coroutine was never awaited" RuntimeWarning during teardown.
    (coro,), _ = mock_fire.call_args
    coro.close()


@patch("bisheng.notification.forwarder.resolve_eplus_recipient")
@patch("bisheng.notification.forwarder.settings")
def test_skipped_logs_include_message_id_and_reason(
    mock_settings, mock_resolve, fake_msg, caplog,
):
    """Skipped-path logs must contain forward.skipped + key fields for troubleshooting."""
    import logging
    caplog.set_level(logging.INFO)
    mock_settings.get_cofco_forwarding_conf.return_value.enabled = True
    mock_resolve.return_value = (None, "external_id_empty")

    maybe_forward_external(fake_msg)

    assert "forward.skipped" in caplog.text
    assert "message_id=100" in caplog.text
    assert "reason=external_id_empty" in caplog.text
