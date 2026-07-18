"""Regression coverage for retired organization-reconcile Celery tasks."""

from bisheng.core.config.settings import CeleryConf


def test_obsolete_organization_tasks_are_not_scheduled():
    conf = CeleryConf()

    obsolete_tasks = {
        "reconcile_all_organizations",
        "report_ts_conflicts_weekly",
        "report_ts_conflicts_daily_escalation",
    }
    assert obsolete_tasks.isdisjoint(conf.beat_schedule)


def test_user_tenant_reconcile_uses_default_queue():
    conf = CeleryConf()

    schedule = conf.beat_schedule["reconcile_user_tenant_assignments"]
    assert "options" not in schedule
    assert "bisheng.worker.tenant_reconcile.*" not in conf.task_routers


def test_admin_scope_cleanup_uses_default_queue():
    conf = CeleryConf()

    schedule = conf.beat_schedule["admin_scope_cleanup"]
    assert "options" not in schedule
    assert "bisheng.worker.admin_scope.*" not in conf.task_routers
