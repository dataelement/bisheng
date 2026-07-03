"""E+ (COFCO) notify metric wiring tests (F042 T010).

The client emits ``eplus_notify result=ok/error`` for real interface calls; the
forwarder emits ``result=skipped`` only for post-whitelist recipient-resolution
skips (feature_disabled / not_in_whitelist fire on nearly every inbox message
and are intentionally NOT metered — see tasks 偏差记录). Contract: design §6.1.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from loguru import logger

from bisheng.notification.external.cofco_eplus_client import CofcoEPlusClient


@contextmanager
def capture_metric_logs():
    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(str(m).rstrip("\n")), level="INFO", format="{message}")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


def _line_for(messages, domain):
    prefix = f"BS_METRIC domain={domain}"
    for m in messages:
        if m == prefix or m.startswith(prefix + " "):
            return m
    return None


@contextmanager
def _mock_conf():
    with patch("bisheng.notification.external.cofco_eplus_client.settings") as m:
        c = m.get_cofco_forwarding_conf.return_value
        c.api_base = "http://x/qwmsg-ui"
        c.app_id = "a"
        c.secret = "s"
        c.agentid = 1
        c.timeout_seconds = 5.0
        c.enable_duplicate_check = 0
        c.duplicate_check_interval = 1800
        yield


_CARD = {"title": "t", "description": "d", "url": "u", "btntxt": "b"}


def _resp(code, status=200):
    r = MagicMock()
    r.json.return_value = {"code": code, "msg": "m"}
    r.status_code = status
    return r


# ---------------------------------------------------------------------------
# Client: real interface calls -> ok / error
# ---------------------------------------------------------------------------


async def test_client_success_emits_ok():
    client = CofcoEPlusClient()
    with _mock_conf(), capture_metric_logs() as messages:
        with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
            ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=_resp("0", 200))
            await client.send_textcard(message_id=1, action_code="request_channel", touser=["U1"], textcard=_CARD)
    line = _line_for(messages, "eplus_notify")
    assert line is not None
    assert "result=ok" in line and "biz_code=0" in line
    assert "http_status=200" in line and "action=request_channel" in line and "elapsed_ms=" in line


async def test_client_nonzero_code_emits_error():
    client = CofcoEPlusClient()
    with _mock_conf(), capture_metric_logs() as messages:
        with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
            ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=_resp("82001", 200))
            await client.send_textcard(message_id=2, action_code="approved_channel", touser=["U1"], textcard=_CARD)
    line = _line_for(messages, "eplus_notify")
    assert line is not None
    assert "result=error" in line and "biz_code=82001" in line


async def test_client_exception_emits_error():
    client = CofcoEPlusClient()
    with _mock_conf(), capture_metric_logs() as messages:
        with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
            ACli.return_value.__aenter__.return_value.post = AsyncMock(side_effect=Exception("network down"))
            await client.send_textcard(message_id=3, action_code="rejected_channel", touser=["U1"], textcard=_CARD)
    line = _line_for(messages, "eplus_notify")
    assert line is not None and "result=error" in line


# ---------------------------------------------------------------------------
# Forwarder: post-whitelist recipient skip -> skipped
# ---------------------------------------------------------------------------


def test_forwarder_recipient_skip_emits_skipped():
    from bisheng.notification import forwarder
    from bisheng.notification.external._payload import FORWARDABLE_ACTION_CODES

    action_code = next(iter(FORWARDABLE_ACTION_CODES))
    message = MagicMock()
    message.id = 7
    message.action_code = action_code
    message.receiver = [101]

    bad_user = MagicMock()
    bad_user.source = "local"  # not in user_sources -> skip
    bad_user.external_id = "E101"

    with capture_metric_logs() as messages:
        with (
            patch("bisheng.notification.forwarder.settings") as msettings,
            patch("bisheng.notification.forwarder.UserDao") as mUserDao,
        ):
            conf = msettings.get_cofco_forwarding_conf.return_value
            conf.enabled = True
            conf.user_sources = ["cofco_eplus"]
            mUserDao.get_user.return_value = bad_user
            forwarder.maybe_forward_external(message)

    line = _line_for(messages, "eplus_notify")
    assert line is not None and "result=skipped" in line


def test_forwarder_feature_disabled_not_metered():
    from bisheng.notification import forwarder

    message = MagicMock()
    message.id = 8

    with capture_metric_logs() as messages:
        with patch("bisheng.notification.forwarder.settings") as msettings:
            msettings.get_cofco_forwarding_conf.return_value.enabled = False
            forwarder.maybe_forward_external(message)

    # feature_disabled is high-frequency and intentionally NOT metered
    assert _line_for(messages, "eplus_notify") is None
