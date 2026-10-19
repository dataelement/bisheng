"""F086 T15: SubflowNode run-time guard, run context and stop.

覆盖 AC: AC-06、AC-09、AC-16、AC-21
"""

from unittest.mock import patch

import pytest

from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.nodes.subflow.subflow import parse_subflow_error
from test.workflow.subflow_helpers import (
    PARENT_START_TIME,
    FlowStore,
    RecordingCallback,
    chain,
    dialog_input,
    end,
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


def _parent(*middle: dict, end_results: dict[str, str] | None = None) -> dict:
    return chain(start("start_p"), *middle, end("end_p", end_results))


def _assert_forbidden(reason: str, node_name: str) -> None:
    error = parse_subflow_error(reason)
    assert error["status_code"] == 10563, reason
    assert error["data"] == {"subflow_name": "Flow child", "node_name": node_name}


def test_nested_subflow_node_fails_with_10563(store):
    store.add("grandchild", chain(start(), end("end_g", None)))
    store.add("child", chain(start(), subflow_node("inner", "grandchild", name="Inner call"), end("end_c", None)))

    _, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")))

    assert status == WorkflowStatus.FAILED.value
    _assert_forbidden(reason, "Inner call")


def test_input_node_that_waits_fails_with_10563(store):
    store.add("child", chain(start(), dialog_input("input_c"), end("end_c", None)))
    callback = RecordingCallback()

    _, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")), callback)

    assert status == WorkflowStatus.FAILED.value
    _assert_forbidden(reason, "input_c")
    assert "on_user_input" not in [name for name, _ in callback.events]


def test_input_node_with_empty_form_is_caught_after_it_ran(store):
    store.add("child", chain(start(), dialog_input("input_c"), end("end_c", None)))
    with (
        patch("bisheng.workflow.nodes.input.input.InputNode.get_input_schema", return_value=None),
        patch("bisheng.workflow.nodes.input.input.InputNode._run", return_value={}),
    ):
        _, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")))

    assert status == WorkflowStatus.FAILED.value
    _assert_forbidden(reason, "input_c")


@pytest.mark.parametrize("output_type", ["choose", "input"])
def test_interactive_output_node_fails_with_10563(store, output_type):
    store.add("child", chain(start(), output("output_c", output_type), end("end_c", None)))
    callback = RecordingCallback()

    _, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")), callback)

    assert status == WorkflowStatus.FAILED.value
    _assert_forbidden(reason, "output_c")
    names = [name for name, _ in callback.events]
    assert "on_output_choose" not in names
    assert "on_output_input" not in names


def test_child_runs_with_parent_context(store):
    store.add(
        "child",
        chain(
            start(),
            end(
                "end_c",
                {"hist": "start_c.chat_history", "now": "start_c.current_time", "user": "start_c.user_info"},
            ),
        ),
        user_id=77,
    )

    from bisheng.workflow.graph import workflow as workflow_module

    built = []
    original = workflow_module.Workflow.__init__

    def spy_init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        built.append(self)
        if len(built) == 1:
            # The parent conversation already has one exchange.
            self.graph_engine.graph_state.save_context("earlier question", "human")
            self.graph_engine.graph_state.save_context("earlier answer", "AI")

    with patch.object(workflow_module.Workflow, "__init__", spy_init):
        workflow, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")), tmp_session_id="debug-1")

    assert status == WorkflowStatus.SUCCESS.value, reason
    result = workflow.graph_engine.graph_state.variables_pool["subflow_1"]
    assert "earlier question" in result["hist"]
    assert "earlier answer" in result["hist"]
    assert result["now"] == PARENT_START_TIME

    child_engine = built[1].graph_engine
    assert child_engine.user_id == 5
    assert child_engine.workflow_id == "parent_wf"
    assert child_engine.workflow_name == "Parent"
    assert child_engine.tenant_id == 1
    assert child_engine.flow_user_id == 77
    assert child_engine.tmp_session_id == "debug-1"
    assert child_engine.max_steps == 5
    assert child_engine.subflow_depth == 1


def test_stop_reaches_the_child_and_is_not_wrapped(store):
    store.add("child", chain(start(), output("output_c"), end("end_c", None)))
    # The first check (start node start) says go on; the second (its end) says stop.
    callback = RecordingCallback(stop_after=1)

    _, status, reason = run_parent(_parent(subflow_node("subflow_1", "child")), callback)

    assert status == WorkflowStatus.FAILED.value
    assert reason == "stop by user"
    assert parse_subflow_error(reason) is None
    assert callback.stop_checks == 2
