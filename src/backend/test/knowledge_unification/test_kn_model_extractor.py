"""Knowledge owns the serving and pending model slots, never task parameters.

覆盖 AC: AC-68, AC-71, AC-74, AC-87, AC-88, AC-89, AC-91, AC-92.
"""

from copy import deepcopy

import pytest

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.model_reference_extractor import (
    KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
    extract_knowledge_model_references,
)


def transition(**changes):
    return {
        "schema_version": 1,
        "operation_id": "rebuild-1",
        "current_model_id": "11",
        "pending_model_id": "12",
        **changes,
    }


def refs(model, stage=None):
    return {
        (ref.slot_key, ref.target.target_type.value, ref.target.target_id)
        for ref in extract_knowledge_model_references(model=model, model_transition=stage)
    }


@pytest.mark.parametrize("kind", [0, 1, 3])
def test_real_entity_model_is_current_binding_for_library_qa_and_space(kind):
    resource = Knowledge(
        id=7, tenant_id=101, user_id=9, name="actual", type=kind, model="011", processing_defaults={"model_id": "99"}
    )
    assert refs(resource.model, resource.model_transition) == {("model", "model", "11")}
    assert resource.processing_defaults == {"model_id": "99"}
    assert KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION == "knowledge-model-v1"


def test_business_transition_keeps_old_current_and_pending_until_finalize_without_mutating_config():
    stage = transition()
    before = deepcopy(stage)
    assert refs("11", stage) == {("model", "model", "11"), ("model_transition.pending_model_id", "model", "12")}
    assert stage == before
    assert refs("12") == {("model", "model", "12")}


@pytest.mark.parametrize("empty", [None, ""])
def test_incomplete_saved_model_is_an_explicit_zero_source(empty):
    assert refs(empty) == set()


@pytest.mark.parametrize("model", ["missing", "0", "-1", True, "1.0", [], "\u0661"])
def test_malformed_current_model_is_not_silently_dropped(model):
    with pytest.raises(ReferenceCoverageNotReadyError):
        refs(model)


@pytest.mark.parametrize(
    "stage",
    [
        [],
        {},
        {"model_id": 12},
        transition(schema_version=True),
        transition(schema_version=2),
        transition(operation_id=""),
        transition(operation_id=None),
        transition(operation_id=" " * 3),
        transition(current_model_id="12"),
        transition(pending_model_id=None),
        transition(pending_model_id="missing"),
        transition(extra_model_id="99"),
        transition(phase="building"),
    ],
)
def test_unknown_or_inconsistent_transition_is_not_guessed_or_partially_extracted(stage):
    with pytest.raises(ReferenceCoverageNotReadyError):
        refs("11", stage)


def test_transition_needs_the_actual_current_model_not_only_its_own_claim():
    with pytest.raises(ReferenceCoverageNotReadyError):
        refs(None, transition())
