"""Builders for F086 subflow tests: minimal workflow JSON and a parent engine."""

from contextlib import ExitStack
from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import NodeType
from bisheng.workflow.nodes.base import BaseNode

PARENT_START_TIME = "2026-01-02 03:04:05"


def node(node_id: str, node_type: str, params: list[dict] | None = None, name: str = "", **extra) -> dict:
    data = {
        "id": node_id,
        "type": node_type,
        "name": name or node_id,
        "v": 2,
        "group_params": [{"name": "", "params": params or []}],
        **extra,
    }
    return {"id": node_id, "data": data}


def edge(source: str, target: str, handle: str = "right_handle") -> dict:
    return {
        "id": f"{source}-{handle}-{target}",
        "source": source,
        "sourceHandle": handle,
        "target": target,
        "targetHandle": "left_handle",
    }


def start(node_id: str = "start_c", custom_variables: list[dict] | None = None) -> dict:
    return node(
        node_id,
        "start",
        [
            {"key": "guide_word", "value": "child guide word"},
            {"key": "guide_question", "value": ["child question"]},
            {"key": "preset_question", "value": []},
            {"key": "custom_variables", "value": custom_variables or []},
        ],
    )


def end(node_id: str, results: dict[str, str] | None, name: str = "") -> dict:
    """End node; ``results`` maps return name -> variable reference, ``None`` = switch off."""
    if results is None:
        return node(node_id, "end", name=name)
    return node(
        node_id,
        "end",
        [
            {"key": "return_enabled", "value": True},
            {
                "key": "return_results",
                "value": [{"key": k, "type": "ref", "value": v} for k, v in results.items()],
            },
        ],
        name=name,
    )


def output(node_id: str, output_type: str = "", msg: str = "hello") -> dict:
    params = [
        {"key": "output_msg", "value": {"msg": msg, "files": []}},
        {"key": "output_result", "value": {"type": output_type, "value": ""}, "options": []},
    ]
    return node(node_id, "output", params)


def dialog_input(node_id: str) -> dict:
    return node(
        node_id,
        "input",
        [{"key": "user_input", "value": ""}, {"key": "dialog_files_content", "value": []}],
        tab={"value": "dialog_input"},
    )


def chain(*nodes: dict) -> dict:
    """Workflow whose nodes run one after another in the given order."""
    ids = [one["id"] for one in nodes]
    return {"nodes": list(nodes), "edges": [edge(a, b) for a, b in pairwise(ids)]}


def subflow_node(node_id: str, flow_id: str, inputs: list[dict] | None = None, name: str = "") -> dict:
    return node(
        node_id,
        "subflow",
        [
            {"key": "subflow_id", "value": {"id": flow_id, "name": f"snapshot {flow_id}"}},
            {"key": "subflow_inputs", "value": inputs or []},
            {"key": "subflow_outputs", "value": []},
        ],
        name=name or node_id,
    )


class BoomNode(BaseNode):
    """Test-only node type that fails with the message in its ``message`` param."""

    def _run(self, unique_id: str):
        from bisheng.utils.exceptions import IgnoreException

        raise IgnoreException(self.node_params.get("message", "boom"))


class RecordingCallback(BaseCallback):
    """Parent callback: records every event and answers the stop check like RedisCallback."""

    def __init__(self, stop_after: int | None = None):
        super().__init__()
        self.events: list[tuple[str, object]] = []
        self.stop_checks = 0
        self.stop_after = stop_after

    def _record(self, name: str, data) -> None:
        self.events.append((name, data))

    def on_node_start(self, data):
        self._record("on_node_start", data)

    def on_node_end(self, data):
        self._record("on_node_end", data)

    def on_user_input(self, data):
        self._record("on_user_input", data)

    def on_guide_word(self, data):
        self._record("on_guide_word", data)

    def on_guide_question(self, data):
        self._record("on_guide_question", data)

    def on_stream_msg(self, data):
        self._record("on_stream_msg", data)

    def on_stream_over(self, data):
        self._record("on_stream_over", data)

    def on_output_msg(self, data):
        self._record("on_output_msg", data)

    def on_output_choose(self, data):
        self._record("on_output_choose", data)

    def on_output_input(self, data):
        self._record("on_output_input", data)

    def get_workflow_stop(self) -> bool:
        self.stop_checks += 1
        return self.stop_after is not None and self.stop_checks > self.stop_after

    def node_ends(self) -> list:
        return [data for name, data in self.events if name == "on_node_end"]


class FlowStore:
    """In-memory replacement of FlowDao.get_flow_by_id."""

    def __init__(self):
        self.flows: dict[str, SimpleNamespace] = {}

    def add(self, flow_id: str, data: dict, name: str = "", user_id: int = 77) -> None:
        self.flows[flow_id] = SimpleNamespace(id=flow_id, name=name or f"Flow {flow_id}", data=data, user_id=user_id)

    def get_flow_by_id(self, flow_id: str):
        return self.flows.get(flow_id)


def patched_env(store: FlowStore) -> ExitStack:
    """Patch the database and object storage lookups the test nodes would make."""
    from bisheng.workflow.nodes import node_manage

    stack = ExitStack()
    stack.enter_context(patch("bisheng.workflow.nodes.subflow.subflow.FlowDao", store))
    stack.enter_context(patch("bisheng.workflow.nodes.output.output.get_minio_storage_sync", MagicMock()))
    for target in (
        "bisheng.workflow.nodes.start.start.UserDao.get_user",
        "bisheng.workflow.nodes.start.start.UserDepartmentDao.get_user_primary_department",
    ):
        stack.enter_context(patch(target, return_value=None))
    for target in (
        "bisheng.workflow.nodes.start.start.UserGroupDao.get_user_group",
        "bisheng.workflow.nodes.start.start.UserRoleDao.get_user_roles",
    ):
        stack.enter_context(patch(target, return_value=[]))
    stack.enter_context(patch.dict(node_manage.NODE_CLASS_MAP, {"boom": BoomNode}))
    return stack


def run_parent(parent_data: dict, callback=None, max_steps: int = 5, **kwargs):
    """Run ``parent_data`` as a top-level workflow; return (workflow, status, reason)."""
    from bisheng.workflow.graph.workflow import Workflow

    workflow = Workflow(
        "parent_wf",
        "Parent",
        user_id=kwargs.pop("user_id", 5),
        workflow_data=parent_data,
        max_steps=max_steps,
        callback=callback or RecordingCallback(),
        tenant_id=1,
        flow_user_id=6,
        **kwargs,
    )
    start_id = workflow.graph_engine.start_node_id
    workflow.graph_engine.nodes_map[start_id].node_params["current_time"] = PARENT_START_TIME
    status, reason = workflow.run()
    return workflow, status, reason


def node_types(workflow) -> dict[str, str]:
    return {k: v.type for k, v in workflow.graph_engine.nodes_map.items() if v.type != NodeType.FAKE_OUTPUT.value}
