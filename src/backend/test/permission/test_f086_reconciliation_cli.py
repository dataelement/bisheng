"""AC-09/13/18: default entry initializes no writer infrastructure."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.permission.application.department_batch_repair import build_plan
from scripts import reconcile_department_projections as cli


async def test_default_scan_initializes_database_only_and_never_checks_write_marker(monkeypatch, tmp_path):
    initialize = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr(cli, "initialize_app_context", initialize)
    monkeypatch.setattr(cli, "close_app_context", close)
    environment = {"store_id": "s", "model_id": "m"}
    runtime = SimpleNamespace(
        initialize=AsyncMock(),
        environment=AsyncMock(return_value=environment),
        ledger=SimpleNamespace(check_existing_schema=AsyncMock()),
        client=SimpleNamespace(close=AsyncMock()),
        fga=SimpleNamespace(ready=AsyncMock()),
        limiter=SimpleNamespace(calls=3, interval=0.5),
    )
    monkeypatch.setattr(cli, "DepartmentBatchRuntime", lambda *a, **kw: runtime)
    plan = build_plan(environment, {"tenant_id": 1}, [])
    monkeypatch.setattr(
        cli, "DepartmentBatchRepairApplication", lambda backend: SimpleNamespace(scan=AsyncMock(return_value=plan))
    )
    args = cli.parse_args(["--tenant-id", "1", "--environment-id", "test", "--output-dir", str(tmp_path / "scan")])
    assert await cli.execute(args) == 0
    assert initialize.await_args.kwargs["context_names"] == ("database",)
    runtime.fga.ready.assert_not_awaited()
    assert (tmp_path / "scan" / "plan.jsonl").exists()


def test_existing_backup_confirmation_is_enough_without_extra_json_or_source_hash():
    args = cli.parse_args(
        [
            "--tenant-id",
            "1",
            "--environment-id",
            "test",
            "--output-dir",
            "/tmp/new-evidence",
            "--apply",
            "--plan-file",
            "/tmp/plan.jsonl",
            "--confirm-plan",
            "checksum",
            "--confirm-backups-completed",
            "--confirm-writers-idle",
            "--window-id",
            "window",
        ]
    )
    assert args.backup_evidence is None and args.apply


async def test_real_runtime_constructs_without_database_or_iam_and_accepts_drain_flag():
    from bisheng.api.services.department_reconciliation_runtime import DepartmentBatchRuntime

    runtime = DepartmentBatchRuntime("test-construction", iam_lookup=None, writers_idle=True)
    try:
        assert runtime.writers_idle is True and runtime.session is None
    finally:
        await runtime.client.close()
