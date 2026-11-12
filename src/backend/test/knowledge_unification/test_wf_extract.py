"""Workflow bindings use persisted semantic slots, never runtime/history data.

覆盖 AC: AC-71, AC-87, AC-88. No runtime model or knowledge services are loaded.
"""

from copy import deepcopy

import pytest

from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey
from bisheng.workflow.domain.services.reference_extractor import extract_workflow_version_references


def node(node_id, node_type, **params):
    return {
        "id": f"canvas-{node_id}",
        "data": {
            "id": node_id,
            "type": node_type,
            "group_params": [{"name": "settings", "params": [{"key": k, "value": v} for k, v in params.items()]}],
        },
    }


def graph(*nodes, **other):
    return {"nodes": list(nodes), "edges": [], **other}


def ref(slot, target_type, target_id):
    return ReferenceSpec(slot, TargetKey(target_type, str(target_id)))


def selection(*ids, kind="space"):
    return {"type": kind, "value": [{"key": value, "label": "display only"} for value in ids]}


def test_actual_node_fields_keep_same_target_in_distinct_semantic_slots():
    data = graph(
        node("rag-a", "rag", model_id=7, knowledge=selection(31, 32, 31)),
        node("agent-b", "agent", model_id="007", knowledge_id=selection("31", kind="knowledge")),
        node("retriever-c", "knowledge_retriever", knowledge=selection(32)),
        node("qa-d", "qa_retriever", qa_knowledge_id=[{"key": 33}]),
    )
    assert set(extract_workflow_version_references(data)) == {
        ref("node:rag-a.model_id", "model", 7),
        ref("node:agent-b.model_id", "model", 7),
        ref("node:rag-a.knowledge", "knowledge_space", 31),
        ref("node:rag-a.knowledge", "knowledge_space", 32),
        ref("node:agent-b.knowledge_id", "knowledge_space", 31),
        ref("node:retriever-c.knowledge", "knowledge_space", 32),
        ref("node:qa-d.qa_knowledge_id", "knowledge_space", 33),
    }


def test_disabled_saved_rerank_model_remains_a_reference():
    data = graph(node("r", "rag", advanced_retrieval_switch={"rerank_flag": False, "rerank_model": 18}))
    assert extract_workflow_version_references(data) == (
        ref("node:r.advanced_retrieval_switch.rerank_model", "model", 18),
    )


def test_node_and_multiselect_reordering_do_not_change_slots_or_output():
    first = node("first", "llm", model_id=9)
    second = node("second", "rag", knowledge=selection(32, 31))
    initial = extract_workflow_version_references(graph(first, second))
    second["data"]["group_params"][0]["params"][0]["value"]["value"].reverse()
    assert extract_workflow_version_references(graph(second, first)) == initial


def test_deleting_one_slot_retains_other_slot_to_same_target():
    first = node("a", "llm", model_id=9)
    second = node("b", "llm", model_id=9)
    initial = set(extract_workflow_version_references(graph(first, second)))
    remaining = set(extract_workflow_version_references(graph(second)))
    assert initial - remaining == {ref("node:a.model_id", "model", 9)}
    assert remaining == {ref("node:b.model_id", "model", 9)}


@pytest.mark.parametrize("status", ["draft", "offline", "noncurrent"])
def test_saved_version_status_does_not_discard_references(status):
    data = graph(node("n", "llm", model_id=8), status=status, is_current=0)
    assert extract_workflow_version_references(data) == (ref("node:n.model_id", "model", 8),)


def test_no_arbitrary_recursive_keys_temporary_variables_or_history_sources():
    data = graph(
        node("input", "input", model_id=8, files=[{"file_id": 21}]),
        node("tmp", "rag", knowledge=selection("input.file_output", kind="tmp")),
        node("note", "note", model_id=9, knowledge=selection(31)),
        node("tool", "tool", model_id=9, params={"knowledge_id": 31}),
        node("llm", "llm", prompt={"model_id": 19, "file_id": 22}),
        history={"model_id": 8},
        messages=[{"knowledge_id": 31}],
        evaluation={"model_id": 9},
        tasks=[{"model_id": 18}],
        data={"model_id": 77},
    )
    assert extract_workflow_version_references(data) == ()


def test_metadata_document_id_comparison_is_not_a_physical_file_selector():
    data = graph(
        node(
            "retriever",
            "knowledge_retriever",
            knowledge=selection(31),
            metadata_filter={
                "enabled": True,
                "conditions": [
                    {
                        "id": "filter-a",
                        "knowledge_id": 31,
                        "metadata_field": "document_id",
                        "comparison_operation": "equals",
                        "right_value_type": "input",
                        "right_value": "47",
                    }
                ],
            },
        )
    )
    assert extract_workflow_version_references(data) == (ref("node:retriever.knowledge", "knowledge_space", 31),)


@pytest.mark.parametrize("data", [None, {}, {"nodes": [], "edges": []}, graph(node("n", "rag"))])
def test_incomplete_draft_with_no_configured_target_is_an_explicit_empty_set(data):
    assert extract_workflow_version_references(data) == ()


def test_runtime_uses_inner_node_id_and_last_parameter_value():
    actual = node("inner", "llm", model_id=7)
    actual["data"]["group_params"].append({"params": [{"key": "model_id", "value": 8}]})
    assert extract_workflow_version_references(graph(actual)) == (ref("node:inner.model_id", "model", 8),)


@pytest.mark.parametrize("target_id", [True, -1, "-1", "name", "1.2", [3], {"id": 3}])
def test_nonempty_invalid_target_is_rejected_instead_of_silently_omitted(target_id):
    with pytest.raises(ValueError):
        extract_workflow_version_references(graph(node("n", "llm", model_id=target_id)))


@pytest.mark.parametrize("target_id", [None, "", 0, "0"])
def test_unconfigured_model_placeholder_does_not_make_draft_unsaveable(target_id):
    assert extract_workflow_version_references(graph(node("n", "llm", model_id=target_id))) == ()


def test_reference_bearing_node_without_stable_id_or_duplicate_id_is_rejected():
    with pytest.raises(ValueError, match="node ID"):
        extract_workflow_version_references(graph(node("", "llm", model_id=7)))
    with pytest.raises(ValueError, match="node ID"):
        extract_workflow_version_references(graph(node("n", "llm", model_id=7), node("n", "llm", model_id=8)))


def test_extraction_never_mutates_saved_configuration():
    data = graph(node("rag", "rag", model_id="007", knowledge=selection("031", 32)))
    before = deepcopy(data)
    extract_workflow_version_references(data)
    assert data == before
