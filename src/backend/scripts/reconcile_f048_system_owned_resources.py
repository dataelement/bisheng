#!/usr/bin/env python3
"""Audit or repair missing F048 projections for canonical system resources.

The default is dry-run. Apply creates missing preset-tool projections through
the online F048 facade so the durable ledger, SQL mirrors, and OpenFGA tuples
stay consistent. Preset dashboards are user-owned examples and are deliberately
outside this system-resource reconciler.

Run from ``src/backend`` with the live config:

    PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_system_owned_resources.py
    PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_system_owned_resources.py \
      --apply --confirm-store-id <store-id> --operator-id <user-id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from dataclasses import asdict

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.api.services.f048_system_resource_bootstrap import (  # noqa: E402
    load_system_owned_resource_inventory,
)
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import (  # noqa: E402
    app_context,
    close_app_context,
    initialize_app_context,
)
from bisheng.permission.application.runtime import build_f048_permission_runtime  # noqa: E402
from bisheng.permission.application.system_resource_reconcile import (  # noqa: E402
    reconcile_system_owned_resources,
)

EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_RUNTIME_ERROR = 4


class SystemResourceReconcileBlockedError(RuntimeError):
    """A business predicate or operator confirmation blocked reconciliation."""


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="Apply the audited repair")
    parser.add_argument(
        "--confirm-store-id",
        default=None,
        help="Required with --apply and must equal the live OpenFGA Store ID",
    )
    parser.add_argument(
        "--operator-id",
        type=_positive_int,
        default=1,
        help="Positive audit operator ID recorded in projection operations (default: 1)",
    )
    args = parser.parse_args(argv)
    if args.apply and not args.confirm_store_id:
        parser.error("--apply requires --confirm-store-id")
    return args


async def run(args: argparse.Namespace) -> int:
    await initialize_app_context(settings, instance_role="script")
    manager = app_context.get_context("openfga")
    client = await manager.async_get_instance()
    if args.apply and args.confirm_store_id != client.store_id:
        raise SystemResourceReconcileBlockedError(
            f"Store confirmation mismatch: live={client.store_id} provided={args.confirm_store_id}"
        )
    components = await build_f048_permission_runtime(client)
    await components.marker.wait_until_ready(
        timeout_seconds=float(settings.openfga.recent_consistency_window_seconds) + 5.0,
    )
    inventory = await load_system_owned_resource_inventory()
    resources = inventory.resources
    invalid = inventory.invalid
    if invalid:
        details = ", ".join(f"{item.object_key} ({item.reason})" for item in invalid)
        if args.apply:
            raise SystemResourceReconcileBlockedError(f"Invalid system-owned resources: {details}")
    report = await reconcile_system_owned_resources(
        components.facade,
        resources,
        apply=args.apply,
        operator_id=args.operator_id,
    )
    payload = {
        "mode": report.mode,
        "store_id": client.store_id,
        "model_id": client.model_id,
        "selected_resource_types": ["tool"],
        "resource_count": len(resources),
        "missing_count": report.missing_count,
        "blocked_count": report.blocked_count,
        "current_count": report.current_count,
        "invalid": [asdict(item) for item in invalid],
        "before": [asdict(item) for item in report.before],
        "after": [asdict(item) for item in report.after],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return EXIT_OK if not invalid else EXIT_BLOCKED


async def _main(args: argparse.Namespace) -> int:
    try:
        return await run(args)
    except SystemResourceReconcileBlockedError as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return EXIT_BLOCKED
    except Exception as exc:
        traceback.print_exc()
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return EXIT_RUNTIME_ERROR
    finally:
        await close_app_context()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(parse_args())))
