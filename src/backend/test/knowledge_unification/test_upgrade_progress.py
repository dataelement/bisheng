"""AC-162, AC-166: progress remains observable without logging business data."""

import json
import threading

from bisheng.common.services import metric_log


def test_progress_context_counts_ack_and_sanitizes_details(tmp_path):
    from bisheng.knowledge.application.unification_progress import ProgressRecorder, report_progress

    events = []
    path = tmp_path / "progress.jsonl"
    with ProgressRecorder("run-1", mode="apply", path=path, emit=events.append, interval=60):
        report_progress("sql", processed=2, total=10, unit="command", committed=1, cursor="sql-v1:1:abc")
        report_progress("sql", processed=3, total=10, unit="command", committed=2, password="secret-value")
        report_progress("verify", total=None, unit="source", waiting="object_get")
    assert events[0]["event"] == "started"
    sql = next(x for x in events if x.get("phase") == "sql")
    assert sql["committed"] == 1
    assert sql["unit"] == "command"
    assert "secret-value" not in path.read_text()
    assert all(x["run_id"] == "run-1" for x in events)
    assert events[-1]["event"] == "finished"
    assert all(isinstance(json.loads(line), dict) for line in path.read_text().splitlines())


def test_progress_heartbeat_survives_wait_without_business_events():
    from bisheng.knowledge.application.unification_progress import ProgressRecorder, report_progress

    observed = threading.Event()
    events = []

    def emit(event):
        events.append(event)
        if event["event"] == "heartbeat":
            observed.set()

    with ProgressRecorder("run-2", mode="dry-run", emit=emit, interval=0.02) as recorder:
        report_progress("freeze", waiting="object_get")
        assert observed.wait(1)
    assert not recorder.is_alive
    assert any(e["event"] == "heartbeat" and e["phase"] == "freeze" for e in events)


def test_progress_failure_and_nested_context_are_restored():
    import pytest

    from bisheng.knowledge.application.unification_progress import ProgressRecorder, report_progress

    outer, inner = [], []
    with ProgressRecorder("outer", mode="apply", emit=outer.append, interval=60):
        with pytest.raises(ValueError):
            with ProgressRecorder("inner", mode="apply", emit=inner.append, interval=60):
                raise ValueError("private exception payload")
        report_progress("after", processed=1)
    assert any(e["event"] == "failed" for e in inner)
    assert "private exception payload" not in json.dumps(inner)
    assert any(e.get("phase") == "after" for e in outer)
    before = len(outer)
    report_progress("outside", processed=1)
    assert len(outer) == before


def test_hot_metrics_are_aggregated_only_in_command_scope(monkeypatch):
    from bisheng.knowledge.application.unification_progress import ProgressRecorder

    lines, events = [], []
    monkeypatch.setattr(metric_log.logger, "info", lambda line: lines.append(line))
    monkeypatch.setattr(metric_log, "_get_conf", lambda: None)
    metric_log.emit_metric("permission_visibility_projection", operation="project", elapsed_ms=2)
    assert len(lines) == 1
    with ProgressRecorder("metrics", mode="apply", emit=events.append, interval=60):
        for _ in range(100):
            metric_log.emit_metric("permission_visibility_projection", operation="project", elapsed_ms=2)
        metric_log.emit_metric("another_domain", status="ok")
    assert len(lines) == 2
    summary = events[-1]["metrics"]["permission_visibility_projection"]
    assert summary["count"] == 100
    assert summary["elapsed_ms_sum"] == 200
    metric_log.emit_metric("permission_visibility_projection", operation="project")
    assert len(lines) == 3


def test_resume_rate_counts_only_new_acknowledgements(monkeypatch):
    from bisheng.knowledge.application import unification_progress as progress

    now, events = [100.0], []
    monkeypatch.setattr(progress, "monotonic", lambda: now[0])
    with progress.ProgressRecorder("resume-rate", mode="apply", emit=events.append, interval=60):
        progress.report_progress("sql", tenant_id=101, processed=50_000, total=51_000, unit="command", committed=50_000)
        now[0] += 10
        progress.report_progress("sql", tenant_id=101, processed=50_100, total=51_000, unit="command", committed=50_100)
    assert events[-1]["rate"] == 10
    assert events[-1]["eta_s"] == 90
