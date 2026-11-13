"""Run F118 stopped-service M2→M3→M4 or inspect the same durable Run.

From src/backend with the service's config: python scripts/unify_knowledge_spaces.py
--run-id maintenance-1 --environment production --backup-ref '<descriptor JSON>'
--schema-ref '<descriptor JSON>'. Default preview writes no SQL, FGA or artifacts.
For a new Run it performs the complete current inventory preflight; for an
existing Run it validates that Run's original frozen reference plan.
Add --apply --operator-id 7 to freeze and execute; --apply --resume requires the
same already-frozen Run. This script never stops, starts or probes services.
For historical depth/orphan permission cleanup, run prepare_f118_history.py
with its selected-row backup plan BEFORE the first M2 freeze, never mid-resume.
"""

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _operator(value):
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("operator-id must be a nonnegative integer") from error
    if result < 0:
        raise argparse.ArgumentTypeError("operator-id must be a nonnegative integer")
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
    result.add_argument("--environment", required=True)
    result.add_argument("--backup-ref", required=True, type=_descriptor)
    result.add_argument("--schema-ref", required=True, type=_descriptor)
    result.add_argument("--operator-id", type=_operator, default=0)
    result.add_argument("--apply", action="store_true", help="execute the original full frozen migration")
    result.add_argument(
        "--resume", action="store_true", help="require an existing frozen Run; never replace its baseline"
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
        await app_context.async_get_instance(DatabaseManager.name)
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

            yield SimpleNamespace(store=store, sessions=get_async_db_session, inventory=inventory)
    finally:
        # Lazy acquisition does not mark ApplicationContext initialized, so
        # its global close helper intentionally skips these owned managers.
        for manager in reversed(owned):
            await manager.async_close()


async def arun(args, *, runtime_factory=_runtime):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
    from bisheng.knowledge.application.unification_coverage import production_coverage_factory
    from bisheng.knowledge.application.unification_reference_plan import UnificationReferencePlanReader
    from bisheng.knowledge.domain.repositories.unification_coverage_repository import UnificationCoverageRepository
    from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository

    inputs = {
        name: getattr(args, name)
        for name in ("run_id", "writer_contract_version", "environment", "backup_ref", "schema_ref")
    }
    runs = KnowledgeUnificationRunRepository()
    runs._identity(inputs["run_id"], inputs["writer_contract_version"])
    with tenant_execution_scope(1):
        async with runtime_factory(args) as runtime:
            application = UnificationSQLConversionApplication(
                artifact_store=runtime.store, session_factory=runtime.sessions
            )
            async with runtime.sessions() as session, session.begin():
                tenants = await runs.alist_actual_tenant_ids(session)
                frozen = await runs.aget_global_freeze(
                    session,
                    run_id=inputs["run_id"],
                    writer_contract_version=inputs["writer_contract_version"],
                    tenant_ids=tenants,
                )
            if args.resume and frozen is None:
                raise KnowledgeOperationPlanConflictError(reason="migration_cli_resume_requires_frozen_run")
            if not args.apply:
                if frozen is not None:
                    reader = UnificationReferencePlanReader(inventory=application.reader, artifact_store=runtime.store)
                    await reader.aprepare(
                        frozen, **{name: inputs[name] for name in ("environment", "backup_ref", "schema_ref")}
                    )
                else:
                    if not callable(runtime.inventory):
                        raise KnowledgeOperationPlanConflictError(
                            reason="migration_cli_native_inventory_ports_required"
                        )
                    async with runtime.sessions() as session, session.begin():
                        async with runtime.inventory(session) as inventory:
                            scanned = await inventory.arun(session, **inputs, freeze=False)
                    tenants = scanned.tenant_ids
                return {
                    "mode": "preview",
                    "run_id": inputs["run_id"],
                    "writer_contract_version": inputs["writer_contract_version"],
                    "tenant_ids": list(tenants),
                    "baseline_ref": frozen.baseline_ref if frozen else None,
                    "plan_ref": frozen.plan_ref if frozen else None,
                    "frozen": frozen is not None,
                    "validation_scope": "frozen_run" if frozen is not None else "current_inventory",
                    "preflight_complete": frozen is None,
                    "ready": False,
                }
            if frozen is None:
                if not callable(runtime.inventory):
                    raise KnowledgeOperationPlanConflictError(reason="migration_cli_native_inventory_ports_required")
                async with runtime.sessions() as session, session.begin():
                    async with runtime.inventory(session) as inventory:
                        frozen = await inventory.arun(session, **inputs)
            report = await application.arun_references(**inputs, operator_id=args.operator_id)
            async with runtime.sessions() as session, session.begin():
                ready = await production_coverage_factory(
                    session, writer_contract_version=inputs["writer_contract_version"]
                ).arequire_global_ready()
                rows = await UnificationCoverageRepository().aload_runs(session)
                rows = [row for row in rows if row["run_id"] == report.run_id]
                proofs = {
                    str(row["tenant_id"]): row["verification_report"]["reference_coverage"]["proofs"] for row in rows
                }
            return {
                "mode": "apply",
                **asdict(report),
                "tenant_ids": list(report.tenant_ids),
                "ready": report.complete and ready.verified_tenant_ids == report.tenant_ids,
                "invalid_manifest_ref": frozen.plan_ref,
                "source_proofs": proofs,
            }


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = asyncio.run(arun(args))
    except Exception as error:
        from bisheng.common.errcode.base import BaseErrorCode

        if isinstance(error, BaseErrorCode):
            print(
                json.dumps(
                    {
                        "ready": False,
                        "code": error.code,
                        "reason": error.kwargs.get("reason"),
                        "run_id": args.run_id,
                        "resume_same_run": True,
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 3
        # Configurations/credentials and arbitrary provider exception text are
        # deliberately absent from the operational report.
        print(
            json.dumps(
                {"ready": False, "error_type": type(error).__name__, "run_id": args.run_id, "resume_same_run": True}
            ),
            file=sys.stderr,
        )
        return 4
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
