# register tasks
from bisheng.worker.knowledge.file_worker import file_copy_celery, parse_knowledge_file_celery, \
    retry_knowledge_file_celery
from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery
from bisheng.worker.telemetry.mid_table import sync_mid_user_increment, sync_mid_knowledge_increment, \
    sync_mid_app_increment, sync_mid_user_interact_dtl
from bisheng.worker.test.test import add
from bisheng.worker.workflow.tasks import execute_workflow, continue_workflow, stop_workflow
