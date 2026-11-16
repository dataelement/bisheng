"""Replay only public failure metadata, never unrelated task output."""

import json

from bisheng.linsight.domain.services.task_failure_payload import task_failure_payload


def test_replay_redacts_legacy_diagnostics_and_excludes_internal_output():
    payload = task_failure_payload(
        {
            "error_message": "Provider failed https://internal.test password=secret-value",
            "detail": "api_key=private-key http://private.test",
            "failure_info": {"version": 99, "category": "model_service"},
            "exception": "raw-exception",
            "private_credentials": "do-not-export",
            "answer": "private-answer",
        }
    )
    serialized = json.dumps(payload)
    for secret in (
        "internal.test",
        "secret-value",
        "private-key",
        "private.test",
        "do-not-export",
        "raw-exception",
        "private-answer",
    ):
        assert secret not in serialized
    assert "failure_info" not in payload
    assert payload["error_type"] == "unknown"


def test_replay_tolerates_a_missing_legacy_result():
    payload = task_failure_payload(None)
    assert payload["error"] == "Task failed"
    assert payload["error_type"] == "unknown"
