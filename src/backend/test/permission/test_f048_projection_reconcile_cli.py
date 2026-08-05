"""CLI contract for the F048 durable projection reconcile script."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import get_current_tenant_id
from scripts import reconcile_f048_projection_operations as cli


class FakeRepository:
    def __init__(self, operation, tuples) -> None:
        self.operation = operation
        self.tuples = tuples

    async def aget_operation(self, operation_id: int):
        if self.operation is None or self.operation.id != operation_id:
            return None
        return self.operation

    async def aget_operation_tuples(self, operation_id: int):
        if self.operation is None or self.operation.id != operation_id:
            return []
        return self.tuples


class FakeProjection:
    def __init__(self, statuses: dict[int, str]) -> None:
        self.statuses = statuses
        self.calls: list[int] = []

    async def reconcile_operation(self, operation_id: int):
        self.calls.append(operation_id)
        self.statuses[operation_id] = "FINALIZED"
        return SimpleNamespace(status="FINALIZED")


def _operation(**overrides):
    values = {
        "id": 11,
        "tenant_id": 1,
        "operation_type": "MODE_SWITCH",
        "scope_type": "resource",
        "scope_key": "folder:97327",
        "expected_version": 4,
        "target_version": 5,
        "store_id": "store-live",
        "model_id": "model-live",
        "status": "PREPARED",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _tuple(phase: str, action: str):
    return SimpleNamespace(phase=phase, action=action)


def _inspection(operation_id: int, status: str) -> cli.OperationInspection:
    return cli.OperationInspection(
        operation_id=operation_id,
        tenant_id=1,
        operation_type="MODE_SWITCH",
        scope_type="resource",
        scope_key=f"folder:{operation_id}",
        expected_version=4,
        target_version=5,
        store_id="store-live",
        model_id="model-live",
        status=status,
        tuple_count=4,
        tuple_summary={"COMMIT:WRITE": 1, "STAGE:WRITE": 3},
        resource_mode={
            "mode": "INHERIT" if status != "FINALIZED" else "CUSTOM",
            "version": 4 if status != "FINALIZED" else 5,
            "projection_state": "PROJECTING" if status != "FINALIZED" else "CURRENT",
            "operation_id": operation_id,
        },
    )


def test_parse_args_defaults_to_dry_run_and_rejects_duplicates() -> None:
    args = cli.parse_args(["--tenant-id", "1", "11", "15", "18"])

    assert args.tenant_id == 1
    assert args.operation_ids == [11, 15, 18]
    assert args.apply is False

    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(["--tenant-id", "1", "11", "11"])
    assert exc_info.value.code == 2


async def test_inspect_operation_validates_pin_ledger_and_resource_fence(monkeypatch) -> None:
    operation = _operation()
    runtime = cli.ProjectionReconcileRuntime(
        client=SimpleNamespace(store_id="store-live", model_id="model-live"),
        repository=FakeRepository(
            operation,
            [
                _tuple("STAGE", "WRITE"),
                _tuple("STAGE", "WRITE"),
                _tuple("COMMIT", "DELETE"),
                _tuple("COMMIT", "WRITE"),
            ],
        ),
        projection=None,
    )

    async def load_mode(**kwargs):
        assert kwargs == {"tenant_id": 1, "scope_key": "folder:97327"}
        return SimpleNamespace(
            mode="INHERIT",
            version=4,
            projection_state="PROJECTING",
            operation_id=11,
        )

    monkeypatch.setattr(cli, "restore_projection_plan", lambda operation, rows: (operation, rows))
    monkeypatch.setattr(cli, "_load_resource_mode", load_mode)

    inspected = await cli.inspect_operation(
        runtime,
        operation_id=11,
        tenant_id=1,
    )

    assert inspected.status == "PREPARED"
    assert inspected.tuple_count == 4
    assert inspected.tuple_summary == {
        "COMMIT:DELETE": 1,
        "COMMIT:WRITE": 1,
        "STAGE:WRITE": 2,
    }
    assert inspected.resource_mode == {
        "mode": "INHERIT",
        "version": 4,
        "projection_state": "PROJECTING",
        "operation_id": 11,
    }


async def test_inspect_operation_blocks_invalid_ledger_checksum(monkeypatch) -> None:
    runtime = cli.ProjectionReconcileRuntime(
        client=SimpleNamespace(store_id="store-live", model_id="model-live"),
        repository=FakeRepository(_operation(), [_tuple("STAGE", "WRITE")]),
        projection=None,
    )

    def reject_ledger(operation, rows):
        del operation, rows
        raise cli.PermissionVersionConflictError(msg="checksum mismatch")

    monkeypatch.setattr(cli, "restore_projection_plan", reject_ledger)

    with pytest.raises(cli.ProjectionReconcileBlockedError, match="request checksum"):
        await cli.inspect_operation(
            runtime,
            operation_id=11,
            tenant_id=1,
        )


async def test_inspect_operation_blocks_live_pin_mismatch() -> None:
    runtime = cli.ProjectionReconcileRuntime(
        client=SimpleNamespace(store_id="other-store", model_id="model-live"),
        repository=FakeRepository(_operation(), [_tuple("STAGE", "WRITE")]),
        projection=None,
    )

    with pytest.raises(cli.ProjectionReconcileBlockedError, match="OpenFGA pin"):
        await cli.inspect_operation(
            runtime,
            operation_id=11,
            tenant_id=1,
        )


async def test_execute_dry_run_never_builds_apply_runtime_or_reconciles(capsys) -> None:
    events: list[object] = []
    args = cli.parse_args(["--tenant-id", "1", "11"])

    async def initialize_context(*, config):
        events.append(("initialize", config))

    async def close_context():
        events.append("close")

    async def runtime_factory(*, apply: bool):
        events.append(("runtime", apply, get_current_tenant_id()))
        return cli.ProjectionReconcileRuntime(
            client=SimpleNamespace(store_id="store-live", model_id="model-live"),
            repository=object(),
            projection=None,
        )

    async def inspector(runtime, *, operation_id: int, tenant_id: int):
        del runtime
        events.append(("inspect", operation_id, tenant_id))
        return _inspection(operation_id, "PREPARED")

    async def active_loader():
        return [{"operation_id": 11, "status": "PREPARED"}]

    exit_code = await cli.execute(
        args,
        runtime_factory=runtime_factory,
        operation_inspector=inspector,
        active_loader=active_loader,
        initialize_context=initialize_context,
        close_context=close_context,
        live_settings="live-settings",
    )

    assert exit_code == cli.EXIT_OK
    assert events == [
        ("initialize", "live-settings"),
        ("runtime", False, 1),
        ("inspect", 11, 1),
        "close",
    ]
    assert get_current_tenant_id() is None
    output = capsys.readouterr().out
    assert '"mode": "dry-run"' in output
    assert "no SQL or OpenFGA mutations were requested" in output


async def test_execute_preflights_all_targets_before_first_reconcile() -> None:
    args = cli.parse_args(["--tenant-id", "1", "11", "15", "--apply"])
    statuses = {11: "PREPARED", 15: "PREPARED"}
    projection = FakeProjection(statuses)

    async def no_op_context(**kwargs):
        del kwargs

    async def runtime_factory(*, apply: bool):
        assert apply is True
        return cli.ProjectionReconcileRuntime(
            client=SimpleNamespace(store_id="store-live", model_id="model-live"),
            repository=object(),
            projection=projection,
        )

    async def inspector(runtime, *, operation_id: int, tenant_id: int):
        del runtime, tenant_id
        if operation_id == 15:
            raise cli.ProjectionReconcileBlockedError("second preflight failed")
        return _inspection(operation_id, statuses[operation_id])

    with pytest.raises(cli.ProjectionReconcileBlockedError, match="second preflight"):
        await cli.execute(
            args,
            runtime_factory=runtime_factory,
            operation_inspector=inspector,
            active_loader=lambda: None,
            initialize_context=no_op_context,
            close_context=no_op_context,
            live_settings="live-settings",
        )

    assert projection.calls == []
    assert get_current_tenant_id() is None


async def test_execute_reconciles_in_order_and_skips_finalized(capsys) -> None:
    args = cli.parse_args(["--tenant-id", "1", "11", "15", "18", "--apply"])
    statuses = {11: "PREPARED", 15: "FINALIZED", 18: "COMMIT_UNKNOWN"}
    projection = FakeProjection(statuses)

    async def initialize_context(**kwargs):
        del kwargs

    async def close_context():
        return None

    async def runtime_factory(*, apply: bool):
        assert apply is True
        return cli.ProjectionReconcileRuntime(
            client=SimpleNamespace(store_id="store-live", model_id="model-live"),
            repository=object(),
            projection=projection,
        )

    async def inspector(runtime, *, operation_id: int, tenant_id: int):
        del runtime, tenant_id
        return _inspection(operation_id, statuses[operation_id])

    async def active_loader():
        return []

    exit_code = await cli.execute(
        args,
        runtime_factory=runtime_factory,
        operation_inspector=inspector,
        active_loader=active_loader,
        initialize_context=initialize_context,
        close_context=close_context,
        live_settings="live-settings",
    )

    assert exit_code == cli.EXIT_OK
    assert projection.calls == [11, 18]
    output = capsys.readouterr().out
    assert '"event": "skip_finalized", "operation_id": 15' in output
    assert output.count('"event": "reconciled"') == 2
    assert '"count": 0, "event": "remaining_active"' in output


def test_finalized_inspection_helper_reflects_current_mode() -> None:
    active = _inspection(11, "PREPARED")
    finalized = replace(
        active,
        status="FINALIZED",
        resource_mode={
            "mode": "CUSTOM",
            "version": 5,
            "projection_state": "CURRENT",
            "operation_id": 11,
        },
    )

    assert finalized.status == "FINALIZED"
    assert finalized.resource_mode["projection_state"] == "CURRENT"
