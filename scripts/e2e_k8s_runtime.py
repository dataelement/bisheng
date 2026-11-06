#!/usr/bin/env python3
"""Run staged F059 journeys through the real platform APIs.

See features/v3.0.0/059-k8s-runtime-backend/e2e-checklist.md for environment,
fixture schema, permissions and operator-driven fault checkpoints. This tool
never contacts the Kubernetes API or injects a cluster fault.
F059_E2E_CA_FILE optionally adds a public PEM CA for both HTTPS and WSS;
certificate and hostname verification always remain enabled.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "src" / "backend"
sys.path.insert(0, str(BACKEND))


def parser():
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--stage",
        required=True,
        choices=[
            "installation",
            "platform",
            "observe",
            "cycle",
            "fault-upgrade",
            "fault-operation",
            "cleanup",
            "all",
        ],
    )
    command.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="Private resumable journal; contains IDs, never credentials",
    )
    command.add_argument(
        "--event", choices=["manager-restart", "runtime-upgrade", "app-restart"]
    )
    command.add_argument("--checkpoint", choices=["before", "after"])
    command.add_argument("--operation-action", choices=["observe", "cancel", "restore"])
    command.add_argument(
        "--slug", help="Exact configured and journaled e2e-f059- application"
    )
    command.add_argument(
        "--operation-id", help="Exact public runtime operation ID; observe/cancel only"
    )
    command.add_argument(
        "--snapshot-id", help="Confirmed snapshot belonging to the selected application"
    )
    command.add_argument("--expected-generation", type=int)
    command.add_argument(
        "--acknowledge-data-loss",
        action="store_true",
        help="Explicit owner intent for restore",
    )
    command.add_argument(
        "--expected-rows-file",
        type=Path,
        help="Private JSON containing the expected rows API data",
    )
    command.add_argument(
        "--expect-status",
        choices=["pending", "running", "completed", "failed", "cancelled", "timed_out"],
    )
    command.add_argument("--expect-reason", help="Exact runtime failure reason")
    command.add_argument(
        "--expect-failure-stage", help="Exact failed_stage in runtime failure"
    )
    command.add_argument(
        "--expect-cleanup", choices=["pending", "complete", "storage_pending"]
    )
    return command


def fault_intent(args):
    from test.e2e.helpers.vibe_runtime import validate_slug

    if not args.slug or args.operation_action not in {"observe", "cancel", "restore"}:
        raise ValueError("fault-operation requires --slug and --operation-action")
    validate_slug(args.slug)
    expected_rows = None
    if args.operation_action == "restore":
        if (
            not args.acknowledge_data_loss
            or not args.snapshot_id
            or args.expected_generation is None
            or args.expected_generation < 1
            or args.operation_id
            or not args.expected_rows_file
            or any(
                [
                    args.expect_status,
                    args.expect_reason,
                    args.expect_failure_stage,
                    args.expect_cleanup,
                ]
            )
        ):
            raise ValueError(
                "restore requires one snapshot, generation, explicit acknowledgement and expected rows"
            )
        try:
            path = args.expected_rows_file
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError()
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream:
                information = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(information.st_mode)
                    or not 0 < information.st_size <= 1024 * 1024
                ):
                    raise ValueError()
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError()
            expected_rows = json.loads(raw)
            if not isinstance(expected_rows, dict):
                raise ValueError()
        except (OSError, ValueError):
            raise ValueError(
                "expected rows must be a bounded regular non-symlink JSON object file"
            ) from None
    elif (
        not args.operation_id
        or args.snapshot_id
        or args.expected_generation is not None
        or args.acknowledge_data_loss
        or args.expected_rows_file
        or (args.operation_action == "observe" and not args.expect_status)
        or (
            args.operation_action == "cancel"
            and any(
                [
                    args.expect_status,
                    args.expect_reason,
                    args.expect_failure_stage,
                    args.expect_cleanup,
                ]
            )
        )
    ):
        raise ValueError(
            "observe/cancel requires one operation ID; restore intent is forbidden"
        )
    return {
        "action": args.operation_action,
        "operation_id": args.operation_id,
        "snapshot_id": args.snapshot_id,
        "expected_generation": args.expected_generation,
        "acknowledge_data_loss": args.acknowledge_data_loss,
        "expected_rows": expected_rows,
        "expected_status": args.expect_status,
        "expected_reason": args.expect_reason,
        "expected_failure_stage": args.expect_failure_stage,
        "expected_cleanup": args.expect_cleanup,
    }


async def run(args):
    intent = fault_intent(args) if args.stage == "fault-operation" else None
    import httpx
    from test.e2e.helpers.vibe_runtime import (
        EvidenceJournal,
        LiveVibeSuite,
        SuiteSettings,
    )

    settings = SuiteSettings.from_env()
    journal = EvidenceJournal(args.evidence, tenant_code=settings.tenant_code)
    async with httpx.AsyncClient(
        timeout=75, trust_env=False, follow_redirects=False, verify=settings.ssl_context
    ) as client:
        suite = LiveVibeSuite(settings, journal, client)
        await suite.authenticate()
        if args.stage == "fault-operation":
            return await suite.fault_operation(args.slug, **intent)
        if args.stage == "fault-upgrade":
            if not args.event or not args.checkpoint:
                raise ValueError("fault-upgrade requires --event and --checkpoint")
            await suite.checkpoint(args.event, verify=args.checkpoint == "after")
            return
        if args.stage == "cleanup":
            await suite.cleanup()
            return
        if args.stage in {"installation", "all", "platform"}:
            await suite.installation()
        if args.stage == "installation":
            return
        if args.stage in {"all", "platform"}:
            await suite.cleanup()
        try:
            for scenario in settings.scenarios:
                if args.stage in {"all", "platform"}:
                    await suite.deploy(scenario)
                if scenario.expected_failure_code is not None:
                    continue
                if args.stage in {"all", "platform", "observe"}:
                    await suite.observe(scenario)
                if args.stage in {"all", "platform", "cycle"}:
                    await suite.cycle(scenario)
                if args.stage in {"all", "platform"} and scenario.update:
                    await suite.deploy(scenario, update=True)
                    await suite.observe(scenario)
        finally:
            if args.stage == "all":
                await suite.cleanup()


def main():
    args = parser().parse_args()
    try:
        result = asyncio.run(run(args))
    except (AssertionError, ValueError, OSError) as exc:
        # Assertion text is deliberately authored by the harness. Never dump an
        # HTTP exception/response or environment: either may contain a secret.
        print(
            f"F059 {args.stage}: FAILED ({type(exc).__name__}); inspect private platform diagnostics",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            f"F059 {args.stage}: ERROR ({type(exc).__name__}); credentials and response bodies omitted",
            file=sys.stderr,
        )
        return 2
    if isinstance(result, dict) and result.get("protection_link_verified") is False:
        print(
            f"F059 {args.stage}: PARTIAL; restore rows verified; protection snapshot association needs operator evidence; evidence={args.evidence}"
        )
        return 0
    print(f"F059 {args.stage}: PASS; evidence={args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
