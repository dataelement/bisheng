"""Current-state repair gates and reentry, without external services."""

from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.application.current_department_repair import CurrentDepartmentRepairApplication as Application
from bisheng.permission.domain.services.current_department_repair import correction, owned_key, target_keys
from bisheng.permission.domain.services.department_recovery_plan import RecoveryBlockedError


class Backend:
    def __init__(self, source_type="DEPARTMENT_CREATE", parent=3):
        self.department = {
            "id": 42,
            "tenant_id": 1,
            "parent_id": parent,
            "path": "/1/3/42/",
            "status": "active",
            "deleted": 0,
            "is_tenant_root": 0,
            "mounted_tenant_id": None,
            "state": "FAILED_CLOSED",
            "version": 7,
            "operation_id": 9,
        }
        self.env = {"store_id": "current-store", "model_id": "current-model", "catalog_id": 2}
        self.members = [10]
        self.present = {
            ("department:2", "parent", "department:42"),
            ("department:42", "child", "department:2"),
            ("user:11", "member", "department:42"),
        }
        self.source = {
            "id": 9,
            "operation_type": source_type,
            "tenant_id": 1,
            "scope_type": "department",
            "scope_key": "42",
            "status": "FAILED_CLOSED",
            "target_version": 8,
            "store_id": "old-store",
            "model_id": "old-model",
        }
        self.records, self.operations, self.final_records, self.writes = {}, {}, {}, []
        self.fail_finalize = self.fail_after_gate = False
        self.wait_for_request_slot, self.arm_repair = AsyncMock(), AsyncMock()

    def proof(self):
        fields = ("id", "tenant_id", "parent_id", "path", "status", "deleted", "is_tenant_root", "mounted_tenant_id")
        return {
            "department": {k: self.department[k] for k in fields},
            "ancestors": [],
            "mounts": [],
            "direct_members": list(self.members),
        }

    async def snapshot(self, identity, **kwargs):
        if self.fail_after_gate and self.records:
            raise RuntimeError("interrupted after durable gate")
        return {
            "environment": dict(self.env),
            "department": dict(self.department),
            "business": self.proof(),
            "observed": frozenset(self.present),
            "sources": [(dict(self.source), [], True)],
        }

    async def record(self, identity, **kwargs):
        return deepcopy(self.records.get(identity))

    async def prepare(self, payload):
        self.department.update(state="FAILED_CLOSED", operation_id=99)
        self.operations[99] = "FAILED_CLOSED"
        self.records[payload["recovery_id"]] = {"preview": deepcopy(payload), "operation_id": 99}

    async def completed(self, record, current):
        if self.operations[99] == "FINALIZED":
            return "FINALIZED_HISTORY_ONLY" if self.department["operation_id"] != 99 else "ALREADY_DONE"
        return None

    async def has_active_operations(self, department):
        return False

    async def observed(self, identity):
        return frozenset(self.present)

    async def write_repair(self, rows):
        self.writes.append(deepcopy(rows))
        for row in rows:
            key = row["user"], row["relation"], row["object"]
            self.present.add(key) if row["action"] == "WRITE" else self.present.remove(key)

    async def current_business(self, identity, **kwargs):
        return self.proof()

    async def environment(self, **kwargs):
        return dict(self.env)

    async def finalize(self, record):
        self.department.update(state="CURRENT", version=self.department["version"] + 1)
        self.operations[99] = "FINALIZED"
        if self.fail_finalize:
            raise RuntimeError("SQL rollback")
        self.final_records[record["preview"]["recovery_id"]] = True

    async def verify_repair(self, identity):
        assert self.final_records[identity] and self.operations[99] == "FINALIZED"

    @asynccontextmanager
    async def transaction(self):
        sql = deepcopy((self.department, self.records, self.operations, self.final_records))
        try:
            yield
        except BaseException:
            self.department, self.records, self.operations, self.final_records = sql
            raise


@pytest.mark.parametrize(
    "source_type",
    [
        "DEPARTMENT_CREATE",
        "DEPARTMENT_MOVE",
        "DEPARTMENT_RESTORE",
        "DEPARTMENT_ARCHIVE",
        "DEPARTMENT_MEMBERS_ADD",
        "DEPARTMENT_MEMBER_REMOVE",
    ],
)
async def test_current_facts_not_historical_operation_define_target(source_type):
    backend, audit = Backend(source_type), AsyncMock()
    app = Application(backend)
    p = (await app.inspect_department(42)).payload
    assert p["environment"]["model_id"] != p["sources"][0]["operation"]["model_id"]
    assert not backend.records and not backend.writes
    backend.arm_repair.assert_not_called()
    assert await app.recover_department(p, audit) == "FINALIZED"
    assert backend.present == target_keys(backend.department, backend.members)
    assert backend.department["version"] == 8 and backend.source["status"] == "FAILED_CLOSED"
    assert await app.recover_department(p, audit) == "ALREADY_DONE"
    assert len(backend.writes) == 1 and backend.department["version"] == 8


async def test_gate_commit_interruption_can_resume_from_shared_proof():
    backend = Backend()
    app = Application(backend)
    p = (await app.inspect_department(42)).payload
    backend.fail_after_gate = True
    with pytest.raises(RuntimeError, match="interrupted"):
        await app.recover_department(p, AsyncMock())
    assert backend.department["state"] == "FAILED_CLOSED" and backend.records and not backend.writes
    backend.fail_after_gate = False
    assert await Application(backend).resume(p["recovery_id"], AsyncMock()) == "FINALIZED"


async def test_fga_after_sql_rollback_only_closes_sql_on_retry():
    backend = Backend()
    app = Application(backend)
    p = (await app.inspect_department(42)).payload
    backend.fail_finalize = True
    with pytest.raises(RuntimeError, match="rollback"):
        await app.recover_department(p, AsyncMock())
    assert backend.department["state"] == "FAILED_CLOSED" and backend.department["version"] == 7
    backend.fail_finalize = False
    assert await app.recover_department(p, AsyncMock()) == "FINALIZED"
    assert len(backend.writes) == 1 and backend.department["version"] == 8


@pytest.mark.parametrize("change", ["business", "model", "binding", "relations"])
async def test_stale_seal_never_overwrites_subsequent_facts(change):
    backend = Backend()
    app = Application(backend)
    p = (await app.inspect_department(42)).payload
    backend.fail_after_gate = True
    with pytest.raises(RuntimeError):
        await app.recover_department(p, AsyncMock())
    backend.fail_after_gate = False
    if change == "business":
        backend.members.append(12)
    elif change == "model":
        backend.env["model_id"] = "third-model"
    elif change == "binding":
        backend.department["operation_id"] = 101
    else:
        backend.present.add(("user:12", "member", "department:42"))
    with pytest.raises(RecoveryBlockedError):
        await app.resume(p["recovery_id"], AsyncMock())
    assert not backend.writes


async def test_before_file_failure_prevents_gate_marker_fga_sql():
    backend = Backend()
    app = Application(backend)
    p = (await app.inspect_department(42)).payload
    audit = AsyncMock()
    audit.before.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        await app.recover_department(p, audit)
    assert not backend.records and not backend.writes and backend.department["operation_id"] == 9


async def test_root_zero_delta_has_no_fictitious_write():
    backend = Backend(parent=None)
    backend.members, backend.present = [], set()
    app = Application(backend)
    p = (await app.inspect_department(42)).payload
    assert p["target"] == [] and p["correction"] == []
    assert await app.recover_department(p, AsyncMock()) == "FINALIZED"
    assert not backend.writes


async def test_member_failure_with_correct_relations_only_closes_state():
    backend = Backend("DEPARTMENT_MEMBERS_ADD")
    backend.present = set(target_keys(backend.department, backend.members))
    app = Application(backend)
    p = (await app.inspect_department(42)).payload
    assert p["classification"] == "RECOVER_STATE_ONLY"
    assert await app.recover_department(p, AsyncMock()) == "FINALIZED"
    assert not backend.writes


@pytest.mark.parametrize("status,deleted", [("active", 1), ("unknown", 0), ("active", 2)])
def test_lifecycle_conflicts_never_produce_target(status, deleted):
    with pytest.raises(RecoveryBlockedError, match="LIFECYCLE"):
        target_keys(Backend().department | {"status": status, "deleted": deleted}, [])


@pytest.mark.parametrize(
    "key",
    [
        ("user:1", "admin", "department:42"),
        ("department:42", "parent", "department:99"),
        ("department:99", "child", "department:42"),
        ("user:*", "member", "department:42"),
        ("user:1#member", "member", "department:42"),
    ],
)
def test_scope_excludes_admin_other_children_and_usersets(key):
    assert not owned_key(key, 42)


def test_large_diff_blocks_before_partial_writes():
    with pytest.raises(RecoveryBlockedError, match="90"):
        correction(set(), {(f"user:{i}", "member", "department:42") for i in range(1, 92)})


def test_tampered_confirmation_is_rejected():
    p = Application.preview(
        {
            "department": Backend().department,
            "business": Backend().proof(),
            "observed": set(),
            "sources": [(Backend().source, [], True)],
            "environment": {},
        }
    )
    p["department_id"] = 43
    with pytest.raises(RecoveryBlockedError, match="CONFIRMATION"):
        Application.validate_confirmation(p)


async def test_archived_is_report_only_without_gate_or_fga_changes():
    backend = Backend()
    backend.department.update(status="archived", deleted=1)
    app = Application(backend)
    with pytest.raises(RecoveryBlockedError, match="INACTIVE"):
        await app.inspect_department(42)
    assert not backend.records and not backend.writes
    assert backend.department["status"] == "archived" and backend.department["deleted"] == 1


async def test_post_gate_block_stops_batch_instead_of_refunding_limit():
    from types import SimpleNamespace

    from bisheng.permission.domain.services.department_recovery_plan import RecoveryRuntimeError

    backend = Backend()
    app = Application(backend)
    p = (await app.inspect_department(42)).payload
    original_prepare = backend.prepare

    async def prepare_then_drift(payload):
        await original_prepare(payload)
        backend.members.append(12)

    backend.prepare = prepare_then_drift
    original_inspect = app.inspect_department
    inspected = []

    async def inspect(identity):
        inspected.append(identity)
        assert identity == 42, "must not inspect/prepare another department after durable gate"
        return await original_inspect(identity)

    app.inspect_department = inspect
    audit = SimpleNamespace(before=AsyncMock(), emit=lambda *a, **k: None)
    with pytest.raises(RecoveryRuntimeError, match="STOP_BATCH"):
        await app.recover_department(p, audit)
    assert not inspected and backend.records and backend.department["state"] == "FAILED_CLOSED"
    assert not backend.writes
