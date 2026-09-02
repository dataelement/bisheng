# register tasks
from bisheng.worker.admin_scope.tasks import admin_scope_cleanup
from bisheng.worker.approval.decision_delivery_tasks import (
    coordinate_approval_decision_delivery as coordinate_approval_decision_delivery,
)
from bisheng.worker.approval.decision_delivery_tasks import (
    deliver_approval_decision as deliver_approval_decision,
)
from bisheng.worker.approval.tasks import execute_approval_outbox, retry_approval_outbox
from bisheng.worker.information.article import sync_information_article
from bisheng.worker.information.reconcile import reconcile_all_tenants
from bisheng.worker.knowledge.file_change_tasks import (
    cleanup_all_file_change_residue as cleanup_all_file_change_residue,
)
from bisheng.worker.knowledge.file_change_tasks import (
    compensate_all_file_change_execution_steps as compensate_all_file_change_execution_steps,
)
from bisheng.worker.knowledge.file_change_tasks import (
    reconcile_all_file_change_approvers as reconcile_all_file_change_approvers,
)
from bisheng.worker.knowledge.file_change_tasks import (
    watchdog_all_file_change_executions as watchdog_all_file_change_executions,
)
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
from bisheng.worker.knowledge.space_admin_reconcile import reconcile_department_space_admins
from bisheng.worker.knowledge.stale_projection_reconciler import (
    reconcile_stale_parent_projections as reconcile_stale_parent_projections,
)
from bisheng.worker.permission.resource_user_invite_tasks import (
    execute_resource_user_invite as execute_resource_user_invite,
)
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
