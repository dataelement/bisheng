"""固定线性图中的平台 Agent 等待点。"""

from bisheng.common.errcode.flow import PlatformAgentExecutionError
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest, interaction_node_ids
from bisheng.workflow.graph.kunlian_interaction import (
    capture_linear_wait,
    restore_linear_wait,
    validate_linear_wait,
    wait_engine_version,
)


def _binding(execution, agent_node, source=None):
    versions = [item.get("workflow_version_id") for item in execution["dispatches"].values() if item["kind"] == "START"]
    if len(versions) != 1 or type(versions[0]) is not int or versions[0] <= 0:
        raise PlatformAgentExecutionError()
    if canonical_digest(execution["graph_snapshot"]) != execution["graph_digest"]:
        raise PlatformAgentExecutionError()
    binding = {
        "format": 1,
        "engine": wait_engine_version(),
        "execution_id": execution["execution_id"],
        "workflow_version_id": versions[0],
        "graph_digest": execution["graph_digest"],
        "agent_node": agent_node,
    }
    if source is not None:
        if source not in ("platform", "api"):
            raise PlatformAgentExecutionError()
        binding["source"] = source
    return binding


def capture_agent_wait(workflow, execution, source=None):
    start, agent = interaction_node_ids(execution["graph_snapshot"])
    try:
        return capture_linear_wait(workflow, _binding(execution, agent, source), start, agent)
    except RunError:
        raise PlatformAgentExecutionError() from None


def restore_agent_wait(workflow, execution, snapshot):
    if not isinstance(snapshot, dict):
        raise PlatformAgentExecutionError()
    start, agent = interaction_node_ids(execution["graph_snapshot"])
    try:
        validate_linear_wait(snapshot, _binding(execution, agent, snapshot.get("source")), start, agent)
        restore_linear_wait(workflow, snapshot, execution["execution_id"], agent)
    except RunError:
        raise PlatformAgentExecutionError() from None
