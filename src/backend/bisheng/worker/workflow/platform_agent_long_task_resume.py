"""隔离 Mock 的普通异步 Agent 启动、挂起及恢复。"""

from loguru import logger

from bisheng.common.errcode.flow import PlatformAgentError, PlatformAgentExecutionError, PlatformAgentPermissionError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.errcode.tenant_resolver import TokenVersionMismatchError
from bisheng.common.services.config_service import settings
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.workflow.redis_callback import LongTaskResumeOutput, RedisCallback
from bisheng.workflow.application.platform_agent import (
    claim_long_task_resume,
    commit_long_task_resume_output,
)
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.domain.schemas.platform_agent import long_task_resume_node_ids
from bisheng.workflow.graph.kunlian_interaction import prepare_thread
from bisheng.workflow.graph.platform_agent_long_task_resume import capture_long_task_wait, restore_long_task_wait
from bisheng.workflow.graph.workflow import Workflow


def start_long_task_resume(workflow, context, callback, source):
    execution = context["execution"]
    dispatch = context["dispatch"]
    service = context["service"]
    prepare_thread(workflow, dispatch.execution_id)
    engine = workflow.graph_engine
    engine.run()
    snapshot = capture_long_task_wait(workflow, execution, dispatch.dispatch_id, source)
    node = engine.nodes_map[snapshot["agent_node"]]
    run_async_task(
        lambda: service.invoke_long_node(
            context["login_user"],
            execution["workflow_id"],
            dispatch,
            node.node_data.model_dump(),
            node.current_step,
            node.lookup,
            resume_checkpoint=snapshot,
        )
    )
    callback.workflow = None
    key = f"{node.id}:{node.current_step}"
    service.notify_long(dispatch.execution_id, key, callback.on_agent_long_task)
    service.wake_long(execution["tenant_id"], dispatch.execution_id, key)


def resume_long_task(execution_id, key, dispatch_id):
    context = run_async_task(lambda: claim_long_task_resume(execution_id, key, dispatch_id))
    if context is None:
        return
    execution = context["execution"]
    dispatch = context["dispatch"]
    repository = context["service"].repository
    material = execution["calls"][key]["long_task"]["resume"]
    snapshot = material.get("snapshot")
    output = LongTaskResumeOutput()
    try:
        graph = execution["graph_snapshot"]
        _, context["interaction_node"] = long_task_resume_node_ids(graph)
        context["long_task_resume_result"] = material["result"]
        config = settings.get_workflow_conf()
        workflow = Workflow(
            execution["workflow_id"],
            user_id=execution["user_id"],
            workflow_data=graph,
            max_steps=config.max_steps,
            timeout=config.timeout,
            callback=output,
            tenant_id=execution["tenant_id"],
            platform_agent_context=context,
            redact_errors=True,
        )
        restore_long_task_wait(workflow, execution, snapshot)
        status, _ = workflow.run({})
        if status != WorkflowStatus.SUCCESS.value or output.message is None:
            raise PlatformAgentExecutionError()
    except (PlatformAgentError, KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "平台 Agent 恢复材料或图执行失败 execution_id={} error_type={}", execution_id, type(exc).__name__
        )
        repository.fail_long_task_resume(dispatch, key, "RESUME_STATE_INVALID")
        return
    except Exception as exc:
        logger.warning("平台 Agent 恢复暂时失败 execution_id={} error_type={}", execution_id, type(exc).__name__)
        raise PlatformAgentExecutionError() from None

    try:
        message_id = run_async_task(lambda: commit_long_task_resume_output(context, output.message))
    except (UnAuthorizedError, PlatformAgentPermissionError, PermissionDeniedError, TokenVersionMismatchError):
        repository.fail_long_task_resume(dispatch, key, "FORBIDDEN")
        return
    # 事务已提交。通知失败时授权方仍可按持久消息回执补读。
    try:
        session_id = execution["session_id"]
        callback = RedisCallback(
            session_id,
            execution["workflow_id"],
            session_id.removesuffix("_async_task_id"),
            execution["user_id"],
            source=snapshot["source"],
            tenant_id=execution["tenant_id"],
        )
        callback.bind_platform_agent_execution(execution_id)
        callback.publish_long_task_resume_output(message_id, output.message)
        callback.set_workflow_status(WorkflowStatus.SUCCESS.value)
    except Exception as exc:
        logger.warning("平台 Agent 恢复输出待补读 execution_id={} error_type={}", execution_id, type(exc).__name__)
