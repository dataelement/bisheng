#!/usr/bin/env python3
"""Audit or delete stale F048 public_reader tuples for knowledge spaces.

Public knowledge-space discovery is a square-listing business predicate, not a
permission grant. Older builds wrote ``user:* public_reader
knowledge_space:<id>`` tuples; the hotfix authorization model ignores those
tuples, and this script physically removes the stale Store data.

Run from ``src/backend`` with the live service config. The default is dry-run:

    PYTHONPATH=./ .venv/bin/python scripts/cleanup_f048_public_reader_tuples.py

Apply requires copying both ``store_id`` and ``cleanup_checksum`` from an
immediately preceding dry-run:

    PYTHONPATH=./ .venv/bin/python scripts/cleanup_f048_public_reader_tuples.py \
      --apply \
      --confirm-store-id <store-id> \
      --confirm-cleanup-checksum <cleanup-checksum>
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import traceback

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import (  # noqa: E402
    app_context,
    close_app_context,
    initialize_app_context,
)
from bisheng.core.openfga.client import OPENFGA_WRITE_TUPLE_LIMIT  # noqa: E402

EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_RUNTIME_ERROR = 4


class CleanupBlockedError(RuntimeError):
    """Operator confirmation or runtime state blocked cleanup."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="Delete the audited stale tuples")
    parser.add_argument(
        "--confirm-store-id",
        default=None,
        help="Required with --apply and must equal the live OpenFGA Store ID",
    )
    parser.add_argument(
        "--confirm-cleanup-checksum",
        default=None,
        help="Required with --apply and must equal the dry-run cleanup_checksum",
    )
    parser.add_argument(
        "--object",
        dest="objects",
        action="append",
        default=[],
        help="Optional exact object key to inspect, e.g. knowledge_space:4166. Repeatable.",
    )
    args = parser.parse_args(argv)
    if args.apply:
        if not args.confirm_store_id:
            parser.error("--apply requires --confirm-store-id")
        if not args.confirm_cleanup_checksum:
            parser.error("--apply requires --confirm-cleanup-checksum")
    return args


def _is_target_tuple(row: dict[str, str]) -> bool:
    return (
        row.get("user") == "user:*"
        and row.get("relation") == "public_reader"
        and str(row.get("object", "")).startswith("knowledge_space:")
    )


def _tuple_identity(row: dict[str, str]) -> str:
    return f'{row["user"]}|{row["relation"]}|{row["object"]}'


def _checksum(rows: list[dict[str, str]]) -> str:
    payload = "\n".join(sorted(_tuple_identity(row) for row in rows))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _load_candidates(client, objects: list[str]) -> list[dict[str, str]]:
    if objects:
        candidates: list[dict[str, str]] = []
        for object_key in objects:
            if not object_key.startswith("knowledge_space:"):
                raise CleanupBlockedError(f"Unsupported object filter: {object_key}")
            candidates.extend(
                await client.read_tuples(
                    user="user:*",
                    relation="public_reader",
                    object=object_key,
                    consistency="HIGHER_CONSISTENCY",
                )
            )
    else:
        candidates = await client.read_tuples(consistency="HIGHER_CONSISTENCY")
    return sorted(
        (row for row in candidates if _is_target_tuple(row)),
        key=_tuple_identity,
    )


async def run(args: argparse.Namespace) -> int:
    await initialize_app_context(settings, instance_role="script")
    client = await app_context.async_get_instance("openfga")

    rows = await _load_candidates(client, args.objects)
    cleanup_checksum = _checksum(rows)

    if args.apply:
        if args.confirm_store_id != client.store_id:
            raise CleanupBlockedError(
                f"Store confirmation mismatch: live={client.store_id} provided={args.confirm_store_id}"
            )
        if args.confirm_cleanup_checksum != cleanup_checksum:
            raise CleanupBlockedError(
                "Cleanup checksum mismatch; rerun dry-run and confirm the current tuple set"
            )
        for offset in range(0, len(rows), OPENFGA_WRITE_TUPLE_LIMIT):
            await client.write_tuples(deletes=rows[offset : offset + OPENFGA_WRITE_TUPLE_LIMIT])

    remaining = []
    if args.apply and rows:
        remaining = await _load_candidates(client, args.objects)

    report = {
        "mode": "apply" if args.apply else "dry-run",
        "status": "ok",
        "store_id": client.store_id,
        "model_id": client.model_id,
        "scoped_objects": args.objects,
        "stale_tuple_count": len(rows),
        "cleanup_checksum": cleanup_checksum,
        "deleted_count": len(rows) if args.apply else 0,
        "remaining_count": len(remaining),
        "tuples": rows,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


async def _main(args: argparse.Namespace) -> int:
    try:
        return await run(args)
    except CleanupBlockedError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return EXIT_BLOCKED
    except Exception as exc:
        traceback.print_exc()
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return EXIT_RUNTIME_ERROR
    finally:
        await close_app_context()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(parse_args())))
