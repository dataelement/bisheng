import time

from loguru import logger

from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowDao
from bisheng.memory.domain.ports import SCENE_WORKFLOW
from bisheng.memory.domain.services.activity import MemoryActivity
from bisheng.memory.domain.services.app_switch import workflow_memory_enabled_sync
from bisheng.memory.domain.services.gate import MemoryGate
from bisheng.open_api.domain.services.execution_context import restore_execution_context
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.public_endpoints.domain.services.guest_policy import should_skip_public_workflow_use
from bisheng.utils.exceptions import IgnoreException
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery
from bisheng.worker.utils.stateful_worker import StatefulWorker
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.workflow.common.workflow import WorkflowStatus
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


def _memory_chat_id(chat_id: str, source: str) -> str:
    """F132 AC-10: only platform (logged-in) runs may use memory; open-API runs never do,
    even when they reuse a chat_id that a logged-in connection registered."""
    return chat_id if source == "platform" else ""


def _online_memory_switch(workflow_id: str, chat_id: str) -> bool:
    """F132 R5: the workflow memory switch of the ONLINE version in the database.

    Read once per run at execution start, never from the graph the client sent.
    Runs without a session (evaluation, canvas debug, open API) skip the lookup.
    A lookup failure counts as off and never fails the run.
    """
    if not chat_id:
        return False
    try:
        return workflow_memory_enabled_sync(workflow_id)
    except Exception:
        logger.exception("memory switch lookup failed workflow_id={}", workflow_id)
        return False


def _end_memory_turn(chat_id: str, memory_enabled: bool | None, user_id: int | None = None) -> None:
    """F132: the task yields (waiting for input, success, failure, error) -> one turn ends.

    Enabled turns mark the session for consolidation; turns with memory off move
    the watermark past them. Unregistered sessions are a no-op. Best effort.
    """
    if not chat_id or memory_enabled is None:
        # memory_enabled None: the run object was lost, the switch is unknown; leave
        # the session as it is so earlier enabled turns are still consolidated.
        return
    try:
        ctx = MemoryGate.resolve_sync(chat_id, SCENE_WORKFLOW, app_enabled=memory_enabled, actor_user_id=user_id)
        MemoryActivity.end_turn_sync(chat_id, None, ctx is not None)
    except Exception:
        logger.exception("memory end_turn failed chat_id={}", chat_id)


def _execute_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: int, source: str = "platform"):
    # F022 INV-T18: resolve Flow.tenant_id once; reuse for both Workflow
    # node tenant threading and RedisCallback's sync workbench reads.
    workflow_info = FlowDao.get_flow_by_id(workflow_id)
    flow_tenant_id = getattr(workflow_info, "tenant_id", None)
    # F041: Flow creator (config author) — nodes filter knowledge-space retrieval
    # by this identity when the permission toggle is OFF (distinct from `user_id`,
    # the runtime user who triggered the run).
    flow_user_id = getattr(workflow_info, "user_id", None)
    redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id, source=source, tenant_id=flow_tenant_id)
    memory_chat_id = _memory_chat_id(chat_id, source)
    memory_enabled = _online_memory_switch(workflow_id, memory_chat_id)
    try:
        # update workflow status
        redis_callback.set_workflow_status(WorkflowStatus.RUNNING.value)
        # get workflow data
        workflow_data = redis_callback.get_workflow_data()
        if not workflow_data:
            raise Exception("workflow data not found maybe data is expired")

        # init workflow
        workflow_conf = settings.get_workflow_conf()
        workflow_name = workflow_info.name if workflow_info else workflow_id
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
            chat_id=chat_id or "",
            memory_enabled=memory_enabled,
        )
        redis_callback.workflow = workflow
        status, reason = workflow.run()
        _judge_workflow_status(redis_callback, workflow)
    except IgnoreException as e:
        logger.warning(f"execute_workflow ignore error: {e}")
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e))
        _clear_workflow_obj(redis_callback.unique_id)
    except Exception as e:
        logger.exception("execute_workflow error")
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e)[:100])
        _clear_workflow_obj(redis_callback.unique_id)
    finally:
        _end_memory_turn(memory_chat_id, memory_enabled, user_id)


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
):
    """Implementationworkflow"""
    trace_id_var.set(unique_id)
    start_time = time.time()
    try:
        with restore_execution_context(execution_snapshot) as snapshot:
            # Guest runs skip `use` only when session.flow_id matches this workflow.
            _authorize_workflow_use(snapshot, user_id, workflow_id, chat_id)
            _execute_workflow(unique_id, workflow_id, chat_id, user_id, source)
    finally:
        _log_workflow_telemetry(workflow_id, chat_id, user_id, start_time)


def _continue_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: int, source: str = "platform"):
    """Resumeworkflow"""
    redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id, source=source)
    memory_chat_id = _memory_chat_id(chat_id, source)
    memory_enabled = None
    try:
        workflow = _global_workflow.get(redis_callback.unique_id, None)
        if not workflow:
            raise Exception("workflow object not found maybe data is expired")
        # a resumed run keeps the switch read at its start (R5)
        memory_enabled = bool(getattr(workflow.graph_engine.graph_state, "memory_enabled", False))
        if workflow.status() not in [WorkflowStatus.INPUT.value, WorkflowStatus.INPUT_OVER.value]:
            raise Exception(f"workflow status is {workflow.status()} not INPUT")
        user_input = redis_callback.get_user_input()
        if not user_input:
            raise IgnoreException("workflow continue not found user input")
        redis_callback.set_workflow_status(WorkflowStatus.RUNNING.value)
        status, reason = workflow.run(user_input)
        _judge_workflow_status(redis_callback, workflow)
    except IgnoreException as e:
        logger.warning(f"continue_workflow ignore error: {e}")
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e))
        _clear_workflow_obj(redis_callback.unique_id)
    except Exception as e:
        logger.exception("continue_workflow error")
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e)[:100])
        _clear_workflow_obj(redis_callback.unique_id)
    finally:
        _end_memory_turn(memory_chat_id, memory_enabled, user_id)


@bisheng_celery.task
def continue_workflow(
    unique_id: str,
    workflow_id: str,
    chat_id: str,
    user_id: int,
    source: str = "platform",
    execution_snapshot: dict | None = None,
):
    """Resumeworkflow"""
    trace_id_var.set(unique_id)
    start_time = time.time()
    try:
        with restore_execution_context(execution_snapshot) as snapshot:
            _authorize_workflow_use(snapshot, user_id, workflow_id, chat_id)
            _continue_workflow(unique_id, workflow_id, chat_id, user_id, source)
    finally:
        _log_workflow_telemetry(workflow_id, chat_id, user_id, start_time)


@bisheng_celery.task
def stop_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: int):
    """Stopworkflow"""
    trace_id_var.set(unique_id)

    redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id)
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
