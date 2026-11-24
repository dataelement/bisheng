"""Execution failures preserve authorized selections, locations and exact causes."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceKey, TargetKey
from bisheng.resource_reference.application.error_details import reference_error_details
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    AuthorizedTransientSnapshot,
    ReferenceTargetReadFact,
    canonical_payload_json,
    payload_digest,
)
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime


def setup_runtime(state):
    model = TargetKey("model", "375")
    live = TargetKey("model", "100")
    refs = (
        ReferenceSpec("node:llm_b1ef4.model_id", model),
        ReferenceSpec("node:other.model_id", model),
        ReferenceSpec("node:live.model_id", live),
    )
    payload = canonical_payload_json(
        {
            "graph": {
                "nodes": [
                    {"data": {"id": "llm_b1ef4", "name": "LLM"}},
                    {"data": {"id": "other", "name": "Summary"}},
                    {"data": {"id": "live", "name": "Healthy"}},
                ]
            }
        }
    )
    snapshot = AuthorizedSourceSnapshot(
        SourceKey(1, "workflow_version", "flow", "3876"), refs, "v1", payload_digest(payload), payload
    )
    facts = (ReferenceTargetReadFact(model, state, False, 1), ReferenceTargetReadFact(live, "valid", True, 1))
    runtime = object.__new__(ReferenceSourceReadRuntime)
    runtime.verifier = SimpleNamespace(
        aget_source_snapshot=AsyncMock(return_value=snapshot),
        get_source_snapshot=Mock(return_value=snapshot),
        aget_transient_snapshot=AsyncMock(
            return_value=AuthorizedTransientSnapshot(
                "workflow", "flow", 1, refs, "v1", payload_digest(payload), payload
            )
        ),
        _ainspect_targets=AsyncMock(return_value=facts),
        _inspect_targets=Mock(return_value=facts),
        arevalidate_scope=AsyncMock(),
        revalidate_scope=Mock(),
        arevalidate_transient_scope=AsyncMock(),
    )
    return runtime, snapshot


@pytest.mark.parametrize("mode", ["sync", "async", "transient"])
@pytest.mark.parametrize("state", ["invalid_missing", "invalid_deleted", "deleting", "invalid_scope"])
async def test_execution_reports_exact_state_and_all_affected_nodes(mode, state):
    runtime, _ = setup_runtime(state)
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        if mode == "sync":
            runtime.require_source_valid(None, SimpleNamespace(purpose="execute"), None)
        elif mode == "async":
            await runtime.arequire_source_valid(None, SimpleNamespace(purpose="execute"), None)
        else:
            await runtime.arequire_transient_valid(None, None, None)
    assert caught.value.kwargs == {
        "reason": "reference_target_invalid",
        "reference_errors": [
            {"node_id": "llm_b1ef4", "node_name": "LLM", "resource_type": "model", "target_id": "375", "state": state},
            {"node_id": "other", "node_name": "Summary", "resource_type": "model", "target_id": "375", "state": state},
        ],
    }
    if mode == "sync":
        runtime.verifier.revalidate_scope.assert_called_once()
    elif mode == "async":
        runtime.verifier.arevalidate_scope.assert_awaited_once()
    else:
        runtime.verifier.arevalidate_transient_scope.assert_awaited_once()


async def test_identity_revalidation_failure_takes_priority_over_resource_details():
    runtime, _ = setup_runtime("invalid_missing")
    runtime.verifier.arevalidate_scope.side_effect = ResourceReferenceInvalidError(reason="identity_changed")
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        await runtime.arequire_source_valid(None, SimpleNamespace(purpose="execute"), None)
    assert caught.value.kwargs == {"reason": "identity_changed"}


async def test_inspection_remains_available_to_repair_invalid_selections():
    runtime, snapshot = setup_runtime("invalid_missing")
    result = await runtime.ainspect_source(None, SimpleNamespace(purpose="inspect"), None)
    assert result.snapshot == snapshot
    assert not result.target_states[0].is_valid


def test_source_without_workflow_graph_and_bounded_diagnostics():
    refs = tuple(ReferenceSpec(f"slot{i}", TargetKey("knowledge_file", str(i))) for i in range(1, 12))
    result = reference_error_details(refs, dict.fromkeys((ref.target for ref in refs), "invalid_deleted"))
    assert len(result) == 5
    assert result[0] == {"resource_type": "knowledge_file", "target_id": "1", "state": "invalid_deleted"}


def test_unknown_node_still_reports_target_without_fabricating_a_name():
    _, snapshot = setup_runtime("invalid_missing")
    ref = replace(snapshot.references[0], slot_key="node:absent.model_id")
    assert reference_error_details((ref,), {ref.target: "invalid_missing"}, {"nodes": []}) == [
        {"resource_type": "model", "target_id": ref.target.target_id, "state": "invalid_missing"},
    ]


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (None, "unavailable"),
        (SimpleNamespace(online=False, model_type="llm"), "offline"),
        (SimpleNamespace(online=True, model_type="embedding"), "type_mismatch"),
    ],
)
def test_default_model_failure_explains_availability_and_type(model, expected):
    from bisheng.llm.application.model_default_validation import require_callable_default_models

    ref = ReferenceSpec("model_id", TargetKey("model", "375"))
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        require_callable_default_models("evaluation_llm", (ref,), {} if model is None else {375: model})
    assert caught.value.kwargs == {
        "reason": "model_default_models_unavailable",
        "reference_errors": [{"resource_type": "model", "target_id": "375", "state": expected}],
    }
