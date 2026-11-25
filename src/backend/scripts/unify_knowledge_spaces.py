"""Preview and apply the complete F118 knowledge-space migration.

From src/backend with the service's config: python scripts/unify_knowledge_spaces.py
--run-id maintenance-1 --environment production.
DBA backups are an operational prerequisite, not a script input or check.
Default --dry-run writes only private local reports/materials, with no SQL,
FGA, Redis or remote artifact writes. It checks historical repairs through
their read-only after view and the complete native migration planners.
Use the same --run-id with --apply --operator-id 7 to execute that exact plan;
repeat the same apply command to resume. This script never controls services.
An explicit --permissions-only apply stops after complete SQL/permission
publication. It does not backfill references or certify global Coverage Ready.
Historical depth/orphan preparation is included in the standard full flow.
"""

import argparse
import asyncio
import json
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _operator(value):
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("operator-id must be a positive integer") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("operator-id must be a positive integer")
    return result


def _descriptor(value):
    try:
        result = json.loads(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an immutable object_key/sha256 JSON descriptor") from error
    if type(result) is not dict or set(result) != {"object_key", "sha256"}:
        raise argparse.ArgumentTypeError("expected an immutable object_key/sha256 JSON descriptor")
    return result


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--run-id", required=True)
    result.add_argument("--writer-contract-version", default="f118-v1")
    result.add_argument("--environment", help="assert the unique CURRENT/ACTIVE environment; discovered when omitted")
    result.add_argument("--materials-dir", type=Path, help="private persistent preview materials directory")
    result.add_argument(
        "--backup-ref",
        type=_descriptor,
        help="legacy frozen descriptor assertion; omit to read the original Run metadata",
    )
    result.add_argument(
        "--schema-ref",
        type=_descriptor,
        help="legacy frozen descriptor assertion; omit to read the original Run metadata",
    )
    result.add_argument("--operator-id", type=_operator, default=0)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="complete read-only preflight (default)")
    mode.add_argument("--apply", action="store_true", help="execute the verified plan and resume the same Run")
    result.add_argument("--verify", action="store_true", help="strictly reverify an existing completed Run")
    result.add_argument(
        "--resume", action="store_true", help="require an existing frozen Run; never replace its baseline"
    )
    result.add_argument(
        "--permissions-only", action="store_true", help="apply SQL and permissions only; leave references unverified"
    )
    result.add_argument(
        "--register-references-only",
        action="store_true",
        help="reuse completed SQL/permissions; register references without full verification or Coverage",
    )
    return result


@asynccontextmanager
async def _runtime(args):
    from bisheng.common.services.config_service import settings
    from bisheng.core.cache.redis_manager import RedisManager
    from bisheng.core.context.manager import app_context
    from bisheng.core.database import get_async_db_session
    from bisheng.core.database.manager import DatabaseManager
    from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
    from bisheng.knowledge.application.unification_inventory import UnificationInventoryApplication
    from bisheng.knowledge.application.unification_minio import UnificationMinio
    from bisheng.permission.application.migration_read import PinnedMigrationPermissionReader

    # F118's frozen read-only inventory contract is a deliberate exception to
    # scripts' general initialize_app_context rule: that eager initializer
    # constructs MinioStorage and can create buckets/policies. Register only
    # the original DB/Redis managers with the service's exact settings; all
    # other clients below are the already-reviewed owned raw read adapters.
    owned = []
    try:
        database = DatabaseManager(
            database_url=settings.database_url, engine_config=settings.database_pool.as_engine_kwargs()
        )
        owned.append(database)
        app_context.register_context(database)
        redis = RedisManager(redis_url=settings.redis_url)
        owned.append(redis)
        app_context.register_context(redis)
        database_connection = await app_context.async_get_instance(DatabaseManager.name)
        await app_context.async_get_instance(RedisManager.name)
        async with UnificationMinio.aopen(settings.get_minio_conf()) as storage:
            store = UnificationArtifactStore(storage)

            @asynccontextmanager
            async def sharing(catalog):
                async with PinnedMigrationPermissionReader(settings.openfga, catalog) as reader:
                    yield reader

            @asynccontextmanager
            async def inventory(session):
                # Migration preserves SQL index bindings. ES/Milvus health,
                # schema and counts belong to the separate storage diagnosis.
                yield UnificationInventoryApplication(artifact_store=store, sharing_reader_factory=sharing)

            @asynccontextmanager
            async def history_runtime():
                from bisheng.knowledge.domain.repositories.unification_history_repository import (
                    global_session,
                    read_pin,
                )
                from bisheng.permission.application.migration_history import open_history_runtime

                async with global_session(get_async_db_session) as session:
                    pin = await read_pin(session)
                async with open_history_runtime(
                    settings,
                    pin=pin,
                    sessions=get_async_db_session,
                    apply=args.apply,
                    store=store,
                    sharing_reader_factory=sharing,
                ) as history:
                    yield history

            yield SimpleNamespace(
                store=store,
                sessions=get_async_db_session,
                inventory=inventory,
                engine=database_connection.async_engine,
                history=history_runtime,
                sharing_reader_factory=sharing,
            )
    finally:
        # Lazy acquisition does not mark ApplicationContext initialized, so
        # its global close helper intentionally skips these owned managers.
        for manager in reversed(owned):
            await manager.async_close()


async def _legacy_stage(args, *, application, frozen, inputs):
    """Execute only the explicitly requested compatibility stage."""
    if getattr(args, "register_references_only", False):
        from bisheng.knowledge.application.unification_registration import run_registration

        return await run_registration(application, apply=args.apply, **inputs, operator_id=args.operator_id)
    report = await application.arun_permissions(**inputs, operator_id=args.operator_id)
    return {
        "mode": "apply_permissions",
        "run_id": report.run_id,
        "writer_contract_version": report.writer_contract_version,
        "baseline_hash": report.baseline_hash,
        "plan_hash": report.plan_hash,
        "tenant_ids": list(frozen.tenant_ids),
        "permissions_complete": report.complete,
        "reference_backfill_executed": False,
        "ready": False,
        "invalid_manifest_ref": frozen.plan_ref,
    }


async def _legacy_arun(args, *, runtime_factory=_runtime):
    """Keep compatibility stage writers inside the unified native fence."""
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
    from bisheng.knowledge.application.unification_upgrade import UnificationUpgradeApplication
    from bisheng.knowledge.application.unification_upgrade_executor import UpgradeExecutor
    from bisheng.knowledge.domain.repositories.unification_executor_repository import UnificationExecutorRepository
    from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
    from bisheng.permission.domain.services.maintenance_guard import maintenance_guard

    identity = {name: getattr(args, name) for name in ("run_id", "writer_contract_version")}
    KnowledgeUnificationRunRepository._identity(**identity)
    if getattr(args, "verify", False):
        raise KnowledgeOperationPlanConflictError(reason="migration_cli_verify_conflicting_stage")
    registration = getattr(args, "register_references_only", False)
    if getattr(args, "permissions_only", False) and not args.apply:
        raise KnowledgeOperationPlanConflictError(reason="migration_cli_permissions_only_requires_apply")
    if registration and getattr(args, "permissions_only", False):
        raise KnowledgeOperationPlanConflictError(reason="migration_cli_conflicting_stages")
    if args.apply and (type(args.operator_id) is not int or args.operator_id <= 0):
        raise KnowledgeOperationPlanConflictError(reason="migration_cli_positive_operator_required")
    with tenant_execution_scope(1):
        async with runtime_factory(args) as runtime:
            with runtime.store.verified_reads():
                owner = UnificationUpgradeApplication(runtime, None)
                state = await owner._state(identity)
                frozen = state.frozen
                if frozen is None:
                    reason = (
                        "migration_cli_resume_requires_frozen_run"
                        if args.resume
                        else "migration_cli_legacy_apply_requires_frozen_run"
                        if args.apply
                        else "migration_cli_registration_requires_frozen_resume"
                    )
                    raise KnowledgeOperationPlanConflictError(reason=reason)
                if registration and args.apply and not args.resume:
                    raise KnowledgeOperationPlanConflictError(
                        reason="migration_cli_registration_requires_frozen_resume"
                    )
                if state.pending_intents:
                    raise KnowledgeOperationPlanConflictError(reason="migration_executor_recovery_required")
                environment, connection = await owner._environment(
                    args.environment, state=state, backup_ref=args.backup_ref, schema_ref=args.schema_ref
                )
                inputs = {
                    **identity,
                    "environment": environment,
                    "backup_ref": args.backup_ref,
                    "schema_ref": args.schema_ref,
                }
                readonly = UnificationSQLConversionApplication(
                    artifact_store=runtime.store, session_factory=runtime.sessions, read_only_resume=True
                )
                if not args.apply:
                    # Registration preview consumes native read ports only. It
                    # never acquires/bootstrap a control lock or executor token.
                    return await _legacy_stage(args, application=readonly, frozen=frozen, inputs=inputs)
                await owner._verify_actor(args.operator_id)

                async def admit():
                    current = await owner._state(identity)
                    if current != state:
                        raise KnowledgeOperationPlanConflictError(reason="migration_cli_run_changed_during_admission")
                    actual_environment, actual_connection = await owner._environment(
                        args.environment, state=current, backup_ref=args.backup_ref, schema_ref=args.schema_ref
                    )
                    if actual_environment != environment or actual_connection != connection:
                        raise KnowledgeOperationPlanConflictError(reason="migration_cli_environment_or_schema_changed")
                    await owner._verify_actor(args.operator_id)
                    report = await readonly.apreview_resume(
                        frozen=frozen,
                        inputs={name: inputs[name] for name in ("environment", "backup_ref", "schema_ref")},
                        operator_id=args.operator_id,
                    )
                    if not report["complete"]:
                        raise KnowledgeOperationPlanConflictError(reason="migration_cli_resume_preflight_incomplete")
                    if registration:
                        from bisheng.knowledge.application.unification_registration import run_registration

                        await run_registration(readonly, apply=False, **inputs, operator_id=args.operator_id)

                if getattr(
                    runtime, "executor_lock", None
                ) is None and not await UnificationExecutorRepository().ahas_control_seed(runtime.engine):
                    await admit()
                async with UpgradeExecutor.acquire(runtime, **identity) as executor:
                    await admit()
                    await executor.start(state.tenant_ids)
                    try:
                        with maintenance_guard(
                            transaction_guard=executor.permission_transaction_guard,
                            external_guard=executor,
                            global_tenants=state.tenant_ids,
                            identity=identity,
                        ):
                            application = UnificationSQLConversionApplication(
                                artifact_store=runtime.store,
                                session_factory=runtime.sessions,
                                transaction_guard=executor.transaction_guard,
                                external_guard=executor,
                            )
                            result = await _legacy_stage(args, application=application, frozen=frozen, inputs=inputs)
                        await executor.finish_attempt()
                        return result
                    except BaseException:
                        await executor.finish_attempt(preserve_error=True)
                        raise


async def arun(args, *, runtime_factory=_runtime):
    if getattr(args, "permissions_only", False) or getattr(args, "register_references_only", False):
        return await _legacy_arun(args, runtime_factory=runtime_factory)
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.application.unification_progress import ProgressRecorder
    from bisheng.knowledge.application.unification_upgrade import arun_upgrade
    from bisheng.knowledge.application.unification_upgrade_materials import UpgradeMaterials
    from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository

    KnowledgeUnificationRunRepository._identity(args.run_id, args.writer_contract_version)
    directory = getattr(args, "materials_dir", None) or Path("/app/data/upgrade/3.1.0-beta1/f118") / args.run_id
    materials = UpgradeMaterials(directory, run_id=args.run_id)
    from datetime import UTC, datetime
    from os import getpid

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%f")
    progress = materials.root / "reports" / f"progress-{stamp}-{getpid()}.jsonl"
    result = None
    try:
        with (
            tenant_execution_scope(1),
            ProgressRecorder(args.run_id, mode="apply" if args.apply else "dry-run", path=progress),
        ):
            async with runtime_factory(args) as runtime:
                with runtime.store.verified_reads():
                    result = await arun_upgrade(args, runtime=runtime, materials=materials)
    except BaseException as error:
        if result is not None:
            args._upgrade_failure = {
                "run_id": args.run_id,
                "ready": False,
                "can_apply": False,
                "preflight_complete": False,
                "business_complete": bool(args.apply and result.get("ready")),
                "stages": result.get("stages"),
                "stage_status_scope": result.get("stage_status_scope"),
                "report_path": result.get("report_path"),
                "output_or_cleanup_error": type(error).__name__,
                "commit_unknown": False if result.get("ready") else None,
                "resume_same_run": True,
            }
        raise
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = asyncio.run(arun(args))
    except (asyncio.CancelledError, KeyboardInterrupt):
        report = getattr(args, "_upgrade_failure", {})
        print(
            json.dumps(
                {
                    **report,
                    "mode": "apply" if args.apply else "dry-run",
                    "ready": False,
                    "preflight_complete": False,
                    "can_apply": False,
                    "reason": "migration_cancelled",
                    "run_id": args.run_id,
                    "resume_same_run": True,
                    "commit_unknown": report.get("commit_unknown"),
                }
            ),
            file=sys.stderr,
        )
        return 4
    except Exception as error:
        from bisheng.common.errcode.base import BaseErrorCode

        report = getattr(args, "_upgrade_failure", {})
        reason = error.kwargs.get("reason") if isinstance(error, BaseErrorCode) else None
        if not isinstance(reason, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", reason) is None:
            reason = type(error).__name__
        # Configurations/credentials and arbitrary provider exception text are
        # deliberately absent from the operational report.
        print(
            json.dumps(
                {
                    **report,
                    "mode": "apply" if args.apply else "dry-run",
                    "ready": False,
                    "preflight_complete": False,
                    "can_apply": False,
                    "code": error.code if isinstance(error, BaseErrorCode) else None,
                    "reason": reason,
                    "error_type": type(error).__name__,
                    "run_id": args.run_id,
                    "resume_same_run": True,
                }
            ),
            file=sys.stderr,
        )
        incomplete = any(
            marker in reason
            for marker in ("io_failed", "unavailable", "lock_lost", "recovery_required", "commit_unknown")
        )
        return 3 if isinstance(error, BaseErrorCode) and not incomplete else 4
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if (
        not args.apply
        and not (args.permissions_only or args.register_references_only)
        and result.get("can_apply") is not True
    ):
        unresolved = any(
            item.get("reason") == "migration_executor_recovery_required" for item in result.get("diagnostics", ())
        )
        return 4 if unresolved or (result.get("blocker") == 0 and result.get("not_evaluated", 0) > 0) else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
