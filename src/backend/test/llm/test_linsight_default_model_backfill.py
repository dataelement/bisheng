"""F035 Track E — unit tests for the linsight default-model backfill (pure transform).

Mirrors the F034 ``relation_model_backfill`` test style: only the pure
``transform_linsight_llm_config`` is exercised; the DB read/write wrapper is
idempotent and benign, covered by startup self-heal.
"""

from bisheng.llm.domain.services.linsight_default_model_backfill import (
    transform_linsight_llm_config,
)


def test_skip_when_already_migrated():
    # No legacy task_model → nothing to do.
    payload = {"models": [{"id": "m1"}], "linsight_default_model_id": "m1"}
    out, action = transform_linsight_llm_config(payload)
    assert action == "skip"
    assert out is payload  # untouched


def test_kept_when_legacy_model_still_valid():
    payload = {"models": [{"id": "m1"}, {"id": "m2"}], "task_model": {"id": "m2"}, "linsight_executor_mode": "react"}
    out, action = transform_linsight_llm_config(payload)
    assert action == "kept"
    assert out["linsight_default_model_id"] == "m2"
    assert "task_model" not in out and "linsight_executor_mode" not in out
    # input not mutated
    assert "task_model" in payload


def test_first_when_legacy_model_gone():
    payload = {"models": [{"id": "m1"}, {"id": "m2"}], "task_model": {"id": "stale"}}
    out, action = transform_linsight_llm_config(payload)
    assert action == "first"
    assert out["linsight_default_model_id"] == "m1"


def test_empty_when_no_models():
    payload = {"models": [], "task_model": {"id": "m9"}}
    out, action = transform_linsight_llm_config(payload)
    assert action == "empty"
    assert out["linsight_default_model_id"] is None


def test_legacy_id_coerced_to_string():
    # task_model.id may be an int in legacy rows; matching must be type-tolerant.
    payload = {"models": [{"id": 7}], "task_model": {"id": 7}}
    out, action = transform_linsight_llm_config(payload)
    assert action == "kept"
    assert out["linsight_default_model_id"] == "7"
