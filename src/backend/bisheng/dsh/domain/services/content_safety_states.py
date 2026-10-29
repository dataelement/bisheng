"""Pure per-stage safety reduction, independent of identity and model execution."""

from collections.abc import Mapping

from bisheng.common.errcode.dsh import DshContentSafetyConflictError
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyEvent


def reduce_safety(existing: Mapping | None, event: ContentSafetyEvent | None) -> dict:
    """Return new summary values; stale hits survive while terminal facts stay closed.

    The caller supplies validated events and the existing request's summary. It
    owns event deduplication, request association and the surrounding transaction.
    No argument is mutated, including when a conflicting stage raises an error.
    """
    defaults = {
        "input_safety_state": "UNREPORTED",
        "output_safety_state": "UNREPORTED",
        "input_safety_version": 0,
        "output_safety_version": 0,
        "input_sensitive_hit": False,
        "output_sensitive_hit": False,
        "has_sensitive_hit": False,
        "content_safety_state": "UNREPORTED",
    }
    result = {key: existing.get(key, value) if existing is not None else value for key, value in defaults.items()}
    for direction in ("input", "output"):
        state_key = f"{direction}_safety_state"
        version_key = f"{direction}_safety_version"
        hit_key = f"{direction}_sensitive_hit"
        current_state, current_version = result[state_key], result[version_key]
        result[hit_key] = bool(result[hit_key] or current_state == "BLOCKED")
        if event is None:
            continue
        incoming_state = getattr(event.stage_results, direction)
        incoming_version = getattr(event.stage_versions, direction)
        # Version comparison cannot discard an earlier confirmed hit.
        result[hit_key] |= incoming_state == "BLOCKED"
        if incoming_version < current_version:
            continue
        if incoming_version == current_version:
            if incoming_state != current_state:
                raise DshContentSafetyConflictError()
            continue
        if current_state != "UNREPORTED" and incoming_state != current_state:
            raise DshContentSafetyConflictError()
        result[state_key], result[version_key] = incoming_state, incoming_version

    result["has_sensitive_hit"] = bool(
        result["has_sensitive_hit"] or result["input_sensitive_hit"] or result["output_sensitive_hit"]
    )
    phases = (result["input_safety_state"], result["output_safety_state"])
    if result["has_sensitive_hit"]:
        result["content_safety_state"] = "BLOCKED"
    elif "ERROR" in phases:
        result["content_safety_state"] = "ERROR"
    elif "UNREPORTED" in phases:
        result["content_safety_state"] = "UNREPORTED"
    elif phases == ("DISABLED", "DISABLED"):
        result["content_safety_state"] = "DISABLED"
    elif "PASSED" in phases:
        result["content_safety_state"] = "PASSED"
    else:
        result["content_safety_state"] = "NOT_APPLICABLE"
    return result
