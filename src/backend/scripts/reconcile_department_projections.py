#!/usr/bin/env python3
"""Full department dry-run with optional targeted IAM, then one dependency-ordered apply.

From the private backend root with the API's config and PYTHONPATH=./:
python scripts/reconcile_department_batch_production.py --scan-departments \
  --tenant-id 1 --environment-id production --iam-config /evidence/iam.json \
  --output-dir /evidence/new-scan

Default only reads SQL/FGA/IAM. Apply requires the complete approved batch plan,
existing backup coverage confirmation and drained relevant writers.
"""

# ruff: noqa: E402 -- bootstrap the backend before importing application code
import argparse
import asyncio
import json
import math
import os
import sys
import time

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.api.services.department_reconciliation_runtime import DepartmentBatchRuntime
from bisheng.common.services.config_service import settings
from bisheng.core.context.manager import close_app_context, initialize_app_context
from bisheng.permission.application.department_batch_repair import DepartmentBatchRepairApplication
from bisheng.permission.application.department_recovery_runtime import positive, tenant_scope
from bisheng.permission.domain.services.department_recovery_plan import (
    RecoveryBlockedError,
    RecoveryRuntimeError,
    checksum,
)
from scripts.current_department_repair_io import ProductionRepairAudit, backup_evidence
from scripts.department_batch_io import private_batch_plan, write_batch_plan
from scripts.iam_department_lookup import IamDepartmentLookup


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scan", "--scan-departments", dest="scan_departments", action="store_true")
    mode.add_argument(
        "--department-id", nargs="+", type=positive, help="Pilot scope plus automatically included dependencies"
    )
    mode.add_argument("--plan-file")
    parser.add_argument("--tenant-id", type=positive, required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--iam-config", help="Only needed for business facts SQL cannot prove")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--offline-maintenance",
        action="store_true",
        help="All other organization/FGA writers are stopped; enable offline execution optimizations and FGA QPS up to 20",
    )
    parser.add_argument("--max-fga-qps", type=float, default=2)
    parser.add_argument("--max-plan-items", type=positive, default=50000)
    parser.add_argument(
        "--max-repairs", type=positive, default=10000, help="Refuse the whole batch before writes if exceeded"
    )
    parser.add_argument("--relation-read-timeout-seconds", type=positive, default=120)
    parser.add_argument("--scan-timeout-seconds", type=positive, default=7200)
    parser.add_argument("--execution-timeout-seconds", type=positive, default=21600)
    parser.add_argument("--confirm-writers-idle", action="store_true")
    parser.add_argument("--confirm-store-id")
    parser.add_argument("--confirm-model-id")
    parser.add_argument("--confirm-plan", "--confirm-plan-checksum", dest="confirm_plan_checksum")
    parser.add_argument("--confirm-backups-completed", action="store_true")
    parser.add_argument("--backup-reference")
    parser.add_argument("--backup-evidence")
    parser.add_argument("--window-id")
    args = parser.parse_args(argv)
    if (
        not args.environment_id.strip()
        or not math.isfinite(args.max_fga_qps)
        or not 0 < args.max_fga_qps <= (20 if args.offline_maintenance else 5)
    ):
        parser.error("environment and QPS must be valid")
    if args.offline_maintenance and not args.apply:
        parser.error("--offline-maintenance requires --apply and stopped writers")
    if not 5 <= args.relation_read_timeout_seconds <= 300:
        parser.error("relation pagination timeout must be between 5 and 300 seconds")
    if args.department_id and len(args.department_id) > 1000:
        parser.error("at most 1000 pilot IDs; use --scan-departments for the full tenant")
    if args.plan_file and not args.apply:
        parser.error("--plan-file requires --apply; otherwise use a fresh dry-run")
    if args.apply:
        if not all(
            (
                args.plan_file,
                args.confirm_writers_idle,
                args.confirm_plan_checksum,
                args.confirm_backups_completed or args.backup_evidence,
                args.window_id and args.window_id.strip(),
            )
        ):
            parser.error("apply requires the approved batch plan, backup, window, drain and exact confirmations")
    if not args.department_id and not args.plan_file:
        args.scan_departments = True
    return args


def plan_summary(plan):
    counts = {}
    for row in plan["entries"]:
        label = (
            "BLOCKED"
            if row["status"] == "BLOCKED"
            else "REPAIRABLE_AFTER_DEPENDENCIES"
            if row["dependencies"]
            else row["preview"]["classification"]
        )
        counts[label] = counts.get(label, 0) + 1
    return {
        "complete": plan["complete"],
        "all_repairable": plan["all_repairable"],
        "counts": counts,
        "plan_checksum": plan["plan_checksum"],
        "execution_order": plan["execution_order"],
        "coverage": plan["scope"],
        "environment_fingerprint": checksum(plan["environment"]),
        "store_id": plan["environment"]["store_id"],
        "model_id": plan["environment"]["model_id"],
    }


async def execute(args):
    from bisheng.core.database.query_statistics import query_statistics

    with query_statistics() as statistics:
        return await _execute(args, statistics)


async def _execute(args, statistics):
    audit = ProductionRepairAudit(args.output_dir)
    runtime, iam = None, None
    started = time.monotonic()
    try:
        iam = IamDepartmentLookup.from_file(args.iam_config) if args.iam_config else None
        evidence = backup_evidence(args.backup_evidence) if args.apply and args.backup_evidence else None
        await initialize_app_context(settings, context_names=("database", "redis") if args.apply else ("database",))
        runtime = DepartmentBatchRuntime(
            args.environment_id,
            args.max_fga_qps,
            iam_lookup=iam,
            backup_evidence=evidence,
            window_id=args.window_id,
            scan_timeout=args.scan_timeout_seconds,
            relation_read_timeout=args.relation_read_timeout_seconds,
            offline_maintenance=args.offline_maintenance,
            writers_idle=args.confirm_writers_idle,
        )
        await runtime.initialize()
        with tenant_scope(args.tenant_id):
            await runtime.ledger.check_existing_schema()
            environment = await runtime.environment()
            if args.apply and evidence is None:
                evidence = {
                    "environment_fingerprint": checksum(environment),
                    "backups_completed": True,
                    "backup_reference": args.backup_reference,
                }
                runtime.backup_evidence = evidence
            audit.context = {"environment_id": args.environment_id, "environment_fingerprint": checksum(environment)}
            audit.emit(
                "run_started", apply=args.apply, tenant_id=args.tenant_id, offline_maintenance=args.offline_maintenance
            )
            application = DepartmentBatchRepairApplication(runtime)
            if args.apply:
                if (
                    (args.confirm_store_id is not None and args.confirm_store_id != environment["store_id"])
                    or (args.confirm_model_id is not None and args.confirm_model_id != environment["model_id"])
                    or evidence["environment_fingerprint"] != checksum(environment)
                ):
                    raise RecoveryBlockedError("BATCH_CONFIRMED_ENVIRONMENT_OR_BACKUP_MISMATCH")
                if not await runtime.fga.ready():
                    raise RecoveryRuntimeError("CONSISTENCY_MARKER_NOT_READY")
                plan = private_batch_plan(args.plan_file, audit.path, args.confirm_plan_checksum)
                if plan["scope"]["tenant_id"] != args.tenant_id or plan["environment"] != environment:
                    raise RecoveryBlockedError("BATCH_PLAN_TENANT_OR_ENVIRONMENT_MISMATCH")
                async with asyncio.timeout(args.execution_timeout_seconds):
                    result = await application.apply(plan, audit, max_repairs=args.max_repairs)
            else:
                async with asyncio.timeout(args.scan_timeout_seconds):
                    plan = await application.scan(
                        audit, max_items=args.max_plan_items, requested_ids=args.department_id
                    )
                write_batch_plan(audit.path / "plan.jsonl", plan)
                result = plan_summary(plan)
            result.update(
                **statistics.summary(),
                fga_request_interval_lower_bound_seconds=round(
                    max(0, runtime.limiter.calls - 1) * runtime.limiter.interval, 3
                ),
                elapsed_seconds=round(time.monotonic() - started, 3),
                iam_requests=iam.calls if iam else 0,
                write_path_unmeasured=not args.apply,
                timing_note="dry-run only measures reads; all_repairable is not a duration guarantee",
                fga_requests=runtime.limiter.calls,
            )
            audit.emit("apply_summary" if args.apply else "scan_summary", **result)
            print(json.dumps(result, sort_keys=True))
            if not result["complete"]:
                return 5
            return 0 if args.apply or result["all_repairable"] else 3
    except RecoveryBlockedError as exc:
        audit.emit("batch_blocked", complete=False, reason=str(exc))
        print(json.dumps({"complete": False, "reason": str(exc)}))
        return 3
    except BaseException as exc:
        audit.emit(
            "batch_failed",
            complete=False,
            reason=str(exc) if isinstance(exc, RecoveryRuntimeError) else type(exc).__name__,
        )
        raise
    finally:
        try:
            try:
                if runtime is not None:
                    await runtime.client.close()
            finally:
                if iam is not None:
                    await iam.close()
        finally:
            try:
                await close_app_context()
            finally:
                audit.close()


def main(argv=None):
    args = parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (Exception, asyncio.CancelledError) as exc:
        print(f"DEPARTMENT_BATCH_FAILED {type(exc).__name__}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
