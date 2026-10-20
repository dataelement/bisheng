"""F086 T14: SubflowNode runs a real child engine end to end.

覆盖 AC: AC-01、AC-13、AC-14、AC-17、AC-19、AC-20、AC-21
"""

import pytest

from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.nodes.subflow.subflow import parse_subflow_error
from test.workflow.subflow_helpers import (
    FlowStore,
    RecordingCallback,
    chain,
    edge,
    end,
    node,
    output,
    patched_env,
    run_parent,
    start,
    subflow_node,
)


@pytest.fixture
def store():
    flows = FlowStore()
    with patched_env(flows):
        yield flows


def _parent(*middle: dict, end_results: dict[str, str] | None = None, custom_variables=None) -> dict:
    return chain(start("start_p", custom_variables), *middle, end("end_p", end_results))


def _result(workflow, node_id: str = "subflow_1"):
    return workflow.graph_engine.graph_state.variables_pool.get(node_id)


def _subflow_log(callback: RecordingCallback, node_id: str = "subflow_1") -> list[dict]:
    ends = [one for one in callback.node_ends() if one.node_id == node_id]
    assert len(ends) == 1
    items = [item for round_ in ends[0].log_data for item in round_ if item["type"] == "subflow_logs"]
    assert len(items) == 1
    assert items[0]["key"] == "subflow_logs"
    return items[0]["value"]


def test_inputs_override_child_variables_by_name(store):
    store.add(
        "child",
        chain(
            start(
                custom_variables=[
                    {"key": "k1", "label": "city", "value": "Beijing"},
                    {"key": "k2", "label": "days", "value": "1"},
                    {"key": "k3", "label": "keep", "value": "own"},
                ]
            ),
            end(
                "end_c",
                {
                    "city": "start_c.custom_variables#k1",
                    "days": "start_c.custom_variables#k2",
                    "keep": "start_c.custom_variables#k3",
                },
            ),
        ),
    )
    inputs = [
        {"key": "city", "type": "input", "value": 123},
        {"key": "days", "type": "ref", "value": "start_p.custom_variables#pk"},
        {"key": "not_in_child", "type": "input", "value": "ignored"},
        # Left empty in the editor: the child keeps its own value.
        {"key": "keep", "type": "input", "value": ""},
    ]
    parent = _parent(
        subflow_node("subflow_1", "child", inputs),
        custom_variables=[{"key": "pk", "label": "lst", "value": [1, {"a": 2}]}],
    )

    workflow, status, reason = run_parent(parent)

    assert status == WorkflowStatus.SUCCESS.value, reason
    assert _result(workflow) == {"city": "123", "days": [1, {"a": 2}], "keep": "own"}


def test_plain_output_node_does_not_stop_the_child_and_stays_silent(store):
    store.add("child", chain(start(), output("output_c"), end("end_c", {"said": "output_c.message"})))
    callback = RecordingCallback()

    workflow, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")), callback)

    assert status == WorkflowStatus.SUCCESS.value, reason
    assert _result(workflow) == {"said": "hello"}
    # The parent's own start node sends its guide word; nothing comes from the child.
    child_events = [name for name, data in callback.events if data.node_id in ("start_c", "output_c", "end_c")]
    assert child_events == []
    assert "on_output_msg" not in [name for name, _ in callback.events]
    assert {data.node_id for name, data in callback.events if name.startswith("on_node")} == {
        "start_p",
        "subflow_1",
        "end_p",
    }


def test_end_nodes_merge_in_execution_order(store):
    child = {
        "nodes": [
            start(
                custom_variables=[
                    {"key": "k1", "label": "x1", "value": "1"},
                    {"key": "k2", "label": "x2", "value": "2"},
                ]
            ),
            end("end_early", {"a": "start_c.custom_variables#k1", "b": "start_c.custom_variables#k1"}),
            output("output_c"),
            end("end_late", {"b": "start_c.custom_variables#k2"}),
        ],
        "edges": [edge("start_c", "end_early"), edge("start_c", "output_c"), edge("output_c", "end_late")],
    }
    store.add("child", child)

    workflow, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")))

    assert status == WorkflowStatus.SUCCESS.value, reason
    assert _result(workflow) == {"a": "1", "b": "2"}


def test_switch_off_gives_empty_result(store):
    store.add("child", chain(start(), end("end_c", None)))
    workflow, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")))
    assert status == WorkflowStatus.SUCCESS.value, reason
    assert not _result(workflow)


def test_two_calls_of_the_same_child_are_independent(store):
    store.add(
        "child",
        chain(
            start(custom_variables=[{"key": "k1", "label": "v", "value": "default"}]),
            end("end_c", {"v": "start_c.custom_variables#k1"}),
        ),
    )
    parent = _parent(
        subflow_node("subflow_1", "child", [{"key": "v", "type": "input", "value": "first"}]),
        subflow_node("subflow_2", "child", [{"key": "v", "type": "input", "value": "second"}]),
        end_results={"one": "subflow_1.v", "two": "subflow_2.v"},
    )

    workflow, status, reason = run_parent(parent)

    assert status == WorkflowStatus.SUCCESS.value, reason
    assert _result(workflow, "subflow_1") == {"v": "first"}
    assert _result(workflow, "subflow_2") == {"v": "second"}


def test_missing_referenced_output_fails_with_10562(store):
    store.add("child", chain(start(), end("end_c", {"a": "start_c.current_time"})))
    parent = _parent(subflow_node("subflow_1", "child"), end_results={"x": "subflow_1.a", "y": "subflow_1.gone#0"})

    _, status, reason = run_parent(parent)

    assert status == WorkflowStatus.FAILED.value
    error = parse_subflow_error(reason)
    assert error["status_code"] == 10562
    assert error["data"] == {"subflow_name": "Flow child", "output_name": "gone"}


def test_unreferenced_missing_output_is_not_an_error(store):
    store.add("child", chain(start(), end("end_c", {"a": "start_c.current_time"})))
    snapshot = subflow_node("subflow_1", "child")
    snapshot["data"]["group_params"][0]["params"][2]["value"] = [{"key": "a"}, {"key": "removed_later"}]

    _, status, reason = run_parent(_parent(snapshot, end_results={"x": "subflow_1.a"}))

    assert status == WorkflowStatus.SUCCESS.value, reason


def test_missing_child_fails_with_10561(store):
    _, status, reason = run_parent(_parent(subflow_node("subflow_1", "deleted")))
    assert status == WorkflowStatus.FAILED.value
    assert parse_subflow_error(reason)["status_code"] == 10561


def test_child_that_cannot_be_built_fails_with_10560_and_no_node_name(store):
    # A node without any edge makes GraphEngine refuse to build.
    store.add("child", {"nodes": [start(), node("boom_1", "boom")], "edges": []})

    _, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")))

    error = parse_subflow_error(reason)
    assert status == WorkflowStatus.FAILED.value
    assert error["status_code"] == 10560
    assert error["data"]["subflow_name"] == "Flow child"
    assert error["data"]["node_name"] == ""
    assert "must have at least one edge" in error["data"]["reason"]


@pytest.mark.parametrize(
    "message",
    ["kaput", "boom_1 -- has run more than the maximum number of times."],
)
def test_inner_node_failure_fails_parent_with_10560(store, message):
    store.add(
        "child",
        chain(start(), node("boom_1", "boom", [{"key": "message", "value": message}], name="Boom"), end("end_c", None)),
    )
    callback = RecordingCallback()

    _, status, reason = run_parent(_parent(subflow_node("subflow_1", "child", name="Call child")), callback)

    assert status == WorkflowStatus.FAILED.value
    error = parse_subflow_error(reason)
    assert error["status_code"] == 10560
    assert error["data"] == {"subflow_name": "Flow child", "node_name": "Boom", "reason": message}

    logs = _subflow_log(callback)
    assert [(one["node_id"], one["type"]) for one in logs] == [("start_c", "start"), ("boom_1", "boom")]
    assert logs[1]["reason"] == message
    assert next(one for one in callback.node_ends() if one.node_id == "subflow_1").reason == reason


def test_success_log_lists_inner_nodes_with_timing(store):
    store.add("child", chain(start(), output("output_c"), end("end_c", {"said": "output_c.message"})))
    callback = RecordingCallback()

    _, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")), callback)

    assert status == WorkflowStatus.SUCCESS.value, reason
    logs = _subflow_log(callback)
    assert [one["node_id"] for one in logs] == ["start_c", "output_c", "end_c"]
    assert [one["type"] for one in logs] == ["start", "output", "end"]
    for one in logs:
        assert set(one) == {"node_id", "name", "type", "duration_ms", "reason", "log_data", "input_data"}
        assert one["reason"] is None
    assert logs[2]["log_data"] == [[{"key": "return_results", "value": {"said": "hello"}, "type": "params"}]]
