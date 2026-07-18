"""Model-invoke metric wiring tests (F042 T008).

``upload_telemetry_log`` is the single sink all four LLM wrappers call in their
finally; F042 adds a parallel ``model_invoke`` metric line there, reusing the
already-collected TTFT / status / is_stream (design §5 坑 5). Contract: design §6.1.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

from loguru import logger

from bisheng.common.constants.enums.telemetry import StatusEnum
from bisheng.llm.domain import utils


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


def _make_self(model_id=123):
    self = MagicMock()
    self.model_id = model_id
    # model_type != 'llm' so token parsing is skipped (irrelevant to the metric)
    self.model_info.model_type = "chat"
    return self


def test_model_invoke_line_on_success(monkeypatch):
    monkeypatch.setattr(utils.telemetry_service, "log_event_sync", lambda **kw: None)
    with capture_metric_logs() as messages:
        utils.upload_telemetry_log(
            _make_self(),
            start_time=1000.0,
            end_time=1002.0,
            first_token_cost_time=340,
            status=StatusEnum.SUCCESS,
            is_stream=True,
        )
    line = _line_for(messages, "model_invoke")
    assert line is not None
    assert "model_id=123" in line
    assert "status=success" in line
    assert "is_stream=1" in line
    assert "ttft_ms=340" in line
    assert "total_ms=2000.0" in line


def test_model_invoke_line_on_failure(monkeypatch):
    monkeypatch.setattr(utils.telemetry_service, "log_event_sync", lambda **kw: None)
    with capture_metric_logs() as messages:
        utils.upload_telemetry_log(
            _make_self(),
            start_time=5.0,
            end_time=6.5,
            first_token_cost_time=0,
            status=StatusEnum.FAILED,
            is_stream=False,
        )
    line = _line_for(messages, "model_invoke")
    assert line is not None
    assert "status=failed" in line and "is_stream=0" in line


def test_model_invoke_emitted_even_if_es_upload_fails(monkeypatch):
    # ES telemetry failure must not suppress the parallel metric line.
    monkeypatch.setattr(utils.telemetry_service, "log_event_sync", MagicMock(side_effect=RuntimeError("es down")))
    with capture_metric_logs() as messages:
        utils.upload_telemetry_log(
            _make_self(),
            start_time=1.0,
            end_time=1.1,
            first_token_cost_time=50,
            status=StatusEnum.SUCCESS,
        )
    assert _line_for(messages, "model_invoke") is not None
