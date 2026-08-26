"""Run the one forward-only F048 permission data migration.

Run from ``src/backend`` with the same ``config`` environment value as the
started backend container while its automatic F048 migration gate is active:

    python scripts/migrate_f048_permission_data.py migrate \
      --apply
    python scripts/migrate_f048_permission_data.py migrate \
      --run-id <id> --apply
    python scripts/migrate_f048_permission_data.py reset-source \
      --run-id <id> --apply
    python scripts/migrate_f048_permission_data.py verify --run-id <id>

``--apply`` confirms a formal migration or pre-target source reset. There is no
preview, cleanup, or rollback command.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.errcode.permission import (  # noqa: E402
    PermissionMigrationBlockedError,
)
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import (  # noqa: E402
    close_app_context,
    initialize_app_context,
)

EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_RUNTIME_ERROR = 4


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser(
        "migrate",
        help="Start or resume the formal forward-only migration",
    )
    migrate.add_argument(
        "--apply",
        action="store_true",
        required=True,
        help="Required confirmation for the formal data migration write",
    )
    migrate.add_argument(
        "--lock-token",
        default=None,
        help="Operator/process token used by the durable SQL lease",
    )
    migrate.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="Existing formal run ID used for crash-safe forward resume",
    )

    reset_source = subparsers.add_parser(
        "reset-source",
        help="Discard one pre-target frozen source before a fresh scan",
    )
    reset_source.add_argument("--run-id", type=int, required=True)
    reset_source.add_argument(
        "--apply",
        action="store_true",
        required=True,
        help="Required confirmation for discarding the frozen source snapshot",
    )
    reset_source.add_argument(
        "--lock-token",
        default=None,
        help="Operator/process token used by the durable SQL lease",
    )

    verify = subparsers.add_parser(
        "verify",
        help="Run D4 verification for an existing formal run",
    )
    verify.add_argument("--run-id", type=int, required=True)
    return parser.parse_args(argv)


async def _runtime_factory(*, run_id: int | None = None):
    from scripts.f048_migration_runtime import (
        build_f048_migration_runtime,
    )

    return await build_f048_migration_runtime(settings, run_id=run_id)


def _migration_context_settings(live_settings: Any) -> Any:
    """Disable the online F048 manager while reading the predecessor model.

    The formal migration owns explicit source/target ``FGAClient`` instances.
    Initializing the normal production ``FGAManager`` here would reject the
    predecessor model because online startup only accepts the new F048 pin.
    """

    openfga = getattr(live_settings, "openfga", None)
    copy_settings = getattr(live_settings, "model_copy", None)
    copy_openfga = getattr(openfga, "model_copy", None)
    if not callable(copy_settings) or not callable(copy_openfga):
        return live_settings
    migration_openfga = copy_openfga(update={"enabled": False})
    return copy_settings(update={"openfga": migration_openfga})


async def execute(
    args: argparse.Namespace,
    *,
    runtime_factory: Callable[..., Any] = _runtime_factory,
    initialize_context: Callable[..., Awaitable[None]] = initialize_app_context,
    close_context: Callable[[], Awaitable[None]] = close_app_context,
    live_settings: Any = settings,
) -> int:
    """Initialize the live app context, execute one command, and always close."""

    runtime = None
    await initialize_context(config=_migration_context_settings(live_settings))
    try:
        runtime = runtime_factory(run_id=args.run_id)
        if isinstance(runtime, Awaitable):
            runtime = await runtime
        if args.command == "migrate":
            result = await runtime.coordinator.migrate(
                expected_store_id=runtime.source_client.store_id,
                lock_token=args.lock_token or uuid4().hex,
                run_id=args.run_id,
            )
            print(
                "F048 migration "
                f"run={result.run_id} "
                f"phase={result.phase} "
                f"store={result.store_id} "
                f"source_model={result.source_model_id} "
                f"target_model={result.target_model_id} "
                f"source_checksum={result.source_checksum} "
                f"target_checksum={result.target_checksum}"
            )
            return EXIT_OK
        if args.command == "reset-source":
            run = await runtime.coordinator.reset_source(
                expected_store_id=runtime.source_client.store_id,
                lock_token=args.lock_token or uuid4().hex,
                run_id=args.run_id,
            )
            print(
                "F048 migration source reset "
                f"run={run.id} phase={run.phase} status={run.status} "
                f"checkpoint={run.checkpoint}"
            )
            return EXIT_OK
        if args.command == "verify":
            run = await runtime.verifier.verify(run_id=args.run_id)
            print(f"F048 migration run={run.id} phase={run.phase}")
            return EXIT_OK
        raise ValueError(f"unsupported command: {args.command}")
    finally:
        if runtime is not None:
            close_runtime = getattr(runtime, "aclose", None)
            if close_runtime is not None:
                await close_runtime()
        await close_context()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except PermissionMigrationBlockedError as exc:
        print(f"F048 migration blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except Exception:
        # Preserve the traceback for operators and return a distinct exit code.
        import traceback

        traceback.print_exc()
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main())
