"""Stable alert contract; never serialize exceptions, SQL binds or member lists."""

import json
import re
from hashlib import sha256

from loguru import logger

_REASON_CODES = frozenset(
    {
        "OTHER_ACTIVE_DEPARTMENT_OPERATION",
        "ANCESTOR_INACTIVE",
        "ANCESTOR_MISSING",
        "ANCESTOR_NOT_CURRENT",
        "BUSINESS_PATH_INVALID",
        "UNEXPLAINED_TENANT_BOUNDARY",
        "MOUNT_BINDING_INVALID",
        "NESTED_MOUNT",
        "DEPARTMENT_INACTIVE",
        "LIFECYCLE_CONFLICT_ACTIVE_DELETED",
        "OPERATION_MODEL_PIN_MISMATCH",
        "COMMITTED_AFTER_STATE_MISSING",
        "ORIGINAL_TARGET_NO_LONGER_CURRENT",
        "DRIFT_OUTSIDE_ORIGINAL_EFFECTS",
        "UNPROVEN_ORIGINAL_EFFECTS",
        "BOUND_OPERATION_MISSING",
        "BOUND_OPERATION_NOT_OWNED",
        "SQL_COMMIT_NOT_VERIFIED",
        "ARCHIVE_OWNER_CLEANUP_REQUIRED",
        "BUSINESS_PARENT_CHANGED",
        "ANCESTRY_CYCLE_OR_LIMIT",
        "ANCESTRY_CHANGED_DURING_RECOVERY",
        "PERMISSION_TARGET_MISMATCH",
        "UNKNOWN_WRITE_OUTCOME",
        "MODEL_OR_CATALOG_NOT_READY",
        "RESTORED_AFTER_VERIFIED",
        "IAM_CONFIG_REQUIRED_FOR_UNPROVEN_BUSINESS",
        "IAM_BUSINESS_RESPONSE_NOT_SUCCESS",
        "IAM_PARENT_ANCESTRY_NOT_CURRENT",
        "THIRD_TOPOLOGY_STATE_REQUIRES_PREVIEW",
        "BUSINESS_OR_MODEL_CHANGED_REQUIRES_PREVIEW",
        "DEPARTMENT_BINDING_CHANGED",
    }
)
_ALLOWED_DETAILS = frozenset(
    {
        "ancestor_id",
        "ancestor_status",
        "ancestor_deleted",
        "ancestor_projection_state",
        "actual_parent_id",
        "expected_parent_id",
        "actual_path",
        "expected_path",
        "before_state",
        "current_state",
        "operation_status",
        "expected_version",
        "target_version",
        "current_version",
        "store_id",
        "model_id",
        "current_store_id",
        "current_model_id",
        "exception_type",
        "database_code",
        "commit_state",
        "missing_count",
        "extra_count",
        "missing_member_count",
        "extra_member_count",
        "missing_topology_sample",
        "extra_topology_sample",
        "phase",
        "run_id",
        "recovery_id",
        "contained",
        "attempt",
        "mode",
    }
)


def reason_from_exception(error):
    text = str(error)
    for message, reason in {
        "Department binding changed": "DEPARTMENT_BINDING_CHANGED",
        "Department binding/version changed": "DEPARTMENT_BINDING_VERSION_CHANGED",
        "Department version changed": "DEPARTMENT_VERSION_CHANGED",
        "Original request changed": "ORIGINAL_REQUEST_CHANGED",
        "Recovery authorization release is not ACTIVE": "MODEL_OR_CATALOG_NOT_READY",
    }.items():
        if message in text:
            return reason
    if type(error).__name__ in {"RecoveryBlockedError", "RecoveryRuntimeError", "IamLookupError"}:
        candidate = text.rsplit(":", 1)[-1]
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", candidate):
            return candidate
    if "dedicated department reconciliation CLI" in text:
        return "MAINTENANCE_OPERATION_REQUIRES_CLI"
    if "marker" in text.lower() and ("unavailable" in text.lower() or "not ready" in text.lower()):
        return "CONSISTENCY_MARKER_NOT_READY"
    if "MIXED" in text:
        return "FGA_MIXED_COMMIT"
    if re.search(r"(?:CODE\s*:\s*|\[)-608\b", text):
        return "DATABASE_TIMEOUT"
    if type(error).__name__ == "RedisLockLostError":
        return "EXECUTION_LEASE_LOST"
    if type(error).__name__ == "RedisLockBusyError":
        return "EXECUTION_LEASE_BUSY"
    for reason in sorted(_REASON_CODES, key=len, reverse=True):
        if reason in text:
            return reason
    if type(error).__name__ in {"TimeoutError", "ReadTimeout", "ConnectTimeout"}:
        return "INFRASTRUCTURE_TIMEOUT"
    if type(error).__name__.startswith("FGA"):
        return "FGA_TRANSPORT_ERROR"
    return "UNCLASSIFIED_PROJECTION_FAILURE"


def relation_diagnostics(observed, target, *, limit=8):
    missing, extra = set(target) - set(observed), set(observed) - set(target)
    return {
        "missing_count": len(missing),
        "extra_count": len(extra),
        "missing_member_count": sum(k[1] == "member" for k in missing),
        "extra_member_count": sum(k[1] == "member" for k in extra),
        "missing_topology_sample": [list(k) for k in sorted(missing) if k[1] in {"parent", "child"}][:limit],
        "extra_topology_sample": [list(k) for k in sorted(extra) if k[1] in {"parent", "child"}][:limit],
    }


def emit_projection_alert(
    event,
    *,
    reason_code,
    tenant_id,
    department_id=None,
    operation_id=None,
    scope_type="department",
    scope_key=None,
    details=None,
):
    level = (
        "INFO"
        if event in {"RECOVERED", "PROJECTED"}
        else "WARNING"
        if event == "EXECUTION_BUSY" or reason_code == "DEPARTMENT_PROJECTING"
        else "ERROR"
    )
    identity = {
        "tenant_id": tenant_id,
        "scope_type": scope_type,
        "scope_key": str(scope_key or department_id or ""),
        "operation_id": operation_id,
        "reason_code": reason_code,
    }
    payload = {
        "schema_version": 1,
        "severity": level,
        "event": event,
        **identity,
        "alert_key": sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24],
        "details": {k: v for k, v in (details or {}).items() if k in _ALLOWED_DETAILS},
    }
    # A fixed prefix works with both plain-text and JSON log collectors.
    message = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    logger.bind(permission_projection_alert=payload).log(level, "PERMISSION_PROJECTION_ALERT {}", message)
    return payload
