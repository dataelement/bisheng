"""Project a persisted task failure onto its public replay event."""

from bisheng.common.services.failure_context import FailureContextAdapter

_METADATA_FIELDS = (
    "failure_info",
    "reference_id",
    "execution_id",
    "attempt_id",
    "recovery_subject_id",
    "model_id",
    "rate_limit_state",
    "resume_mode",
)


def task_failure_payload(output_result: dict | None) -> dict:
    raw = output_result if isinstance(output_result, dict) else {}
    public = FailureContextAdapter.public_payload(raw)
    payload = {key: public[key] for key in _METADATA_FIELDS if key in public}
    payload.update(
        error=FailureContextAdapter.public_text(raw.get("error_message") or "Task failed"),
        error_code=public.get("error_code"),
        error_type=public.get("error_type") or "unknown",
    )
    if isinstance(raw.get("detail"), str):
        payload["detail"] = FailureContextAdapter.public_text(raw["detail"])
    return payload
