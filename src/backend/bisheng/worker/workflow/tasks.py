from loguru import logger

from bisheng.settings import settings
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


def _execute_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: str):
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
        workflow = Workflow(workflow_id, user_id, workflow_data, False,
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
def execute_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: str):
    """ 执行workflow """
    with logger.contextualize(trace_id=unique_id):
        _execute_workflow(unique_id, workflow_id, chat_id, user_id)


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
    with logger.contextualize(trace_id=unique_id):
        _continue_workflow(unique_id, workflow_id, chat_id, user_id)


@bisheng_celery.task
def stop_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: str):
    """ 停止workflow """
    with logger.contextualize(trace_id=unique_id):
        redis_callback = RedisCallback(unique_id, workflow_id, chat_id, user_id)
        if unique_id not in _global_workflow:
            logger.warning("stop_workflow called but workflow not found in global cache")
            return
        workflow = _global_workflow[unique_id]
        workflow.stop()
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, 'workflow stop by user')
        _clear_workflow_obj(unique_id)
        logger.info(f'workflow stop by user {user_id}')
