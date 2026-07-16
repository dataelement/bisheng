# ruff: noqa: F401
# register tasks
from bisheng.worker.admin_scope.tasks import admin_scope_cleanup
from bisheng.worker.approval.notification_tasks import (
    consume_approval_notification,
    dispatch_approval_notifications,
)
from bisheng.worker.approval.tasks import execute_approval_outbox, retry_approval_outbox
from bisheng.worker.information.article import sync_information_article
from bisheng.worker.knowledge.file_worker import (
    file_copy_celery,
    parse_knowledge_file_celery,
    refresh_file_similarity_candidates_celery,
    retry_knowledge_file_celery,
)
from bisheng.worker.knowledge.portal_hot_search import (
    fanout_portal_hot_search_rebuild,
    rebuild_portal_hot_search_snapshot_celery,
    trigger_portal_hot_search_rebuild_celery,
)
from bisheng.worker.knowledge.portal_recommendation import (
    fanout_portal_recommendation_maintenance,
    invalidate_department_users_celery,
    prepare_pool_rebuild_celery,
    purge_expired_searches_celery,
    rebuild_shared_pools_celery,
    rebuild_user_interest_celery,
    reconcile_full_celery,
    reconcile_incremental_celery,
    refresh_projection_celery,
)
from bisheng.worker.knowledge.qa import copy_qa_knowledge_celery, insert_qa_celery, rebuild_qa_knowledge_celery
from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery, rebuild_knowledge_file_chunk
from bisheng.worker.knowledge.space_init_worker import (
    grant_knowledge_space_scope_permissions,
    init_knowledge_space_indices,
)
from bisheng.worker.knowledge.space_migrate_worker import space_migrate_celery
from bisheng.worker.message.tasks import push_single_wechat_message, scan_wechat_message_push_outbox
from bisheng.worker.org_sync.reconcile_tasks import (
    reconcile_all_organizations,
    report_ts_conflicts_daily_escalation,
    report_ts_conflicts_weekly,
)
from bisheng.worker.org_sync.tasks import check_org_sync_schedules, execute_org_sync
from bisheng.worker.permission.retry_failed_tuples import retry_failed_tuples
from bisheng.worker.telemetry.derived_mid_table import (
    sync_mid_active_user,
    sync_mid_doc_parse_dtl,
    sync_mid_knowledge_file_increment,
    sync_mid_model_call_dtl,
    sync_mid_session_run_dtl,
    sync_mid_sessions_increment,
    sync_mid_tool_call_dtl,
)
from bisheng.worker.telemetry.mid_table import (
    sync_mid_app_increment,
    sync_mid_knowledge_increment,
    sync_mid_knowledge_space_content_stat,
    sync_mid_user_increment,
    sync_mid_user_interact_dtl,
    sync_pending_knowledge_space_content_stat,
)
from bisheng.worker.tenant_reconcile.tasks import reconcile_user_tenant_assignments
from bisheng.worker.test.test import add
from bisheng.worker.workflow.tasks import continue_workflow, execute_workflow, stop_workflow
