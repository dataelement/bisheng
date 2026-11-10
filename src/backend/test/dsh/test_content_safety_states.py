"""Coverage AC: AC-33, AC-34, AC-41. Pure state reduction; no persistence or model runtime."""

from copy import deepcopy

import pytest

from bisheng.common.errcode.dsh import DshContentSafetyConflictError
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyEvent

STATES = ("PASSED", "BLOCKED", "ERROR", "DISABLED", "NOT_APPLICABLE", "UNREPORTED")
# Literal AC-34 decision table, in the input/output order above.
EXPECTED = (
    ("PASSED", "BLOCKED", "ERROR", "PASSED", "PASSED", "UNREPORTED"),
    ("BLOCKED", "BLOCKED", "BLOCKED", "BLOCKED", "BLOCKED", "BLOCKED"),
    ("ERROR", "BLOCKED", "ERROR", "ERROR", "ERROR", "ERROR"),
    ("PASSED", "BLOCKED", "ERROR", "DISABLED", "NOT_APPLICABLE", "UNREPORTED"),
    ("PASSED", "BLOCKED", "ERROR", "NOT_APPLICABLE", "NOT_APPLICABLE", "UNREPORTED"),
    ("UNREPORTED", "BLOCKED", "ERROR", "UNREPORTED", "UNREPORTED", "UNREPORTED"),
)
MATRIX = [(left, right, EXPECTED[i][j]) for i, left in enumerate(STATES) for j, right in enumerate(STATES)]


def safety_event(factory, input_state, output_state, *, version=1, input_version=None, output_version=None, **changes):
    """Construct validated facts, rather than a test implementation of reduction."""
    payload = factory(
        gateway_request_id="99999999-9999-4999-8999-999999999999",
        hit_count=1 if "BLOCKED" in (input_state, output_state) else 0,
        rule_refs=["synthetic-rule-1"] if "BLOCKED" in (input_state, output_state) else [],
        stage_results={"input": input_state, "output": output_state},
        stage_versions={
            "input": (0 if input_state == "UNREPORTED" else version) if input_version is None else input_version,
            "output": (0 if output_state == "UNREPORTED" else version) if output_version is None else output_version,
        },
        event_version=version,
        **changes,
    )
    return ContentSafetyEvent.model_validate(payload)


@pytest.mark.parametrize("input_state,output_state,expected", MATRIX)
def test_all_36_phase_combinations_follow_literal_precedence(content_safety_event, input_state, output_state, expected):
    from bisheng.dsh.domain.services.content_safety_states import reduce_safety

    event = safety_event(content_safety_event, input_state, output_state)
    reduced = reduce_safety(None, event)
    assert reduced["content_safety_state"] == expected
    assert reduced["input_safety_state"] == input_state
    assert reduced["output_safety_state"] == output_state
    assert reduced["input_sensitive_hit"] is (input_state == "BLOCKED")
    assert reduced["output_sensitive_hit"] is (output_state == "BLOCKED")
    assert reduced["has_sensitive_hit"] is (input_state == "BLOCKED" or output_state == "BLOCKED")


def test_no_event_remains_unreported_and_preserves_unknown_instead_of_pass():
    from bisheng.dsh.domain.services.content_safety_states import reduce_safety

    reduced = reduce_safety(None, None)
    assert reduced["content_safety_state"] == "UNREPORTED"
    assert reduced["input_safety_state"] == reduced["output_safety_state"] == "UNREPORTED"
    assert reduced["input_safety_version"] == reduced["output_safety_version"] == 0
    assert not reduced["has_sensitive_hit"]
    assert reduce_safety(reduced, None) == reduced


def test_partial_stage_report_is_unreported_until_other_phase_is_known(content_safety_event):
    from bisheng.dsh.domain.services.content_safety_states import reduce_safety

    first = reduce_safety(None, safety_event(content_safety_event, "PASSED", "UNREPORTED"))
    assert first["content_safety_state"] == "UNREPORTED"
    final = safety_event(content_safety_event, "PASSED", "PASSED", version=2, input_version=1, event_kind="FINAL")
    result = reduce_safety(first, final)
    assert result["content_safety_state"] == "PASSED"
    assert result["input_safety_version"] == 1
    assert result["output_safety_version"] == 2


def test_repeat_is_idempotent_and_reducer_does_not_mutate_arguments(content_safety_event):
    from bisheng.dsh.domain.services.content_safety_states import reduce_safety

    event = safety_event(content_safety_event, "PASSED", "BLOCKED", version=3)
    event_before = event.model_dump()
    first = reduce_safety(None, event)
    first_before = deepcopy(first)
    assert reduce_safety(first, event) == first
    assert first == first_before and event.model_dump() == event_before
    assert first["has_sensitive_hit"] and first["output_sensitive_hit"]


@pytest.mark.parametrize("direction", ["input", "output"])
def test_old_version_hit_accumulates_without_overwriting_newer_phase_version(content_safety_event, direction):
    from bisheng.dsh.domain.services.content_safety_states import reduce_safety

    recent = reduce_safety(None, safety_event(content_safety_event, "PASSED", "PASSED", version=5))
    old = safety_event(
        content_safety_event,
        "BLOCKED" if direction == "input" else "PASSED",
        "BLOCKED" if direction == "output" else "PASSED",
        version=2,
    )
    result = reduce_safety(recent, old)
    assert result[f"{direction}_safety_state"] == "PASSED"
    assert result[f"{direction}_safety_version"] == 5
    assert result[f"{direction}_sensitive_hit"] is True
    assert result["has_sensitive_hit"] is True
    assert result["content_safety_state"] == "BLOCKED"
    assert reduce_safety(result, old) == result


@pytest.mark.parametrize("terminal", STATES[:-1])
def test_drain_old_unknown_snapshot_cannot_reopen_a_terminal_phase(content_safety_event, terminal):
    from bisheng.dsh.domain.services.content_safety_states import reduce_safety

    current = reduce_safety(None, safety_event(content_safety_event, terminal, "NOT_APPLICABLE", version=2))
    drain = safety_event(
        content_safety_event, "UNREPORTED", "UNREPORTED", version=3, event_kind="DRAIN", drain_status="FINISHED"
    )
    assert reduce_safety(current, drain) == current


def test_same_phase_version_different_fact_is_explicit_conflict(content_safety_event):
    from bisheng.dsh.domain.services.content_safety_states import reduce_safety

    current = reduce_safety(None, safety_event(content_safety_event, "PASSED", "UNREPORTED", version=2))
    before = deepcopy(current)
    conflicting = safety_event(content_safety_event, "BLOCKED", "UNREPORTED", version=2)
    with pytest.raises(DshContentSafetyConflictError):
        reduce_safety(current, conflicting)
    assert current == before


@pytest.mark.parametrize("terminal", STATES[:-1])
def test_newer_contradictory_terminal_fact_is_rejected_without_clearing_hit(content_safety_event, terminal):
    from bisheng.dsh.domain.services.content_safety_states import reduce_safety

    current = reduce_safety(None, safety_event(content_safety_event, terminal, "NOT_APPLICABLE", version=2))
    before = deepcopy(current)
    changed = "PASSED" if terminal != "PASSED" else "BLOCKED"
    conflicting = safety_event(content_safety_event, changed, "NOT_APPLICABLE", version=3, output_version=2)
    with pytest.raises(DshContentSafetyConflictError):
        reduce_safety(current, conflicting)
    assert current == before
    if terminal == "BLOCKED":
        assert current["has_sensitive_hit"]


def test_later_unchanged_snapshot_preserves_each_stage_version(content_safety_event):
    from bisheng.dsh.domain.services.content_safety_states import reduce_safety

    current = reduce_safety(
        None, safety_event(content_safety_event, "DISABLED", "NOT_APPLICABLE", version=2, input_version=1)
    )
    drain = safety_event(
        content_safety_event,
        "DISABLED",
        "NOT_APPLICABLE",
        version=7,
        input_version=1,
        output_version=2,
        event_kind="DRAIN",
        drain_status="NOT_REQUIRED",
    )
    assert reduce_safety(current, drain) == current
    assert current["content_safety_state"] == "NOT_APPLICABLE"
