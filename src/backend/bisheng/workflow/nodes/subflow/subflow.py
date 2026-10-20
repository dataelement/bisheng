import copy
import json
from typing import Any

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.flow import (
    WorkFlowSubflowForbiddenNodeError,
    WorkFlowSubflowNotFoundError,
    WorkFlowSubflowOutputMissingError,
    WorkFlowSubflowRunError,
)
from bisheng.database.models.flow import FlowDao
from bisheng.utils.exceptions import IgnoreException
from bisheng.workflow.callback.subflow_callback import SubflowCallback
from bisheng.workflow.common.node import NodeType
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.domain.services.subflow_inspect import is_interactive_output
from bisheng.workflow.nodes.agent.skill_support import AGENT_SKILL_ERROR_MARKER
from bisheng.workflow.nodes.base import BaseNode

# A failure reason that carries this marker is followed by the JSON of an
# error code; RedisCallback.parse_workflow_failed reads it before any other
# substring rule, so texts from inside the subflow cannot be misread.
SUBFLOW_ERROR_MARKER = "-- subflow error --"
STOP_BY_USER = "stop by user"


class SubflowRunError(IgnoreException):
    """Failure of a subflow node that reaches the user with its own code."""

    def __init__(self, error_class: type[BaseErrorCode], **data: Any) -> None:
        error = error_class(**data)
        self.error = error
        super().__init__(f"{error.message} {SUBFLOW_ERROR_MARKER}{error.to_json_str(data=data)}")


def parse_subflow_error(reason: str | None) -> dict | None:
    """Return the ``{status_code, status_message, data}`` dict carried by a failure reason."""
    if not reason or SUBFLOW_ERROR_MARKER not in reason:
        return None
    try:
        return json.loads(reason.split(SUBFLOW_ERROR_MARKER, 1)[1])
    except ValueError:
        return None


def _clean_reason(reason: str) -> str:
    # An F078 skill error carries its own JSON after a marker; the user only
    # needs the text in front of it.
    if AGENT_SKILL_ERROR_MARKER in reason:
        return reason.split(AGENT_SKILL_ERROR_MARKER, 1)[0].strip()
    return reason


class SubflowNode(BaseNode):
    """F086: run another workflow's current version as one node.

    The child runs as its own engine inside ``_run``, silently, with the
    parent's run context. Its result is the merged return values of the End
    nodes it went through. See features/v3.0.0/086-nested-workflow/design.md.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        subflow = self.node_params.get("subflow_id") or {}
        self._subflow_id: str = subflow.get("id") or ""
        self._subflow_name: str = subflow.get("name") or ""
        self._inputs: list[dict] = self.node_params.get("subflow_inputs") or []
        # Return names that other nodes of this workflow reference; computed by the engine.
        self._referenced_outputs: list[str] = kwargs.get("referenced_outputs") or []

        self.sub_workflow = None
        self._sub_callback: SubflowCallback | None = None
        self._resolved_inputs: dict[str, Any] = {}

    def _run(self, unique_id: str):
        self.sub_workflow = None
        self._sub_callback = None
        self._resolved_inputs = {}

        if self.subflow_depth >= 1:
            # Only reachable inside a subflow; the parent node reports it as 10563.
            raise IgnoreException(f"{self.name} -- subflow node cannot run inside a subflow")

        flow = FlowDao.get_flow_by_id(self._subflow_id) if self._subflow_id else None
        if flow is None:
            raise SubflowRunError(WorkFlowSubflowNotFoundError)
        self._subflow_name = flow.name

        self._resolved_inputs = self._resolve_inputs()
        data = self._apply_inputs(copy.deepcopy(flow.data or {}))
        self._sub_callback = SubflowCallback(stop_check=self._stop_check(), on_stop=self.stop)
        self.sub_workflow = self._build_workflow(data, flow.user_id)
        self._copy_parent_context()

        status, reason = self.sub_workflow.run()
        if status == WorkflowStatus.FAILED.value and reason == STOP_BY_USER:
            raise IgnoreException(STOP_BY_USER)
        self._check_forbidden_nodes(status)
        if status != WorkflowStatus.SUCCESS.value:
            raise SubflowRunError(
                WorkFlowSubflowRunError,
                subflow_name=self._subflow_name,
                node_name=self._sub_callback.last_failed_node_name(),
                reason=_clean_reason(self._sub_callback.last_failed_reason() or reason or ""),
            )
        return self._collect_outputs()

    def _resolve_inputs(self) -> dict[str, Any]:
        ret = {}
        for one in self._inputs:
            if not one.get("key"):
                continue
            # A row left empty means "not configured": the child keeps its own value (R-1.3).
            if one.get("value") in (None, ""):
                continue
            if one.get("type") == "ref":
                ret[one["key"]] = self.get_other_node_variable(one.get("value"))
            else:
                # A typed-in value is text, whatever it looks like.
                value = one.get("value")
                ret[one["key"]] = "" if value is None else str(value)
        return ret

    def _apply_inputs(self, data: dict) -> dict:
        """Override the child's start node custom variables by name; unknown names are ignored."""
        for node in data.get("nodes") or []:
            node_data = (node or {}).get("data") or {}
            if node_data.get("type") != NodeType.START.value:
                continue
            for group in node_data.get("group_params") or []:
                for param in group.get("params") or []:
                    if param.get("key") != "custom_variables":
                        continue
                    for variable in param.get("value") or []:
                        if variable.get("label") in self._resolved_inputs:
                            variable["value"] = self._resolved_inputs[variable["label"]]
        return data

    def _stop_check(self):
        parent_check = getattr(self.callback_manager, "get_workflow_stop", None)
        if parent_check is None:
            return None
        return lambda: bool(parent_check())

    def _build_workflow(self, data: dict, child_owner_id: int | None):
        # Imported here: graph.workflow imports the node registry, which imports this module.
        from bisheng.workflow.graph.workflow import Workflow

        try:
            return Workflow(
                self.workflow_id,
                self.workflow_name,
                user_id=self.user_id,
                workflow_data=data,
                async_mode=False,
                max_steps=self.max_steps,
                callback=self._sub_callback,
                tenant_id=self.tenant_id,
                flow_user_id=child_owner_id,
                chat_id=self.chat_id,
                tmp_session_id=self.tmp_session_id,
                subflow_depth=self.subflow_depth + 1,
            )
        except IgnoreException as e:
            raise SubflowRunError(WorkFlowSubflowRunError, subflow_name=self._subflow_name, node_name="", reason=str(e))
        except Exception as e:
            raise SubflowRunError(
                WorkFlowSubflowRunError, subflow_name=self._subflow_name, node_name="", reason=str(e)
            ) from e

    def _copy_parent_context(self) -> None:
        """Give the child the parent's chat history and start time.

        Done after the child engine is built: its start node replaces the
        history memory and takes a fresh time when it is constructed.
        """
        engine = self.sub_workflow.graph_engine
        parent_memory = self.graph_state.history_memory
        if parent_memory is not None and engine.graph_state.history_memory is not None:
            engine.graph_state.history_memory.chat_memory.messages = list(parent_memory.chat_memory.messages)

        child_start = engine.nodes_map.get(engine.start_node_id)
        parent_time = self.graph_state.get_variable(self.start_node_id, "current_time") if self.start_node_id else None
        if child_start is not None and parent_time:
            child_start.node_params["current_time"] = parent_time

    def _check_forbidden_nodes(self, status: str) -> None:
        engine = self.sub_workflow.graph_engine
        for node_id in self._sub_callback.executed_node_ids:
            node = engine.nodes_map.get(node_id)
            if node is None:
                continue
            if node.type in (NodeType.INPUT.value, NodeType.SUBFLOW.value) or (
                node.type == NodeType.OUTPUT.value and is_interactive_output(node.node_params)
            ):
                self._raise_forbidden(node.name)

        if status == WorkflowStatus.INPUT.value:
            # Stopped before a node that waits for the user: an Input node or
            # the fake node behind an interactive Output node.
            snapshot = engine.graph.get_state(engine.graph_config)
            names = []
            for node_id in snapshot.next:
                node = engine.nodes_map.get(node_id)
                if node is None:
                    continue
                names.append(node.output_node.name if node.type == NodeType.FAKE_OUTPUT.value else node.name)
            self._raise_forbidden(names[0] if names else "")

    def _raise_forbidden(self, node_name: str) -> None:
        raise SubflowRunError(WorkFlowSubflowForbiddenNodeError, subflow_name=self._subflow_name, node_name=node_name)

    def _collect_outputs(self) -> dict[str, Any]:
        engine = self.sub_workflow.graph_engine
        ret = {}
        for node_id in self._sub_callback.executed_node_ids:
            node = engine.nodes_map.get(node_id)
            if node is not None and node.type == NodeType.END.value:
                ret.update(engine.graph_state.variables_pool.get(node_id) or {})
        for name in self._referenced_outputs:
            if name not in ret:
                raise SubflowRunError(
                    WorkFlowSubflowOutputMissingError, subflow_name=self._subflow_name, output_name=name
                )
        return ret

    def _subflow_logs(self) -> dict:
        logs = []
        if self._sub_callback is not None:
            nodes_map = self.sub_workflow.graph_engine.nodes_map if self.sub_workflow else {}
            for one in self._sub_callback.node_logs:
                node = nodes_map.get(one["node_id"])
                logs.append({**one, "type": node.type if node is not None else ""})
        return {"key": "subflow_logs", "type": "subflow_logs", "value": logs}

    def parse_log(self, unique_id: str, result: dict) -> Any:
        return [
            [
                {"key": "subflow_inputs", "value": self._resolved_inputs, "type": "params"},
                {"key": "subflow_outputs", "value": result, "type": "params"},
                self._subflow_logs(),
            ]
        ]

    def failed_reason(self, error: Exception) -> str:
        # The node log shows the message; the marker stays on the raised error
        # so the workflow failure keeps its code.
        if isinstance(error, SubflowRunError):
            return error.error.message
        return super().failed_reason(error)

    def parse_failed_log(self, unique_id: str) -> Any:
        return [
            [
                {"key": "subflow_inputs", "value": self._resolved_inputs, "type": "params"},
                self._subflow_logs(),
            ]
        ]

    def stop(self):
        super().stop()
        if self.sub_workflow is not None:
            self.sub_workflow.stop()
