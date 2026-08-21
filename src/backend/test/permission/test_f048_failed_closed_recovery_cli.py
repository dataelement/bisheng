"""CLI safety contract for FAILED_CLOSED resource projection recovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import get_current_tenant_id
from scripts import recover_f048_failed_closed_projection as cli


def _args(*extra: str):
    return cli.parse_args(
        [
            "--tenant-id",
            "1",
            "--resource-type",
            "knowledge_space",
            "--resource-id",
            "4166",
            *extra,
        ]
    )


def _operation(**overrides):
    values = {
        "id": 405,
        "tenant_id": 1,
        "operation_type": "GRANT_MUTATION",
        "scope_type": "resource",
        "scope_key": "knowledge_space:4166",
        "expected_version": 19,
        "target_version": 20,
        "store_id": "store-live",
        "model_id": "model-live",
        "status": "FAILED_CLOSED",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _mode(**overrides):
    values = {
        "mode": "CUSTOM",
        "version": 19,
        "projection_state": "FAILED_CLOSED",
        "operation_id": 405,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _preview():
    return SimpleNamespace(
        operation_id=405,
        tenant_id=1,
        operation_type="GRANT_MUTATION",
        operation_status="FAILED_CLOSED",
        scope_key="knowledge_space:4166",
        expected_version=19,
        target_version=20,
        store_id="store-live",
        model_id="model-live",
        request_checksum="r" * 64,
        after_checksum="a" * 64,
        observed_state="MIXED",
        target_tuple_count=7,
        correction_deltas=(
            SimpleNamespace(action="WRITE", relation="ordinary_assignee"),
            SimpleNamespace(action="DELETE", relation="ordinary_assignee"),
        ),
        confirmation_checksum="c" * 64,
    )


class FakeRepository:
    def __init__(self, operation) -> None:
        self.operation = operation

    async def aget_operation(self, operation_id: int):
        return self.operation if operation_id == self.operation.id else None

    async def aget_visible_operation_sources(self, operation_id: int):
        assert operation_id == self.operation.id
        return [SimpleNamespace(state="PENDING")]


class FakeProjection:
    def __init__(self, preview) -> None:
        self.preview = preview

    async def inspect_failed_closed_recovery(self, operation_id: int):
        assert operation_id == 405
        return self.preview


def test_parse_args_defaults_to_dry_run_and_apply_requires_confirmations() -> None:
    args = _args()
    assert args.apply is False

    with pytest.raises(SystemExit) as exc_info:
        _args("--apply")
    assert exc_info.value.code == 2

    args = _args(
        "--apply",
        "--confirm-store-id",
        "store-live",
        "--confirm-model-id",
        "model-live",
        "--confirm-recovery-checksum",
        "c" * 64,
    )
    assert args.apply is True


@pytest.mark.asyncio
async def test_inspect_binds_operation_scope_pin_and_live_correction(monkeypatch) -> None:
    preview = _preview()
    runtime = cli.RecoveryRuntime(
        client=SimpleNamespace(store_id="store-live", model_id="model-live"),
        projection=FakeProjection(preview),
        repository=FakeRepository(_operation()),
    )

    async def load_mode(**kwargs):
        assert kwargs == {
            "tenant_id": 1,
            "resource_type": "knowledge_space",
            "resource_id": "4166",
        }
        return _mode()

    monkeypatch.setattr(cli, "_load_mode", load_mode)
    inspected, payload = await cli.inspect(runtime, _args())

    assert inspected is preview
    assert payload["observed_state"] == "MIXED"
    assert payload["correction_tuple_count"] == 2
    assert payload["correction_summary"] == {
        "DELETE:ordinary_assignee": 1,
        "WRITE:ordinary_assignee": 1,
    }
    assert payload["visible_source_summary"] == {"PENDING": 1}
    assert payload["recovery_confirmation_checksum"] == "c" * 64


@pytest.mark.asyncio
async def test_execute_dry_run_never_recovers(monkeypatch, capsys) -> None:
    events: list[object] = []
    preview = _preview()
    runtime = SimpleNamespace()

    async def initialize_context(*, config):
        events.append(("initialize", config))

    async def close_context():
        events.append("close")

    async def build_runtime():
        events.append(("runtime", get_current_tenant_id()))
        return runtime

    async def inspect(runtime_arg, args):
        assert runtime_arg is runtime
        events.append(("inspect", args.resource_type, args.resource_id))
        return preview, {
            "operation_id": 405,
            "status": "FAILED_CLOSED",
        }

    monkeypatch.setattr(cli, "initialize_app_context", initialize_context)
    monkeypatch.setattr(cli, "close_app_context", close_context)
    monkeypatch.setattr(cli, "_build_runtime", build_runtime)
    monkeypatch.setattr(cli, "inspect", inspect)

    exit_code = await cli.execute(_args())

    assert exit_code == cli.EXIT_OK
    assert events[1:] == [
        ("runtime", 1),
        ("inspect", "knowledge_space", "4166"),
        "close",
    ]
    assert get_current_tenant_id() is None
    assert "[dry-run] no SQL or OpenFGA mutations" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_execute_apply_uses_confirmed_domain_recovery_and_verifies(monkeypatch) -> None:
    preview = _preview()

    class ApplyingProjection:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str]] = []

        async def recover_failed_closed_operation(
            self,
            operation_id: int,
            *,
            confirmation_checksum: str,
        ):
            self.calls.append((operation_id, confirmation_checksum))
            return SimpleNamespace(status="FINALIZED")

    projection = ApplyingProjection()
    runtime = SimpleNamespace(projection=projection)
    inspections = iter(
        (
            (preview, {"operation_id": 405, "status": "FAILED_CLOSED"}),
            (
                None,
                {
                    "operation_id": 405,
                    "status": "FINALIZED",
                    "resource_mode": {
                        "version": 20,
                        "projection_state": "CURRENT",
                    },
                },
            ),
        )
    )

    async def no_op_context(**kwargs):
        del kwargs

    async def build_runtime():
        return runtime

    async def inspect(*args, **kwargs):
        del args, kwargs
        return next(inspections)

    monkeypatch.setattr(cli, "initialize_app_context", no_op_context)
    monkeypatch.setattr(cli, "close_app_context", no_op_context)
    monkeypatch.setattr(cli, "_build_runtime", build_runtime)
    monkeypatch.setattr(cli, "inspect", inspect)

    exit_code = await cli.execute(
        _args(
            "--apply",
            "--confirm-store-id",
            "store-live",
            "--confirm-model-id",
            "model-live",
            "--confirm-recovery-checksum",
            "c" * 64,
        )
    )

    assert exit_code == cli.EXIT_OK
    assert projection.calls == [(405, "c" * 64)]
    assert get_current_tenant_id() is None
