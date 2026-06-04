# register tasks
from bisheng.worker.approval.tasks import execute_approval_outbox, retry_approval_outbox
from bisheng.worker.information.article import sync_information_article
from bisheng.worker.information.reconcile import reconcile_all_tenants
from bisheng.worker.knowledge.file_worker import (
    file_copy_celery,
    parse_knowledge_file_celery,
    retry_knowledge_file_celery,
)
from bisheng.worker.knowledge.qa import copy_qa_knowledge_celery, insert_qa_celery, rebuild_qa_knowledge_celery
from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery, rebuild_knowledge_file_chunk
from bisheng.worker.knowledge.scheduler import (
    reconcile_file_scheduler_task,
    trigger_dispatch_task,
)
from bisheng.worker.permission.retry_failed_tuples import retry_failed_tuples
from bisheng.worker.telemetry.mid_table import (
    sync_mid_app_increment,
    sync_mid_knowledge_increment,
    sync_mid_user_increment,
    sync_mid_user_interact_dtl,
)
from bisheng.worker.test.test import add
from bisheng.worker.workflow.tasks import continue_workflow, execute_workflow, stop_workflow
