"""AC-07/08/16/17: schedule registration and bounded candidate discovery."""

from bisheng.core.config.settings import CeleryConf, DepartmentProjectionRecoveryConf
from bisheng.permission.application.department_recovery_runtime import abnormal_department


def test_real_schedule_is_registered_and_custom_schedule_is_preserved():
    key = "recover_department_projections"
    assert "department.projection_recovery" in CeleryConf().beat_schedule[key]["task"]
    custom = {"task": "custom", "schedule": 123}
    assert CeleryConf(beat_schedule={key: custom}).beat_schedule[key] == custom
    assert DepartmentProjectionRecoveryConf().max_fga_qps == 2


def test_current_committed_binding_is_candidate_but_healthy_is_not():
    row = {"state": "CURRENT", "operation_id": 3, "version": 1, "tenant_id": 7, "id": 11}
    op = {"scope_type": "department", "scope_key": "11", "tenant_id": 7, "status": "COMMITTED", "target_version": 1}
    assert abnormal_department(row, {3: op})
    assert not abnormal_department(row, {3: op | {"status": "FINALIZED"}})


def test_schedule_interval_configuration_is_effective_without_overriding_custom():
    from bisheng.core.config.settings import Settings

    settings = Settings(department_projection_recovery={"interval_seconds": 60})
    assert settings.celery_task.beat_schedule["recover_department_projections"]["schedule"] == 60
    settings = Settings(
        department_projection_recovery={"interval_seconds": 60},
        celery_task={"beat_schedule": {"recover_department_projections": {"task": "custom", "schedule": 90}}},
    )
    assert settings.celery_task.beat_schedule["recover_department_projections"]["schedule"] == 90
