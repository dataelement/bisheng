"""AC-17/20: machine readable, diagnostic, credential-free alert contract."""

import json

from loguru import logger

from bisheng.permission.domain.services.projection_diagnostics import (
    emit_projection_alert,
    reason_from_exception,
    relation_diagnostics,
)


def test_alert_has_stable_key_and_bounded_safe_cause_fields():
    output = []
    handle = logger.add(lambda message: output.append(str(message)), format="{message}")
    try:
        a = emit_projection_alert(
            "MANUAL_REQUIRED",
            reason_code="ANCESTOR_INACTIVE",
            tenant_id=7,
            department_id=11,
            operation_id=9,
            details={"ancestor_id": 3, "password": "private-secret", "before_state": "FAILED_CLOSED"},
        )
        b = emit_projection_alert(
            "MANUAL_REQUIRED", reason_code="ANCESTOR_INACTIVE", tenant_id=7, department_id=11, operation_id=9
        )
        assert a["alert_key"] == b["alert_key"]
        assert a["details"] == {"ancestor_id": 3, "before_state": "FAILED_CLOSED"}
        payload = json.loads(output[0].split("PERMISSION_PROJECTION_ALERT ", 1)[1])
        assert payload["reason_code"] == "ANCESTOR_INACTIVE" and payload["schema_version"] == 1
        assert "private-secret" not in output[0]
    finally:
        logger.remove(handle)


def test_relation_diagnostics_explains_chain_but_only_counts_member_ids():
    missing = {(f"user:{i}", "member", "department:11") for i in range(100)} | {
        ("department:3", "parent", "department:11")
    }
    extra = {("department:2", "parent", "department:11")}
    details = relation_diagnostics(extra, missing, limit=2)
    assert details["missing_count"] == 101 and details["extra_count"] == 1
    assert len(details["missing_topology_sample"]) == 1
    assert "user:" not in json.dumps(details)


def test_database_timeout_reason_does_not_echo_sql_or_binds():
    error = RuntimeError("dmPython CODE:-608 select password=private-secret")
    assert reason_from_exception(error) == "DATABASE_TIMEOUT"
    assert reason_from_exception(ValueError("ANCESTOR_INACTIVE")) == "ANCESTOR_INACTIVE"


async def test_login_permission_context_logs_exact_failed_ancestor_without_user_data():
    from unittest.mock import AsyncMock

    import pytest

    from bisheng.common.errcode.permission import PermissionPublishNotReadyError
    from bisheng.department.domain.repositories.permission_context_repository import DepartmentContextRow
    from bisheng.department.domain.services.permission_context import DepartmentPermissionContextProvider

    repository = AsyncMock()
    repository.load_ancestry.return_value = (
        (11,),
        {
            11: DepartmentContextRow(11, 3, 7, "active", "CURRENT"),
            3: DepartmentContextRow(3, None, 7, "active", "FAILED_CLOSED"),
        },
    )
    output = []
    handle = logger.add(lambda message: output.append(str(message)), format="{message}")
    try:
        with pytest.raises(PermissionPublishNotReadyError):
            await DepartmentPermissionContextProvider(repository).load(999999)
        payload = json.loads(
            next(s for s in output if "PERMISSION_PROJECTION_ALERT " in s).split("PERMISSION_PROJECTION_ALERT ", 1)[1]
        )
        assert payload["event"] == "CONTEXT_REJECTED" and payload["reason_code"] == "DEPARTMENT_FAILED_CLOSED"
        assert payload["details"]["ancestor_id"] == 3 and payload["scope_key"] == "11"
        assert "999999" not in str(payload)
    finally:
        logger.remove(handle)
