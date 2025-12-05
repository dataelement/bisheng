import time

from loguru import logger

from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowDao
from bisheng.utils.exceptions import IgnoreException
from bisheng.worker.main import bisheng_celery
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.graph.workflow import Workflow

# 存储全局的工作流对象
_global_workflow: dict[str, Workflow] = {}


def _clear_workflow_obj(unique_id: str):
    """ 清除全局工作流对象 """
    if unique_id in _global_workflow:
        del _global_workflow[unique_id]
        logger.debug(f'clear workflow object for unique_id: {unique_id}')
    else:
        logger.warning(f'workflow object not found for unique_id: {unique_id}')


def _judge_workflow_status(redis_callback: RedisCallback, workflow: Workflow):
    status = workflow.status()
    reason = workflow.reason()
    if workflow.status() in [WorkflowStatus.SUCCESS.value, WorkflowStatus.FAILED.value]:
        redis_callback.set_workflow_status(status, reason)
        _clear_workflow_obj(redis_callback.unique_id)
        return
    if workflow.status() == WorkflowStatus.INPUT.value:
        # 如果是输入状态，将对象放到内存中
        _global_workflow[redis_callback.unique_id] = workflow
        # redis_callback.save_workflow_object(workflow)
        redis_callback.set_workflow_status(status, reason)
        return
    logger.error(f'unexpected workflow status error: {status}')
    redis_callback.set_workflow_status(WorkflowStatus.FAILED.value,
                                       f'workflow run failed, unexpected status: {status}')
    _clear_workflow_obj(redis_callback.unique_id)


def _execute_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: int):
    redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id)
    try:
        # update workflow status
        redis_callback.set_workflow_status(WorkflowStatus.RUNNING.value)
        # get workflow data
        workflow_data = redis_callback.get_workflow_data()
        if not workflow_data:
            raise Exception('workflow data not found maybe data is expired')

        # init workflow
        workflow_conf = settings.get_workflow_conf()
        workflow_info = FlowDao.get_flow_by_id(workflow_id)
        workflow_name = workflow_info.name if workflow_info else workflow_id
        workflow = Workflow(workflow_id, workflow_name,
                            user_id, workflow_data, False,
                            workflow_conf.max_steps,
                            workflow_conf.timeout,
                            redis_callback)
        redis_callback.workflow = workflow
        status, reason = workflow.run()
        _judge_workflow_status(redis_callback, workflow)
    except IgnoreException as e:
        logger.warning(f'execute_workflow ignore error: {e}')
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e))
        _clear_workflow_obj(redis_callback.unique_id)
    except Exception as e:
        logger.exception('execute_workflow error')
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e)[:100])
        _clear_workflow_obj(redis_callback.unique_id)


@bisheng_celery.task
def execute_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: int):
    """ 执行workflow """
    trace_id_var.set(unique_id)
    start_time = time.time()
    try:
        _execute_workflow(unique_id, workflow_id, chat_id, user_id)
    finally:
        end_time = time.time()
        workflow_info = WorkFlowService.get_one_workflow_simple_info_sync(workflow_id)
        telemetry_service.log_event_sync(user_id=user_id,
                                         event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
                                         trace_id=trace_id_var.get(),
                                         event_data=ApplicationProcessEventData(
                                             app_id=workflow_id,
                                             app_name=workflow_info.name if workflow_info else workflow_id,
                                             app_type=ApplicationTypeEnum.WORKFLOW,
                                             chat_id=chat_id,

                                             start_time=int(start_time),
                                             end_time=int(end_time),
                                             process_time=int((end_time - start_time) * 1000)
                                         ))


def _continue_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: str):
    """ 继续执行workflow """
    redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id)
    try:
        workflow = _global_workflow.get(redis_callback.unique_id, None)
        if not workflow:
            raise Exception('workflow object not found maybe data is expired')
        if workflow.status() not in [WorkflowStatus.INPUT.value, WorkflowStatus.INPUT_OVER.value]:
            raise Exception(f'workflow status is {workflow.status()} not INPUT')
        user_input = redis_callback.get_user_input()
        if not user_input:
            raise IgnoreException('workflow continue not found user input')
        redis_callback.set_workflow_status(WorkflowStatus.RUNNING.value)
        status, reason = workflow.run(user_input)
        _judge_workflow_status(redis_callback, workflow)
    except IgnoreException as e:
        logger.warning(f'continue_workflow ignore error: {e}')
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e))
        _clear_workflow_obj(redis_callback.unique_id)
    except Exception as e:
        logger.exception('continue_workflow error')
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e)[:100])
        _clear_workflow_obj(redis_callback.unique_id)


@bisheng_celery.task
def continue_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: str):
    """ 继续执行workflow """
    trace_id_var.set(unique_id)
    start_time = time.time()
    try:
        _continue_workflow(unique_id, workflow_id, chat_id, user_id)
    finally:
        end_time = time.time()
        workflow_info = WorkFlowService.get_one_workflow_simple_info_sync(workflow_id)
        telemetry_service.log_event_sync(user_id=user_id,
                                         event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
                                         trace_id=trace_id_var.get(),
                                         event_data=ApplicationProcessEventData(
                                             app_id=workflow_id,
                                             app_name=workflow_info.name if workflow_info else workflow_id,
                                             app_type=ApplicationTypeEnum.WORKFLOW,
                                             chat_id=chat_id,

                                             start_time=int(start_time),
                                             end_time=int(end_time),
                                             process_time=int((end_time - start_time) * 1000)
                                         ))


@bisheng_celery.task
def stop_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: int):
    """ 停止workflow """
    trace_id_var.set(unique_id)

    redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id)
    if unique_id not in _global_workflow:
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, 'workflow stop by user')
        logger.warning("stop_workflow called but workflow not found in global cache")
        return
    workflow = _global_workflow[unique_id]
    workflow.stop()

    while workflow.status() == WorkflowStatus.RUNNING.value:
        time.sleep(0.3)
    status, reason = workflow.status(), workflow.reason()
    if status != WorkflowStatus.FAILED.value:
        status = WorkflowStatus.FAILED.value
        reason = 'workflow stop by user'
    redis_callback.set_workflow_status(status, reason)
    _clear_workflow_obj(unique_id)
    logger.info(f'workflow stop by user {user_id}')
