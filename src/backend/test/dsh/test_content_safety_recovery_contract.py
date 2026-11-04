"""Coverage AC: AC-66. Live metadata checks retain legacy and bounded-word contracts."""

from uuid import uuid4

import pytest

from test.dsh.test_content_safety_recovery_e2e import LiveSafetyError, validate_event_shape


def event():
    return {
        "schema_version": 1,
        "source_id": "synthetic",
        "event_id": str(uuid4()),
        "gateway_request_id": str(uuid4()),
        "backend_request_id": None,
        "session_id": None,
        "protocol": "CHAT",
        "event_kind": "DECISION",
        "event_version": 1,
        "request_started_at": "2026-10-27T00:00:00Z",
        "occurred_at": "2026-10-27T00:00:01Z",
        "received_at": "2026-10-27T00:00:02Z",
        "stage_results": {"input": "BLOCKED", "output": "NOT_APPLICABLE"},
        "stage_versions": {"input": 1, "output": 1},
        "policy_version": 1,
        "builtin_digest": "a" * 64,
        "hit_count": 1,
        "hit_count_truncated": False,
        "rule_refs": ["custom:1:1:0"],
        "forwarded": False,
        "drain_status": "NOT_REQUIRED",
        "conversation": None,
        "association_status": "UNASSOCIATED",
        "audit_request_id": None,
        "user_id": "1",
        "model_id": "8",
    }


@pytest.mark.parametrize("snapshot", [None, {"input": ["synthetic-word"], "output": []}])
def test_live_validator_accepts_optional_snapshot(snapshot):
    value = event()
    value["matched_words"] = snapshot
    validate_event_shape(value)


def test_live_validator_accepts_legacy_omission():
    validate_event_shape(event())


@pytest.mark.parametrize(
    "snapshot",
    [
        {"input": ["same", "same"], "output": []},
        {"input": ["x" * 257], "output": []},
        {"input": [" "], "output": []},
        {"input": [chr(0xD800)], "output": []},
        {"input": [str(i) for i in range(21)], "output": []},
        {"input": [], "output": ["wrong-stage"]},
        {"input": [], "output": [], "prompt": "forbidden-context"},
    ],
)
def test_live_validator_rejects_invalid_snapshot(snapshot):
    value = event()
    value["matched_words"] = snapshot
    with pytest.raises(LiveSafetyError):
        validate_event_shape(value)


def test_live_validator_rejects_unrelated_new_fields():
    value = event()
    value["prompt"] = "forbidden-context"
    with pytest.raises(LiveSafetyError):
        validate_event_shape(value)
