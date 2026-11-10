"""普通异步 Agent 的持久等待点。"""

from bisheng.common.errcode.flow import PlatformAgentExecutionError
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest, long_task_resume_node_ids
from bisheng.workflow.graph.kunlian_interaction import (
    capture_linear_wait,
    restore_linear_wait,
    validate_linear_wait,
    wait_engine_version,
)


def _wait_binding(execution, dispatch, source):
    graph = execution["graph_snapshot"]
    start, agent = long_task_resume_node_ids(graph)
    version = dispatch.get("workflow_version_id")
    if (
        dispatch.get("long_task_resume") is not True
        or type(version) is not int
        or version <= 0
        or canonical_digest(graph) != execution["graph_digest"]
        or source not in {"platform", "api"}
    ):
        raise PlatformAgentExecutionError()
    return (
        start,
        agent,
        {
            "format": 1,
            "engine": wait_engine_version(),
            "execution_id": execution["execution_id"],
            "workflow_version_id": version,
            "graph_digest": execution["graph_digest"],
            "agent_node": agent,
            "source": source,
        },
    )


def capture_long_task_wait(workflow, execution, dispatch_id, source):
    try:
        start, agent, binding = _wait_binding(execution, execution["dispatches"][dispatch_id], source)
        return capture_linear_wait(workflow, binding, start, agent)
    except RunError:
        raise PlatformAgentExecutionError() from None


def restore_long_task_wait(workflow, execution, snapshot):
    starts = [item for item in execution["dispatches"].values() if item["kind"] == "START"]
    if len(starts) != 1 or not isinstance(snapshot, dict):
        raise PlatformAgentExecutionError()
    try:
        start, agent, binding = _wait_binding(execution, starts[0], snapshot.get("source"))
        validate_linear_wait(snapshot, binding, start, agent)
        restore_linear_wait(workflow, snapshot, execution["execution_id"], agent)
    except (RunError, KeyError, TypeError, ValueError):
        raise PlatformAgentExecutionError() from None
