import time

from loguru import logger

from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import (
    PlatformAgentExecutionError,
    PlatformKnowledgeExecutionError,
    knowledge_error_from_reason,
)
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowDao
from bisheng.open_api.domain.services.execution_context import restore_execution_context
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.public_endpoints.domain.services.guest_policy import should_skip_public_workflow_use
from bisheng.sso_sync.application.workflow_context import workflow_causal_scope
from bisheng.utils.exceptions import IgnoreException
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery
from bisheng.worker.utils.stateful_worker import StatefulWorker
from bisheng.worker.workflow.platform_agent_interaction import resume_interaction, start_interaction
from bisheng.worker.workflow.platform_agent_long_task_resume import resume_long_task, start_long_task_resume
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.workflow.application.platform_agent import (
    QueuedExecutionRejected,
    claim_queued_execution,
    public_execution_error,
    queue_tenant_scope,
)
from bisheng.workflow.application.platform_knowledge import claim_execution as claim_knowledge_execution
from bisheng.workflow.application.platform_knowledge import public_error as public_knowledge_error
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.domain.schemas.platform_agent import (
    interaction_node_ids,
    long_task_resume_node_ids,
    uses_agent_interaction,
    uses_platform_agent,
)
from bisheng.workflow.domain.schemas.platform_knowledge import uses_platform_knowledge
from bisheng.workflow.graph.workflow import Workflow

# workflow execute stateful worker for assigning tasks to bound workers
workflow_stateful_worker = StatefulWorker(queue_prefix="workflow_celery", bound_nodes_prefix="workflow_bound_nodes:")
# Stores global workflow objects
_global_workflow: dict[str, Workflow] = {}


def _clear_workflow_obj(unique_id: str):
    """Clear Global Workflow Objects"""
    if unique_id in _global_workflow:
        del _global_workflow[unique_id]
        logger.debug(f"clear workflow object for unique_id: {unique_id}")
    else:
        logger.warning(f"workflow object not found for unique_id: {unique_id}")


def _judge_workflow_status(redis_callback: RedisCallback, workflow: Workflow):
    status = workflow.status()
    reason = workflow.reason()
    context = getattr(getattr(workflow, "graph_engine", None), "platform_agent_context", None)
    if context:
        execution = context["service"].repository.get_execution(context["dispatch"].execution_id)
        if execution["actor_reference"].get("environment") != context["service"].repository.environment(
            context["service"].current_config
        ):
            from bisheng.common.errcode.flow import PlatformAgentEnvironmentError

            raise PlatformAgentEnvironmentError()
        target = (
            "WAITING"
            if status == WorkflowStatus.INPUT.value
            else "SUCCEEDED"
            if status == WorkflowStatus.SUCCESS.value
            else "FAILED"
        )
        context["service"].repository.finish_execution(context["dispatch"], target)
    run = getattr(getattr(workflow, "graph_engine", None), "platform_knowledge_context", None)
    if run:
        cache_key = f"{redis_callback.unique_id}:{run.execution_id}"
        if status == WorkflowStatus.INPUT.value:
            _global_workflow[cache_key] = workflow
            redis_callback.set_workflow_status(status)
        else:
            redis_callback.set_workflow_status(
                status if status == WorkflowStatus.SUCCESS.value else WorkflowStatus.FAILED.value,
                None if status == WorkflowStatus.SUCCESS.value else str(knowledge_error_from_reason(reason)),
            )
            _global_workflow.pop(cache_key, None)
        return
    if workflow.status() in [WorkflowStatus.SUCCESS.value, WorkflowStatus.FAILED.value]:
        redis_callback.set_workflow_status(status, reason)
        _clear_workflow_obj(redis_callback.unique_id)
        return
    if workflow.status() == WorkflowStatus.INPUT.value:
        # If it is an input state, place the object in memory
        _global_workflow[redis_callback.unique_id] = workflow
        # redis_callback.save_workflow_object(workflow)
        redis_callback.set_workflow_status(status, reason)
        return
    logger.error(f"unexpected workflow status error: {status}")
    redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, f"workflow run failed, unexpected status: {status}")
    _clear_workflow_obj(redis_callback.unique_id)


def _execute_workflow(
    unique_id: str,
    workflow_id: str,
    chat_id: str,
    user_id: int,
    source: str = "platform",
    platform_context=None,
    knowledge_run=None,
):
    # F022 INV-T18: resolve Flow.tenant_id once; reuse for both Workflow
    # node tenant threading and RedisCallback's sync workbench reads.
    workflow_info = FlowDao.get_flow_by_id(workflow_id)
    flow_tenant_id = getattr(workflow_info, "tenant_id", None)
    # F041: Flow creator (config author) — nodes filter knowledge-space retrieval
    # by this identity when the permission toggle is OFF (distinct from `user_id`,
    # the runtime user who triggered the run).
    flow_user_id = getattr(workflow_info, "user_id", None)
    redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id, source=source, tenant_id=flow_tenant_id)
    if knowledge_run:
        redis_callback.bind_platform_knowledge_execution(knowledge_run.execution_id, knowledge_run.owner)
    elif isinstance(getattr(redis_callback, "get_platform_knowledge_reference", lambda: None)(), str):
        return
    try:
        workflow_data = (
            platform_context["execution"]["graph_snapshot"] if platform_context else redis_callback.get_workflow_data()
        )
        if knowledge_run:
            frozen = knowledge_run.record["graph"]
            if platform_context:
                repository = platform_context["service"].repository
                if repository.candidate_graph(workflow_data) != repository.candidate_graph(frozen):
                    raise PlatformKnowledgeExecutionError()
            workflow_data = frozen
        if uses_platform_knowledge(workflow_data) and knowledge_run is None:
            raise PlatformKnowledgeExecutionError()
        if uses_platform_agent(workflow_data) and platform_context is None:
            if knowledge_run:
                raise PlatformKnowledgeExecutionError()
            logger.warning("ignored workflow message without platform Agent execution reference")
            return
        if platform_context:
            redis_callback.bind_platform_agent_execution(platform_context["dispatch"].execution_id)
        # update workflow status
        redis_callback.set_workflow_status(WorkflowStatus.RUNNING.value)
        # get workflow data
        if not workflow_data:
            raise Exception("workflow data not found maybe data is expired")

        # init workflow
        workflow_conf = settings.get_workflow_conf()
        workflow_name = workflow_info.name if workflow_info else workflow_id
        interaction = platform_context is not None and uses_agent_interaction(workflow_data)
        entry = platform_context["execution"]["dispatches"][platform_context["dispatch"].dispatch_id] if platform_context else {}
        long_task_resume = entry.get("long_task_resume") is True
        if interaction or long_task_resume:
            if not chat_id:
                raise PlatformAgentExecutionError()
            node_ids = long_task_resume_node_ids if long_task_resume else interaction_node_ids
            # 图引擎的既有静态中断位置也用于普通长任务。
            _, platform_context["interaction_node"] = node_ids(workflow_data)
        workflow = Workflow(
            workflow_id,
            workflow_name,
            user_id,
            workflow_data,
            False,
            workflow_conf.max_steps,
            workflow_conf.timeout,
            redis_callback,
            tenant_id=flow_tenant_id,
            flow_user_id=flow_user_id,
            platform_agent_context=platform_context,
            platform_knowledge_context=knowledge_run,
        )
        redis_callback.workflow = workflow
        if long_task_resume:
            start_long_task_resume(workflow, platform_context, redis_callback, source)
            return
        if interaction:
            if entry["kind"] == "INTERACTION_RESUME":
                resume_interaction(workflow, platform_context, redis_callback)
            elif start_interaction(workflow, platform_context, redis_callback, source):
                return
        else:
            workflow.run()
        _judge_workflow_status(redis_callback, workflow)
    except IgnoreException as e:
        if platform_context or knowledge_run:
            raise
        logger.warning(f"execute_workflow ignore error: {e}")
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e))
        _clear_workflow_obj(redis_callback.unique_id)
    except Exception as e:
        if platform_context or knowledge_run:
            raise
        logger.exception("execute_workflow error")
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e)[:100])
        _clear_workflow_obj(redis_callback.unique_id)


def _authorize_workflow_use(snapshot, user_id: int, workflow_id: str, chat_id: str) -> None:
    if snapshot is None:
        return
    if should_skip_public_workflow_use(
        channel=getattr(snapshot, "channel", None),
        chat_id=chat_id,
        workflow_id=workflow_id,
    ):
        return
    run_async_task(
        lambda: require_business_action(
            UserPayload(user_id=user_id, user_role=[], tenant_id=snapshot.tenant_id),
            resource_type="workflow",
            resource_id=workflow_id,
            action="use",
            actor=get_current_permission_actor(),
        )
    )


def _fail_platform_execution(context, unique_id, workflow_id, chat_id, user_id, source, error):
    reason = public_execution_error(error)
    dispatch = context["dispatch"]
    # 仅记录安全领域错误。驱动、构造器和身份服务的原始异常不进入日志及 Redis。
    logger.opt(exception=(type(reason), reason, None)).error(
        "platform Agent workflow failed: execution_id={}", dispatch.execution_id
    )
    if context["service"].repository.fail_execution(dispatch):
        callback = RedisCallback(unique_id, workflow_id, chat_id, user_id, source=source)
        callback.bind_platform_agent_execution(dispatch.execution_id)
        callback.set_workflow_status(WorkflowStatus.FAILED.value, reason.Msg)
        existing = _global_workflow.get(unique_id)
        existing_context = getattr(getattr(existing, "graph_engine", None), "platform_agent_context", None)
        if existing_context and existing_context["dispatch"] == dispatch:
            _clear_workflow_obj(unique_id)
    raise reason from None


def _run_platform_workflow(
    reference, runner, unique_id, workflow_id, chat_id, user_id, source, snapshot, kind, knowledge_run=None
):
    context = None
    try:
        context = run_async_task(
            lambda: claim_queued_execution(
                reference, workflow_id, unique_id, user_id, execution_snapshot=snapshot, dispatch_kind=kind
            )
        )
        if context is not None:
            if knowledge_run:
                runner(unique_id, workflow_id, chat_id, user_id, source, context, knowledge_run)
            else:
                runner(unique_id, workflow_id, chat_id, user_id, source, context)
        elif knowledge_run:
            raise PlatformKnowledgeExecutionError()
    except QueuedExecutionRejected as error:
        _fail_platform_execution(error.context, unique_id, workflow_id, chat_id, user_id, source, error.reason)
        if knowledge_run:
            raise PlatformKnowledgeExecutionError() from None
    except Exception as error:
        if context is not None:
            _fail_platform_execution(context, unique_id, workflow_id, chat_id, user_id, source, error)
        raise


def _run_knowledge_workflow(
    reference, agent_reference, runner, unique_id, workflow_id, chat_id, user_id, source, snapshot, kind
):
    if snapshot is not None:
        from bisheng.workflow.application.platform_knowledge import actual_user_from_snapshot

        login_user = actual_user_from_snapshot(snapshot, user_id)
        if login_user.tenant_id != get_current_tenant_id():
            raise PlatformKnowledgeExecutionError()
    else:
        login_user = UserPayload(user_id=user_id, tenant_id=get_current_tenant_id(), user_role=[])
    run = claim_knowledge_execution(login_user, workflow_id, unique_id, reference, resume=kind == "RESUME")
    if run is None:
        return
    try:
        run_async_task(run.authorize)
        if agent_reference is not None:
            _run_platform_workflow(
                agent_reference,
                runner,
                unique_id,
                workflow_id,
                chat_id,
                user_id,
                source,
                snapshot,
                kind,
                run,
            )
        else:
            runner(unique_id, workflow_id, chat_id, user_id, source, knowledge_run=run)
    except Exception as error:
        run.store.status(run.execution_id, run.owner, WorkflowStatus.FAILED.value, str(public_knowledge_error(error)))
        _global_workflow.pop(f"{unique_id}:{run.execution_id}", None)
        logger.warning("昆联检索运行失败 execution_id={} error={}", run.execution_id, type(error).__name__)


def _log_workflow_telemetry(workflow_id: str, chat_id: str, user_id: int, start_time: float):
    """Record best-effort workflow telemetry without changing task outcome."""
    try:
        end_time = time.time()
        workflow_info = WorkFlowService.get_one_workflow_simple_info_sync(workflow_id)
        telemetry_service.log_event_sync(
            user_id=user_id,
            event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
            trace_id=trace_id_var.get(),
            event_data=ApplicationProcessEventData(
                app_id=workflow_id,
                app_name=workflow_info.name if workflow_info else workflow_id,
                app_type=ApplicationTypeEnum.WORKFLOW,
                chat_id=chat_id,
                start_time=int(start_time),
                end_time=int(end_time),
                process_time=int((end_time - start_time) * 1000),
            ),
        )
    except Exception:
        # Telemetry is opportunistic and must not reverse the workflow task outcome.
        logger.exception("failed to record workflow telemetry for workflow_id={}", workflow_id)


@bisheng_celery.task
def execute_workflow(
    unique_id: str,
    workflow_id: str,
    chat_id: str,
    user_id: int,
    source: str = "platform",
    execution_snapshot: dict | None = None,
    platform_agent_execution: dict | None = None,
    platform_knowledge_execution: dict | None = None,
):
    """Implementationworkflow"""
    trace_id_var.set(unique_id)
    start_time = time.time()
    try:
        with (
            queue_tenant_scope(
                getattr(getattr(execute_workflow, "request", None), "headers", None),
                platform_agent_execution or platform_knowledge_execution,
            ),
            workflow_causal_scope(
                getattr(getattr(execute_workflow, "request", None), "headers", None),
                user_id=user_id,
                execution_snapshot=execution_snapshot,
            ),
            restore_execution_context(execution_snapshot) as snapshot,
        ):
            if platform_knowledge_execution is not None:
                _run_knowledge_workflow(
                    platform_knowledge_execution,
                    platform_agent_execution,
                    _execute_workflow,
                    unique_id,
                    workflow_id,
                    chat_id,
                    user_id,
                    source,
                    snapshot,
                    "START",
                )
                return
            if platform_agent_execution is not None:
                _run_platform_workflow(
                    platform_agent_execution,
                    _execute_workflow,
                    unique_id,
                    workflow_id,
                    chat_id,
                    user_id,
                    source,
                    snapshot,
                    "START",
                )
                return
            else:
                # 普通流程保留原有公开入口授权。平台流程在领取后复核当前资格。
                _authorize_workflow_use(snapshot, user_id, workflow_id, chat_id)
                _execute_workflow(unique_id, workflow_id, chat_id, user_id, source)
    finally:
        _log_workflow_telemetry(workflow_id, chat_id, user_id, start_time)


def _continue_workflow(
    unique_id: str,
    workflow_id: str,
    chat_id: str,
    user_id: int,
    source: str = "platform",
    platform_context=None,
    knowledge_run=None,
):
    """Resumeworkflow"""
    redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id, source=source)
    if knowledge_run:
        redis_callback.bind_platform_knowledge_execution(knowledge_run.execution_id, knowledge_run.owner)
    elif isinstance(getattr(redis_callback, "get_platform_knowledge_reference", lambda: None)(), str):
        return
    try:
        if platform_context:
            redis_callback.bind_platform_agent_execution(platform_context["dispatch"].execution_id)
        workflow = _global_workflow.get(
            f"{unique_id}:{knowledge_run.execution_id}" if knowledge_run else redis_callback.unique_id
        )
        if not workflow:
            raise Exception("workflow object not found maybe data is expired")
        existing_knowledge = getattr(workflow.graph_engine, "platform_knowledge_context", None)
        if bool(existing_knowledge) != bool(knowledge_run) or (
            existing_knowledge and existing_knowledge.execution_id != knowledge_run.execution_id
        ):
            if knowledge_run:
                raise PlatformKnowledgeExecutionError()
            return
        if knowledge_run:
            workflow.set_platform_knowledge_context(knowledge_run)
            # 恢复后的回调也必须使用新领取的 owner。
            workflow.graph_engine.callback.bind_platform_knowledge_execution(
                knowledge_run.execution_id, knowledge_run.owner
            )
        existing = getattr(workflow.graph_engine, "platform_agent_context", None)
        if bool(existing) != bool(platform_context) or (
            existing and existing["dispatch"].execution_id != platform_context["dispatch"].execution_id
        ):
            if platform_context:
                from bisheng.common.errcode.flow import PlatformAgentExecutionError

                raise PlatformAgentExecutionError()
            logger.warning("ignored workflow resume with mismatched platform Agent execution")
            return
        if platform_context:
            workflow.set_platform_agent_context(platform_context)
            redis_callback.bind_platform_agent_execution(platform_context["dispatch"].execution_id)
        if workflow.status() not in [WorkflowStatus.INPUT.value, WorkflowStatus.INPUT_OVER.value]:
            raise Exception(f"workflow status is {workflow.status()} not INPUT")
        user_input = redis_callback.get_user_input()
        if not user_input:
            raise IgnoreException("workflow continue not found user input")
        redis_callback.set_workflow_status(WorkflowStatus.RUNNING.value)
        workflow.run(user_input)
        _judge_workflow_status(redis_callback, workflow)
    except IgnoreException as e:
        if platform_context or knowledge_run:
            raise
        logger.warning(f"continue_workflow ignore error: {e}")
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e))
        _clear_workflow_obj(redis_callback.unique_id)
    except Exception as e:
        if platform_context or knowledge_run:
            raise
        logger.exception("continue_workflow error")
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e)[:100])
        _clear_workflow_obj(redis_callback.unique_id)


@bisheng_celery.task
def continue_workflow(
    unique_id: str,
    workflow_id: str,
    chat_id: str,
    user_id: int,
    source: str = "platform",
    execution_snapshot: dict | None = None,
    platform_agent_execution: dict | None = None,
    platform_knowledge_execution: dict | None = None,
):
    """Resumeworkflow"""
    trace_id_var.set(unique_id)
    start_time = time.time()
    try:
        with (
            queue_tenant_scope(
                getattr(getattr(continue_workflow, "request", None), "headers", None),
                platform_agent_execution or platform_knowledge_execution,
            ),
            workflow_causal_scope(
                getattr(getattr(continue_workflow, "request", None), "headers", None),
                user_id=user_id,
                execution_snapshot=execution_snapshot,
            ),
            restore_execution_context(execution_snapshot) as snapshot,
        ):
            if platform_knowledge_execution is not None:
                _run_knowledge_workflow(
                    platform_knowledge_execution,
                    platform_agent_execution,
                    _continue_workflow,
                    unique_id,
                    workflow_id,
                    chat_id,
                    user_id,
                    source,
                    snapshot,
                    "RESUME",
                )
                return
            if platform_agent_execution is not None:
                _run_platform_workflow(
                    platform_agent_execution,
                    _continue_workflow,
                    unique_id,
                    workflow_id,
                    chat_id,
                    user_id,
                    source,
                    snapshot,
                    "RESUME",
                )
                return
            else:
                _authorize_workflow_use(snapshot, user_id, workflow_id, chat_id)
                _continue_workflow(unique_id, workflow_id, chat_id, user_id, source)
    finally:
        _log_workflow_telemetry(workflow_id, chat_id, user_id, start_time)


def register_interaction_resume(celery_app):
    """由隔离环境显式注册交互恢复任务。"""
    from bisheng.workflow.application.platform_agent import get_service

    @celery_app.task(name="kunlian.platform_agent_interaction_resume", shared=False)
    def resume(execution_id, interaction_id, dispatch_id):
        service = get_service()
        if service.config.mode != "mock" or not (service.enable_interactions and service.enable_long_tasks):
            return
        reference = {"execution_id": execution_id, "dispatch_id": dispatch_id}
        headers = getattr(getattr(resume, "request", None), "headers", None)
        with queue_tenant_scope(headers, reference):
            execution = service.repository.get_execution(execution_id)
            entry = execution["dispatches"].get(dispatch_id, {})
            if (
                execution["tenant_id"] != get_current_tenant_id()
                or execution["entry_kind"] != "PUBLISHED"
                or entry.get("kind") != "INTERACTION_RESUME"
                or entry.get("interaction_id") != interaction_id
            ):
                raise PlatformAgentExecutionError()
            session = execution["session_id"]
            suffix = "_async_task_id"
            chat_id = session.removesuffix(suffix)
            if not chat_id or chat_id == session:
                raise PlatformAgentExecutionError()
            snapshot = execution["calls"][entry["call_key"]]["long_task"]["interaction"].get("snapshot")
            source = snapshot.get("source") if isinstance(snapshot, dict) else None
            _run_platform_workflow(
                reference, _execute_workflow, session, execution["workflow_id"], chat_id, execution["user_id"],
                "api" if source == "api" else "platform", None, "INTERACTION_RESUME",
            )

    return resume


def register_long_task_resume(celery_app):
    """隔离 Worker 显式注册普通长任务恢复。"""

    @celery_app.task(name="kunlian.platform_agent_long_task_resume", shared=False)
    def resume(execution_id, call_key, dispatch_id):
        headers = getattr(getattr(resume, "request", None), "headers", None)
        with queue_tenant_scope(headers, {"execution_id": execution_id}):
            resume_long_task(execution_id, call_key, dispatch_id)

    return resume


@bisheng_celery.task
def stop_workflow(
    unique_id: str,
    workflow_id: str,
    chat_id: str,
    user_id: int,
    platform_agent_execution_id=None,
    platform_knowledge_execution_id=None,
):
    with queue_tenant_scope(
        getattr(getattr(stop_workflow, "request", None), "headers", None),
        platform_agent_execution_id or platform_knowledge_execution_id,
    ):
        if platform_knowledge_execution_id:
            callback = RedisCallback(unique_id, workflow_id, chat_id, user_id)
            if callback.get_platform_knowledge_reference() != platform_knowledge_execution_id:
                return
            callback.knowledge_store.stop(platform_knowledge_execution_id)
            workflow = _global_workflow.pop(f"{unique_id}:{platform_knowledge_execution_id}", None)
            run = getattr(getattr(workflow, "graph_engine", None), "platform_knowledge_context", None)
            if run and run.execution_id == platform_knowledge_execution_id:
                workflow.stop()
            return
        return _stop_workflow(unique_id, workflow_id, chat_id, user_id, platform_agent_execution_id)


def _stop_workflow(unique_id, workflow_id, chat_id, user_id, platform_agent_execution_id):
    """Stopworkflow"""
    trace_id_var.set(unique_id)

    redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id)
    reference = redis_callback.get_platform_agent_reference()
    if reference != platform_agent_execution_id:
        return
    redis_callback.platform_agent_execution_id = platform_agent_execution_id
    existing = _global_workflow.get(unique_id)
    context = getattr(getattr(existing, "graph_engine", None), "platform_agent_context", None)
    if context and context["dispatch"].execution_id != platform_agent_execution_id:
        return
    if unique_id not in _global_workflow:
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, "workflow stop by user")
        logger.warning("stop_workflow called but workflow not found in global cache")
        return
    workflow = _global_workflow[unique_id]
    workflow.stop()

    while workflow.status() == WorkflowStatus.RUNNING.value:
        time.sleep(0.3)
    status, reason = workflow.status(), workflow.reason()
    if status != WorkflowStatus.FAILED.value:
        status = WorkflowStatus.FAILED.value
        reason = "workflow stop by user"
        redis_callback.set_workflow_status(status, reason)
    _clear_workflow_obj(unique_id)
    logger.info(f"workflow stop by user {user_id}")
