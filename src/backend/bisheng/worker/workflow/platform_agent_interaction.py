"""隔离 Mock 的平台 Agent 交互执行。"""

from loguru import logger

from bisheng.common.errcode.flow import PlatformAgentExecutionError
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.graph.kunlian_interaction import prepare_thread
from bisheng.workflow.graph.platform_agent_interaction import capture_agent_wait, restore_agent_wait


def start_interaction(workflow, context, callback, source) -> bool:
    """保存等待点时返回 True。图终态仍由既有 Worker 处理。"""
    execution = context["execution"]
    dispatch = context["dispatch"]
    service = context["service"]
    prepare_thread(workflow, dispatch.execution_id)
    engine = workflow.graph_engine
    engine.run()
    snapshot = capture_agent_wait(workflow, execution, source)
    node = engine.nodes_map[snapshot["agent_node"]]
    result = run_async_task(
        lambda: service.invoke_long_node(
            context["login_user"],
            execution["workflow_id"],
            dispatch,
            node.node_data.model_dump(),
            node.current_step,
            node.lookup,
            notify=callback.on_agent_long_task,
            wait_checkpoint=snapshot,
        )
    )
    if result is not None:
        context["interaction_result"] = result
        workflow.run({})
        return False

    callback.workflow = None
    try:
        callback.set_workflow_status(WorkflowStatus.INPUT.value)
        service.notify_long(dispatch.execution_id, f"{node.id}:{node.current_step}", callback.on_agent_long_task)
    except Exception as exc:
        logger.warning("平台 Agent 等待通知失败, error_type={}", type(exc).__name__)
    return True


def resume_interaction(workflow, context, callback):
    execution = context["execution"]
    dispatch = context["dispatch"]
    service = context["service"]
    key = execution["dispatches"][dispatch.dispatch_id]["call_key"]
    task = service.repository.long_snapshot(dispatch.execution_id, key)
    snapshot = task.get("interaction", {}).get("snapshot")
    restore_agent_wait(workflow, execution, snapshot)
    result = run_async_task(
        lambda: service.resume_long_interaction(context["login_user"], dispatch, key, callback.on_agent_long_task)
    )
    if result is None:
        raise PlatformAgentExecutionError()
    context["interaction_result"] = result
    workflow.run({})


def redeliver_interaction_resume(repository, resume_task, tenant_id, execution_id, key):
    dispatch = repository.claim_interaction_redelivery(execution_id, key, tenant_id)
    if dispatch is None:
        return
    interaction_id, dispatch_id = dispatch
    try:
        resume_task.apply_async(args=[execution_id, interaction_id, dispatch_id], headers={"tenant_id": tenant_id})
    except Exception as exc:
        logger.warning("平台 Agent 交互恢复派发待补投, error_type={}", type(exc).__name__)
