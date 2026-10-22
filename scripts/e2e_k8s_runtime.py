#!/usr/bin/env python3
"""Run staged F059 journeys through the real platform APIs.

See features/v3.0.0/059-k8s-runtime-backend/e2e-checklist.md for environment,
fixture schema, permissions and operator-driven fault checkpoints. This tool
never contacts the Kubernetes API or injects a cluster fault.
"""

from __future__ import annotations

import argparse
import asyncio
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
    return command


async def run(args):
    import httpx

    from test.e2e.helpers.vibe_runtime import (
        EvidenceJournal,
        LiveVibeSuite,
        SuiteSettings,
    )

    settings = SuiteSettings.from_env()
    journal = EvidenceJournal(args.evidence, tenant_code=settings.tenant_code)
    async with httpx.AsyncClient(
        timeout=75, trust_env=False, follow_redirects=False
    ) as client:
        suite = LiveVibeSuite(settings, journal, client)
        await suite.authenticate()
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
        asyncio.run(run(args))
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
    print(f"F059 {args.stage}: PASS; evidence={args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
