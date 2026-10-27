from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from bisheng.eplus.domain.schemas.metric import TerminalMetricSnapshot
from bisheng.eplus.infrastructure.metric_events import emit_request_metric


def snapshot(**overrides):
    values = {
        "tenant_id": 73,
        "bot_id": "bot-1",
        "bot_config_id": 101,
        "message_id": "msg-1",
        "sender_external_id": "employee-1",
        "conversation_id": "conversation-1",
        "admitted": True,
        "result": "success",
        "reason": None,
        "reply_status": "FINISHED",
        "event_time": datetime(2026, 10, 28, 0, 1),
        "received_at": datetime(2026, 10, 27, 23, 59),
    }
    return TerminalMetricSnapshot(**(values | overrides))


def test_terminal_is_self_contained_and_has_stable_tenant_scoped_identity():
    """AC-01, AC-04, AC-05, AC-06, AC-12: no request-start join or raw identity."""
    with patch("bisheng.eplus.infrastructure.metric_events.emit_metric") as emit:
        emit_request_metric(snapshot())
        first = emit.call_args.kwargs
        emit_request_metric(snapshot(bot_id="bot-2", message_id="msg-2"))
        assert emit.call_args.kwargs["user_id"] == first["user_id"]
        emit_request_metric(snapshot(tenant_id=74))
        assert emit.call_args.kwargs["user_id"] != first["user_id"]
        assert first["elapsed_ms"] == 120000
        assert first["message_id"] == "msg-1" and first["admitted"] is True
        assert first["event_time_ms"] == int(snapshot().event_time.timestamp() * 1000)
        assert "employee-1" not in str(first) and len(first["user_id"]) == 64
        assert "answer" not in first and "payload" not in first


def test_result_classification_does_not_treat_terminal_failure_reply_as_success():
    """AC-02, AC-03: FINISHED can be a failure or a rejection."""
    base = {
        "tenant_id": 73,
        "bot_id": "bot",
        "bot_config_id": 1,
        "msgid": "m",
        "sender_external_id": "u",
        "conversation_id": "c",
        "turn_id": "t",
        "reply_status": "FINISHED",
        "status": "FAILED",
        "error_code": "ASSISTANT_TIMEOUT",
        "received_at": datetime.now(),
        "finished_at": datetime.now(),
    }
    value = TerminalMetricSnapshot.from_message(SimpleNamespace(**base))
    assert value.admitted and value.result == "failed"
    value = TerminalMetricSnapshot.from_message(SimpleNamespace(**(base | {"turn_id": None})))
    assert not value.admitted and value.result == "rejected"


def test_new_domains_obey_existing_eplus_switch():
    """AC-10, AC-11: no separate metrics store or independent switches."""
    from bisheng.common.services import metric_log

    with patch.object(metric_log, "_get_conf", return_value=SimpleNamespace(enabled=True, eplus=False)):
        with patch.object(metric_log.logger, "info") as info:
            metric_log.emit_metric("eplus_robot_request", result="success")
            metric_log.emit_metric("eplus_robot_connection", event="authenticated")
            info.assert_not_called()


def test_output_failure_never_breaks_business():
    """AC-11, AC-13: optional telemetry failure is isolated."""
    with patch("bisheng.eplus.infrastructure.metric_events.emit_metric", side_effect=RuntimeError("broken")):
        emit_request_metric(snapshot())
