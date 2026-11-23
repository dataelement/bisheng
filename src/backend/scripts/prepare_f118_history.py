# ruff: noqa: E402
"""Prepare historical depth/permission mirrors before freezing F118 M2.

Run from src/backend with the service's config and ALL writers/consumers stopped.
Preview saves a private, checksummed selected-row backup/plan (no SQL/FGA writes)::

    python scripts/prepare_f118_history.py --plan /secure/f118-history.json
    python scripts/prepare_f118_history.py --plan /secure/f118-history.json --apply --operator-id 1

Apply/resume reads the same plan. Repairs parent ownership/depth, cleans proven
orphan metadata and its backed-up file payloads, and purges deleted resources'
derived permissions. Keeps audit, roles and live index bindings. Physical
cleanup deletes only identified orphan objects/rows, never whole stores. Unknown
ownership or unavailable physical identity is reported. Run BEFORE a new M2
freeze; an active frozen migration is rejected. Unreachable rootless history
and old embedding names are preserved with warnings and formal M2 proofs.
Proven empty successful NORMAL-file permissions initialize only INHERIT through
the native ledger; intact FAILED_CLOSED GRANT_MUTATION operations forward-recover
their original intent/fence. A historical delete whose saved snapshot already
lacks one permission_enabled marker can recover its own frozen projection.
Unknown ownership/authorization, changed evidence and failed native recovery stop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.knowledge.domain.repositories.unification_history_repository import (
    _ModeFact as _ModeFact,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    _ModeRows as _ModeRows,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    apply as apply,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    blocked as blocked,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    business_models as business_models,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    canonical as canonical,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    capture as capture,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    checksum as checksum,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    downstream as downstream,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    fga_blocked_modes as fga_blocked_modes,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    folder_path as folder_path,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    global_session as global_session,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    hard_missing as hard_missing,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    hard_missing_batch as hard_missing_batch,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    level_scope as level_scope,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    load_plan as load_plan,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    mirrors as mirrors,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    mirrors_batch as mirrors_batch,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    project_history_delete as project_history_delete,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    read_pin as read_pin,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    record_event as record_event,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    require_chain as require_chain,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    save_plan as save_plan,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    stable_mirrors as stable_mirrors,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    target_for as target_for,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    unfrozen as unfrozen,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    valid_chain as valid_chain,
)
from bisheng.knowledge.domain.repositories.unification_history_repository import (
    warning_summary as warning_summary,
)
from bisheng.knowledge.domain.repositories.unification_history_snapshot import snapshot_scope


@snapshot_scope
async def arun(args):
    from contextlib import AsyncExitStack

    from bisheng.common.services.config_service import settings
    from bisheng.core.cache.redis_manager import RedisManager
    from bisheng.core.context.manager import app_context
    from bisheng.core.database import get_async_db_session
    from bisheng.core.database.manager import DatabaseManager
    from bisheng.core.openfga.client import FGAClient
    from bisheng.core.openfga.discovery import discover_openfga_runtime
    from bisheng.permission.application.control_state import SqlPermissionControlState
    from bisheng.permission.application.runtime import F048PermissionRuntime
    from bisheng.permission.application.sql_runtime import build_sql_projection_runtime
    from bisheng.permission.domain.services.projection_service import ProjectionService

    # Own DB/Redis and a read-pinned FGA transport, like the formal F118 CLI;
    # never initialize storage/RAG clients that could change physical stores.
    async with AsyncExitStack() as stack:
        if (
            not settings.openfga.enabled
            or settings.openfga.force_write_model
            or settings.openfga.dual_model_mode
            or settings.openfga.legacy_model_id
        ):
            blocked("read_pinned_fga_configuration_required")
        database = DatabaseManager(
            database_url=settings.database_url, engine_config=settings.database_pool.as_engine_kwargs()
        )
        app_context.register_context(database)
        stack.push_async_callback(database.async_close)
        await app_context.async_get_instance(DatabaseManager.name)
        async with global_session(get_async_db_session) as session:
            pin = await read_pin(session)
        actual = await discover_openfga_runtime(
            settings.openfga,
            expected_model=None,
            allow_bootstrap=False,
            required_store_id=pin["store_id"],
            required_model_id=pin["model_id"],
        )
        if actual.model_checksum != pin["model_checksum"]:
            blocked("physical_pin_changed")
        client = FGAClient(
            api_url=settings.openfga.api_url,
            store_id=pin["store_id"],
            model_id=pin["model_id"],
            timeout=settings.openfga.timeout,
        )
        stack.push_async_callback(client.close)
        if not args.apply:
            if getattr(args, "delete_closures_only", False) or getattr(args, "projection_repairs_only", False):
                from scripts import f118_delete_closure

                closures, retained = await f118_delete_closure.capture(get_async_db_session, client, pin=pin)
                plan = {
                    "schema": 2,
                    "purpose": "f118-delete-closures",
                    "pin": pin,
                    "levels": [],
                    "parents": [],
                    "purges": [],
                    "blocked": [],
                    "initializations": [],
                    "recoveries": [],
                    "retained_evidence": [],
                    "business": {},
                    "delete_closures": closures,
                    "permission_delete_retained": retained,
                }
                if getattr(args, "projection_repairs_only", False):
                    from scripts import f118_empty_root
                    from scripts import f118_history_permissions as permissions

                    plan.update(
                        schema=4,
                        empty_root_initializations=await f118_empty_root.capture(get_async_db_session, client, pin),
                        purpose="f118-projection-repairs",
                        builtin_finalizations=await permissions.capture_builtin_finalizations(
                            get_async_db_session, client, pin
                        ),
                    )
                saved_checksum = save_plan(args.plan, plan)
                return {
                    "mode": "preview",
                    "plan": str(args.plan),
                    "sha256": saved_checksum,
                    "delete_closures": len(closures),
                    "permission_delete_retained": len(retained),
                    "empty_root_initializations": len(plan.get("empty_root_initializations", ())),
                    "builtin_finalizations": len(plan.get("builtin_finalizations", ())),
                    "validation_scope": "projection_repairs_only"
                    if getattr(args, "projection_repairs_only", False)
                    else "delete_closures_only",
                    "blocked": [],
                    "ready": False,
                }
            plan = await capture(get_async_db_session, client)
            if plan["business"]["physical"]:
                # Preserve selected SQL evidence even if physical inspection
                # fails. This candidate snapshot is not a completed apply plan.
                save_plan(args.plan.with_name(args.plan.name + ".candidates.json"), plan)
                from bisheng.knowledge.application.unification_minio import UnificationMinio
                from bisheng.knowledge.application.unification_physical import PhysicalInventoryReader
                from scripts.f118_history_physical import OrphanPayloads

                async with global_session(get_async_db_session) as session:
                    from scripts.f118_history_business import read

                    rows = (await read(session))["knowledgefile"]
                removing = {item["file"]["id"] for item in plan["business"]["physical"]}
                storage = await stack.enter_async_context(UnificationMinio.aopen(settings.get_minio_conf()))
                reader = await stack.enter_async_context(
                    PhysicalInventoryReader.aopen(settings.get_vectors_conf(), storage=storage)
                )
                await OrphanPayloads(
                    reader,
                    str(args.plan) + ".payloads",
                    environment=checksum(
                        canonical(
                            [
                                settings.get_vectors_conf().model_dump(mode="json"),
                                settings.get_minio_conf().model_dump(mode="json"),
                            ]
                        )
                    ),
                ).capture(
                    plan["business"]["physical"], surviving_files=[row for row in rows if row["id"] not in removing]
                )
            saved_checksum = save_plan(args.plan, plan)
            return {
                "mode": "preview",
                "plan": str(args.plan),
                "sha256": saved_checksum,
                **{key: len(plan[key]) for key in ("levels", "parents", "purges", "initializations", "recoveries")},
                "empty_root_initializations": len(plan.get("empty_root_initializations", ())),
                "builtin_finalizations": len(plan.get("builtin_finalizations", ())),
                "delete_closures": len(plan.get("delete_closures", ())),
                "permission_delete_retained": len(plan.get("permission_delete_retained", ())),
                "business_deletes": len(plan["business"]["deletes"]),
                "business_updates": len(plan["business"]["updates"]),
                "orphan_payloads": len(plan["business"]["physical"]),
                "blocked": plan["blocked"],
                "warnings": warning_summary(plan),
            }
        plan = load_plan(args.plan)
        if getattr(args, "delete_closures_only", False) and plan.get("purpose") != "f118-delete-closures":
            blocked("delete_closure_plan_purpose")
        if getattr(args, "projection_repairs_only", False) and plan.get("purpose") != "f118-projection-repairs":
            blocked("projection_repair_plan_purpose")
        if plan["pin"] != pin:
            blocked("backup_or_pin_changed")
        physical = None
        if plan.get("business", {}).get("physical"):
            from bisheng.knowledge.application.unification_minio import UnificationMinio
            from bisheng.knowledge.application.unification_physical import PhysicalInventoryReader
            from scripts.f118_history_physical import OrphanPayloads

            storage = await stack.enter_async_context(UnificationMinio.aopen(settings.get_minio_conf()))
            reader = await stack.enter_async_context(
                PhysicalInventoryReader.aopen(settings.get_vectors_conf(), storage=storage)
            )
            physical = OrphanPayloads(
                reader,
                str(args.plan) + ".payloads",
                environment=checksum(
                    canonical(
                        [
                            settings.get_vectors_conf().model_dump(mode="json"),
                            settings.get_minio_conf().model_dump(mode="json"),
                        ]
                    )
                ),
            )
        redis = RedisManager(redis_url=settings.redis_url)
        app_context.register_context(redis)
        stack.push_async_callback(redis.async_close)
        await app_context.async_get_instance(RedisManager.name)
        components = await build_sql_projection_runtime(client)

        class MaintenanceState(SqlPermissionControlState):
            async def current_catalog(self):
                async with global_session(get_async_db_session) as session:
                    current = await read_pin(session)
                if current != pin:
                    blocked("catalog_pin_changed")
                # No action/model reinterpretation before the new model is
                # published. This maintenance facade exposes no business check.
                return SimpleNamespace(**current)

        runtime = F048PermissionRuntime(
            client=client,
            state=MaintenanceState(),
            marker=components.marker,
            decision=None,
            projection=ProjectionService(
                **{
                    name: getattr(components, name)
                    for name in ("repository", "marker", "scope_guard", "fga", "finalizer")
                }
            ),
            sources=None,
            owner=None,
            grants=None,
            modes=None,
            explain=None,
        )
        return {
            "mode": "apply",
            "sha256": checksum(plan),
            **await apply(
                plan,
                sessions=get_async_db_session,
                client=client,
                runtime=runtime,
                operator_id=args.operator_id,
                physical=physical,
            ),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--operator-id", type=int)
    parser.add_argument(
        "--delete-closures-only",
        action="store_true",
        help="preview only deterministic residual delete-marker closures before M2; keep all payloads",
    )
    parser.add_argument(
        "--projection-repairs-only",
        action="store_true",
        help="preview native delete closure and AFTER-only builtin CREATE finalization before M2",
    )
    args = parser.parse_args(argv)
    if args.apply and (args.operator_id is None or args.operator_id <= 0):
        parser.error("--apply requires a positive --operator-id")
    try:
        if args.apply:
            record_event(args.plan, {"event": "apply_start", "operator_id": args.operator_id})
        result = asyncio.run(arun(args))
        if args.apply:
            record_event(args.plan, {"event": "apply_complete", "operator_id": args.operator_id, **result})
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        # Do not expose configuration/provider exception text or backup rows.
        failure = {
            "error_type": type(error).__name__,
            "reason": getattr(error, "kwargs", {}).get("reason") or "history_prepare_execution_failed",
            "resume_same_plan": True,
        }
        failure.update(
            {
                key: error.kwargs[key]
                for key in ("operation_id", "projection_status")
                if key in getattr(error, "kwargs", {})
            }
        )
        if args.apply:
            try:
                record_event(args.plan, {"event": "apply_failed", **failure})
            except OSError as journal_error:
                failure["event_journal_error"] = type(journal_error).__name__
        print(json.dumps(failure), file=sys.stderr)
        return 3
    return 2 if args.apply and result["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
