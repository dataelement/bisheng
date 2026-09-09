# register tasks
from bisheng.worker.admin_scope.tasks import admin_scope_cleanup
from bisheng.worker.approval.tasks import execute_approval_outbox, retry_approval_outbox

# DSH tasks register without performing network IO; startup owns approved runtimes.
from bisheng.worker.dsh.registry import register_dsh_tasks
from bisheng.worker.information.article import sync_information_article
from bisheng.worker.information.reconcile import reconcile_all_tenants
from bisheng.worker.knowledge.file_worker import (
    file_copy_celery,
    parse_knowledge_file_celery,
    retry_knowledge_file_celery,
)
from bisheng.worker.knowledge.move_worker import migrate_file_vectors
from bisheng.worker.knowledge.qa import copy_qa_knowledge_celery, insert_qa_celery, rebuild_qa_knowledge_celery
from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery, rebuild_knowledge_file_chunk
from bisheng.worker.knowledge.scheduler import (
    reconcile_file_scheduler_task,
    trigger_dispatch_task,
)
from bisheng.worker.main import bisheng_celery
from bisheng.worker.permission.retry_failed_tuples import (
    cleanup_succeeded_failed_tuples,
    retry_failed_tuples,
)
from bisheng.worker.telemetry.mid_table import (
    sync_mid_app_increment,
    sync_mid_knowledge_increment,
    sync_mid_user_increment,
    sync_mid_user_interact_dtl,
)
from bisheng.worker.tenant_reconcile.tasks import reconcile_user_tenant_assignments
from bisheng.worker.test.test import add
from bisheng.worker.workflow.tasks import continue_workflow, execute_workflow, stop_workflow

register_dsh_tasks(bisheng_celery)

__all__ = [
    "add",
    "admin_scope_cleanup",
    "cleanup_succeeded_failed_tuples",
    "continue_workflow",
    "copy_qa_knowledge_celery",
    "execute_approval_outbox",
    "execute_workflow",
    "file_copy_celery",
    "insert_qa_celery",
    "migrate_file_vectors",
    "parse_knowledge_file_celery",
    "rebuild_knowledge_celery",
    "rebuild_knowledge_file_chunk",
    "rebuild_qa_knowledge_celery",
    "reconcile_all_tenants",
    "reconcile_file_scheduler_task",
    "reconcile_user_tenant_assignments",
    "retry_approval_outbox",
    "retry_failed_tuples",
    "retry_knowledge_file_celery",
    "stop_workflow",
    "sync_information_article",
    "sync_mid_app_increment",
    "sync_mid_knowledge_increment",
    "sync_mid_user_increment",
    "sync_mid_user_interact_dtl",
    "trigger_dispatch_task",
]
