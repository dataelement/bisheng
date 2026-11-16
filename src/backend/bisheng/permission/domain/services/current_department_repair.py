"""Bounded current-state facts for the production department repair tool."""

from uuid import NAMESPACE_URL, uuid5

from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError, checksum

REPAIR_TYPE = "DEPARTMENT_RECONCILE"
FORMAT = "cofco.department-recovery.item.v1"
MAX_KEYS = 10000
MAX_DELTA = 90
MAX_RECORD_BYTES = 1024 * 1024
ACTIVE = frozenset({"PREPARED", "STAGING", "COMMIT_UNKNOWN", "COMMITTED"})
KNOWN_EFFECTS = frozenset(
    {
        "DEPARTMENT_CREATE",
        "DEPARTMENT_MOVE",
        "DEPARTMENT_PARENT_REMOVE",
        "DEPARTMENT_ARCHIVE",
        "DEPARTMENT_RESTORE",
        "DEPARTMENT_MEMBERS_ADD",
        "DEPARTMENT_MEMBER_REMOVE",
        REPAIR_TYPE,
    }
)


def event_id(recovery_id, stage):
    return uuid5(NAMESPACE_URL, f"bisheng:f086:current:v1:{recovery_id}:{stage}").hex


def owned_key(key, department_id):
    user, relation, obj = key
    if relation == "parent" and obj == f"department:{department_id}":
        value = user.removeprefix("department:")
        return user.startswith("department:") and value.isdecimal() and int(value) > 0 and int(value) != department_id
    if relation == "child" and user == f"department:{department_id}":
        value = obj.removeprefix("department:")
        return obj.startswith("department:") and value.isdecimal() and int(value) > 0 and int(value) != department_id
    if relation == "member" and obj == f"department:{department_id}":
        value = user.removeprefix("user:")
        return user.startswith("user:") and value.isdecimal() and int(value) > 0
    return False


def archive_owned_key(key, department_id):
    if owned_key(key, department_id):
        return True
    user, relation, obj = key
    value = user.removeprefix("user:")
    return (
        relation == "admin"
        and obj == f"department:{department_id}"
        and user.startswith("user:")
        and value.isascii()
        and value.isdecimal()
        and int(value) > 0
    )


def target_keys(department, members):
    status, deleted = department["status"], department["deleted"]
    if deleted not in (0, 1) or status not in {"active", "archived"}:
        raise RecoveryBlockedError("LIFECYCLE_UNPROVEN")
    if status == "active" and deleted:
        raise RecoveryBlockedError("LIFECYCLE_CONFLICT_ACTIVE_DELETED")
    if status != "active":
        raise RecoveryBlockedError("DEPARTMENT_INACTIVE_REQUIRES_BUSINESS_OWNER")
    identity = department["id"]
    target = {(f"user:{uid}", "member", f"department:{identity}") for uid in members}
    if status == "active" and department["parent_id"] is not None:
        parent = int(department["parent_id"])
        if parent <= 0 or parent == identity:
            raise RecoveryBlockedError("INVALID_PARENT")
        target.update(
            {
                (f"department:{parent}", "parent", f"department:{identity}"),
                (f"department:{identity}", "child", f"department:{parent}"),
            }
        )
    return frozenset(target)


def correction(observed, target):
    if len(observed | target) > MAX_KEYS:
        raise RecoveryBlockedError("SCOPE_TOO_LARGE")
    rows = [{"action": "DELETE", "user": k[0], "relation": k[1], "object": k[2]} for k in sorted(observed - target)] + [
        {"action": "WRITE", "user": k[0], "relation": k[1], "object": k[2]} for k in sorted(target - observed)
    ]
    if len(rows) > MAX_DELTA:
        raise RecoveryBlockedError("ATOMIC_DIFF_EXCEEDS_90")
    return rows


def business_identity(proof):
    return checksum(proof)


def validate_history(operation, rows, identity, *, archive=False):
    """Unrecognized pending effects cannot be silently erased by a tree repair."""
    owns = archive_owned_key if archive else owned_key
    if any(not owns((r.fga_user, r.relation, r.fga_object), identity) for r in rows):
        raise RecoveryBlockedError("UNPROVEN_PENDING_DEPARTMENT_EFFECTS")
    if operation["operation_type"] == "DEPARTMENT_CURRENT_REPAIR" and operation.get("legacy_sealed_v2_verified"):
        return
    if operation["operation_type"] in KNOWN_EFFECTS:
        return
    raise RecoveryBlockedError("UNPROVEN_PENDING_DEPARTMENT_EFFECTS")
