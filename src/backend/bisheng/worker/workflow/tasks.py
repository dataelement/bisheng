import time

from loguru import logger

from bisheng.settings import settings
from bisheng.worker.main import bisheng_celery
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.graph.workflow import Workflow


@bisheng_celery.task
def execute_workflow(unique_id: str, workflow_id: str, chat_id: str, user_id: str):
    """ 执行workflow """
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
        start_time = time.time()
        status, reason = workflow.run()
        # run workflow
        while True:
            logger.debug(f'workflow {unique_id} execute status: {workflow.status()}')
            if workflow.status() in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
                redis_callback.set_workflow_status(status, reason)
                break
            elif workflow.status() == WorkflowStatus.INPUT.value:
                redis_callback.set_workflow_status(status, reason)
                time.sleep(1)
                if time.time() - start_time > workflow.timeout * 60:
                    raise Exception('workflow wait user input timeout')
                if redis_callback.get_workflow_stop() == 1:
                    raise Exception('workflow stop by user')
                user_input = redis_callback.get_user_input()
                if not user_input:
                    continue
                redis_callback.set_workflow_status(WorkflowStatus.RUNNING.value)
                status, reason = workflow.run(user_input)
            else:
                raise Exception(f'unexpected workflow status error: {status}')
    except Exception as e:
        logger.exception('execute_workflow error')
        redis_callback.set_workflow_status(WorkflowStatus.FAILED.value, str(e)[:100])
