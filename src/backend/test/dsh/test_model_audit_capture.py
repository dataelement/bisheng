"""覆盖 AC: AC-09, AC-11, AC-12, AC-17, AC-22, AC-27, AC-28, AC-31, AC-38."""

import json

from bisheng.dsh.domain.services.model_audit_capture import AuditCapture
from test.dsh.model_audit_fixtures import AuditTestClock, ControlledAuditQueue


def capture(mode, queue=None, **kwargs):
    queue = queue if queue is not None else ControlledAuditQueue()
    return AuditCapture(
        {"request_id": "request", "tenant_id": 2, "user_id": 20, "effective_mode": mode},
        queue,
        now=AuditTestClock(),
        chunk_bytes=1024,
        digest_key=bytes(range(32)),
        key_version="test-key",
        request_budget_bytes=kwargs.pop("budget", 65536),
        **kwargs,
    ), queue


def test_off_no_entered_activity_or_body_and_metadata_no_originals():
    off, queue = capture("OFF")
    off.entered([{"content": "synthetic"}])
    off.output({"content": "synthetic"})
    off.terminal("SUCCEEDED")
    assert queue.events == []
    metadata, queue = capture("METADATA")
    metadata.entered([{"content": "synthetic"}])
    metadata.output({"content": "synthetic"})
    metadata.terminal("SUCCEEDED")
    assert [event.kind for event in queue.events] == ["entered", "terminal"]
    assert all(event.body is None for event in queue.events)
    assert "synthetic" not in repr(queue.events)


def test_content_expected_sequence_and_queue_drop_are_not_complete():
    cap, queue = capture("CONTENT", ControlledAuditQueue(drop_sequence=1))
    cap.entered([{"content": "x" * 5000}])
    cap.output({"content": "answer"})
    cap.terminal("SUCCEEDED")
    terminal = queue.events[-1]
    assert terminal.metadata["capture_failed"]
    assert terminal.metadata["channels"]["input"]["count"] > 1
    actual = [e for e in queue.events if e.kind == "body" and e.channel == "input"]
    assert len(actual) < terminal.metadata["channels"]["input"]["count"]


def test_budget_or_encoding_failure_is_bounded_and_does_not_throw():
    cap, queue = capture("CONTENT", budget=2048)
    cap.entered([{"content": "x" * 100000}])
    cap.output({"content": "answer"})
    cap.terminal("CANCELLED")
    assert sum(len(e.body or b"") for e in queue.events) <= 2048
    assert queue.events[-1].metadata["capture_failed"]
    cap, queue = capture("CONTENT")
    cap.entered([{"content": object()}])
    cap.terminal("FAILED")
    assert queue.events[-1].metadata["capture_failed"]


def test_healthy_content_has_input_and_output_and_empty_result_manifest():
    cap, queue = capture("CONTENT")
    cap.entered([{"role": "user", "content": "synthetic"}])
    cap.output({"role": "assistant", "content": "answer"})
    cap.terminal("SUCCEEDED")
    terminal = queue.events[-1]
    assert terminal.metadata["input_complete"] and not terminal.metadata["capture_failed"]
    body = b"".join(e.body for e in queue.events if e.kind == "body" and e.channel == "input")
    assert json.loads(body)["content"] == "synthetic"
    cap, queue = capture("CONTENT")
    cap.entered([{"role": "user", "content": "synthetic"}])
    cap.terminal("FAILED")
    assert queue.events[-1].metadata["channels"]["output"]["count"] == 0
    assert not queue.events[-1].metadata["capture_failed"]


def test_independent_evidence_failure_does_not_drop_valid_originals():
    cap, queue = capture("CONTENT", evidence_queue=ControlledAuditQueue(capacity=0))
    cap.entered([{"content": "synthetic"}])
    cap.terminal("SUCCEEDED")
    assert queue.events[-1].metadata["input_complete"]
    assert not queue.events[-1].metadata["capture_failed"]
