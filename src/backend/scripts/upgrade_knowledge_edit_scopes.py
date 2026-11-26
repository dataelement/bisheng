#!/usr/bin/env python3
"""Publish the missing file/folder edit scopes on an existing F048 environment.

Run from src/backend with the live service's config environment variable:
  python scripts/upgrade_knowledge_edit_scopes.py plan
  python scripts/upgrade_knowledge_edit_scopes.py apply --plan-digest DIGEST --operator-id ID --idempotency-key KEY
  python scripts/upgrade_knowledge_edit_scopes.py resume --draft-id ID --operator-id ID --idempotency-key KEY
  python scripts/upgrade_knowledge_edit_scopes.py verify

Default: read-only plan. apply/resume reuse the original Catalog ledger, fence,
tuple staging, atomic active-pointer switch, and forward-only reconciliation.
This command never writes a new OpenFGA model or changes resource Grants.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.errcode.base import BaseErrorCode  # noqa: E402


@asynccontextmanager
async def runtime(*, write=False):
    """Own only the needed clients, including failed initialization cleanup."""
    from bisheng.common.services.config_service import settings
    from bisheng.core.cache.redis_manager import RedisManager
    from bisheng.core.context.manager import app_context
    from bisheng.core.database.manager import DatabaseManager
    from bisheng.core.openfga.authorization_model_f048 import (
        authorization_model_checksum,
        build_authorization_model_f048,
    )
    from bisheng.core.openfga.client import FGAClient
    from bisheng.core.openfga.discovery import discover_openfga_runtime
    from bisheng.permission.application.catalog_api import OpenFGACatalogProjector, SqlCatalogState
    from bisheng.permission.application.knowledge_edit_scope_upgrade import KnowledgeEditScopeUpgrade
    from bisheng.permission.application.sql_runtime import RedisConsistencyMarker

    settings.openfga.validate_production_runtime()
    if not settings.openfga.enabled:
        raise ValueError("OpenFGA must be enabled")
    async with AsyncExitStack() as stack:
        database = DatabaseManager(
            database_url=settings.database_url, engine_config=settings.database_pool.as_engine_kwargs()
        )
        stack.push_async_callback(database.async_close)
        app_context.register_context(database)
        await app_context.async_get_instance(DatabaseManager.name)
        state = SqlCatalogState()
        current = await state.current_release()
        authorization = await state.authorization_release(current.id)
        expected = authorization_model_checksum(build_authorization_model_f048())
        if authorization.status != "ACTIVE" or authorization.model_checksum != expected:
            raise ValueError("Pinned authorization model differs from this code; complete its own upgrade first")
        actual = await discover_openfga_runtime(
            settings.openfga,
            expected_model=build_authorization_model_f048(),
            allow_bootstrap=False,
            required_store_id=authorization.store_id,
            required_model_id=authorization.model_id,
        )
        if actual.model_checksum != expected:
            raise ValueError("Physical authorization model checksum differs from the SQL pin")
        client = FGAClient(
            api_url=settings.openfga.api_url,
            store_id=authorization.store_id,
            model_id=authorization.model_id,
            timeout=settings.openfga.timeout,
        )
        stack.push_async_callback(client.close)
        if write:
            redis = RedisManager(redis_url=settings.redis_url)
            stack.push_async_callback(redis.async_close)
            app_context.register_context(redis)
            await app_context.async_get_instance(RedisManager.name)
        projector = OpenFGACatalogProjector(client=client, marker=RedisConsistencyMarker())
        yield KnowledgeEditScopeUpgrade(state=state, projector=projector)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("plan", "apply", "resume", "verify"), nargs="?", default="plan")
    result.add_argument("--plan-digest")
    result.add_argument("--operator-id", type=int, help="Original audit operator user ID; does not impersonate a login")
    result.add_argument("--idempotency-key", help="Keep this key unchanged when resuming the same upgrade")
    result.add_argument("--draft-id", type=int)
    return result


async def run(args):
    async with runtime(write=args.command in {"apply", "resume"}) as upgrade:
        if args.command == "plan":
            return await upgrade.plan()
        if args.command == "verify":
            return await upgrade.verify()
        common = {"operator_id": args.operator_id, "idempotency_key": args.idempotency_key}
        if args.command == "resume":
            return await upgrade.resume(draft_id=args.draft_id, **common)
        return await upgrade.apply(plan_digest=args.plan_digest, **common)


def main():
    command = parser()
    args = command.parse_args()
    if args.command in {"apply", "resume"}:
        if not args.operator_id or args.operator_id <= 0 or not args.idempotency_key:
            command.error("apply/resume require a positive --operator-id and --idempotency-key")
        if args.command == "apply" and not args.plan_digest:
            command.error("apply requires the --plan-digest returned by plan")
        if args.command == "resume" and (not args.draft_id or args.draft_id <= 0):
            command.error("resume requires a positive --draft-id")
    try:
        result = asyncio.run(run(args))
    except BaseErrorCode as error:
        print(json.dumps({"event": "blocked", "code": error.Code, "message": str(error)}, ensure_ascii=False))
        return 2
    except Exception:
        from loguru import logger

        logger.exception("File/folder edit scope upgrade failed")
        return 1
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
