"""Retain old payload only when native deletion and disabled access are proven."""

from dataclasses import asdict

import pytest
import sqlalchemy as sa
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_coverage import production_coverage_factory
from bisheng.knowledge.domain.repositories.unification_delete_retention_repository import load_facts
from bisheng.permission.domain.models import PermissionProjectionOperation as Operation
from bisheng.permission.domain.models import PermissionProjectionTuple as Tuple
from bisheng.permission.domain.models import ResourcePermissionMode as Mode
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.services.projection_plan import (
    ProjectionPlan,
    ProjectionTupleDelta,
    build_projection_operation,
    normalize_projection_plan,
    projection_request_checksum,
)
from test.knowledge_unification import test_migration_structural_retention as original

resource_native, native, complete = original.resource_native, original.native, original.complete
raw_resource_native = original.raw_resource_native
transport, module, published_input = original.transport, original.module, original.published_input
no_real_network = original.reference_tests.no_real_network
resources = original.resources


def receipt(
    ident, resource_type, resource_id, version, *, store_id, model_id, subjects=("user:*", "service_account:*")
):
    plan = normalize_projection_plan(
        ProjectionPlan(
            tenant_id=101,
            idempotency_key=f"original-delete:{ident}",
            operation_type="RESOURCE_DELETE",
            scope_type="resource",
            scope_key=f"{resource_type}:{resource_id}",
            expected_version=version,
            target_version=version + 1,
            store_id=store_id,
            model_id=model_id,
            operator_id=7,
            change_item_count=1,
            deltas=tuple(
                ProjectionTupleDelta(
                    "COMMIT", seq, "DELETE", subject, "permission_enabled", f"{resource_type}:{resource_id}"
                )
                for seq, subject in enumerate(subjects)
            ),
        )
    )
    operation, rows = build_projection_operation(plan, request_checksum=projection_request_checksum(plan))
    operation.id, operation.status = ident, "FINALIZED"
    for seq, row in enumerate(rows):
        row.id, row.operation_id, row.status = ident * 10 + seq, ident, "APPLIED"
    return operation, rows


async def seed_receipts(database, *, subjects=("user:*", "service_account:*")):
    async with database.engine.begin() as connection:
        await connection.run_sync(lambda c: Tuple.__table__.create(c, checkfirst=True))
    with tenant_execution_scope(101):
        async with AsyncSession(database.engine) as session, session.begin():
            pin = (
                await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
            ).authorization
            modes = (await session.exec(select(Mode).where(Mode.id.in_((9000, 1))))).all()
            for seq, mode in enumerate(modes):
                operation, rows = receipt(
                    7001 + seq,
                    mode.resource_type,
                    mode.resource_id,
                    mode.version,
                    store_id=pin.store_id,
                    model_id=pin.model_id,
                    subjects=subjects,
                )
                session.add_all([operation, *rows])
                mode.version += 1
                mode.operation_id = operation.id
                session.add(mode)


async def seed_legacy_receipts(database):
    await seed_receipts(database, subjects=("user:*",))


REMOVED = [
    (subject, "permission_enabled", obj)
    for subject in ("user:*", "service_account:*")
    for obj in ("knowledge_library:9000", "knowledge_file:1")
]


@pytest.mark.parametrize(
    "published_input",
    [
        {"parent": True, "reference_seed": seed_receipts, "remove_raw_edges": REMOVED},
        {"parent": True, "reference_seed": seed_legacy_receipts, "remove_raw_edges": REMOVED},
    ],
    indirect=True,
)
async def test_full_migration_preserves_payload_and_disabled_permissions_including_resume(published_input):
    value = published_input
    result = await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)
    assert result.complete
    assert await original.reference_tests.app(value).arun_references(**value.input, operator_id=7) == result
    assert not any(
        relation == "permission_enabled" and obj in {"knowledge_space:9000", "knowledge_file:1"}
        for _, relation, obj in value.store.tuples
    )
    async with value.sessions() as session, session.begin():
        assert (await session.get(resources.Knowledge, 9000)).type == 3
        assert await session.get(resources.KnowledgeFile, 1) is not None
        assert (await production_coverage_factory(session).arequire_global_ready()).verified_tenant_ids


@pytest.mark.parametrize(
    "published_input", [{"parent": True, "reference_seed": seed_receipts, "remove_raw_edges": REMOVED}], indirect=True
)
@pytest.mark.parametrize("drift", ["enabled", "receipt"])
async def test_after_freeze_drift_refuses_opening_or_reenabling_history(published_input, drift):
    value = published_input
    if drift == "enabled":
        value.store.tuples.add(("user:*", "permission_enabled", "knowledge_library:9000"))
    else:
        async with value.database.engine.begin() as connection:
            await connection.execute(sa.update(Operation).where(Operation.id == 7001).values(after_checksum="f" * 64))
    with pytest.raises(BaseErrorCode):
        await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)


@pytest.mark.parametrize("count", [200, 400])
async def test_native_receipt_verification_uses_two_reads_per_bounded_batch(complete, count):
    async with complete.engine.begin() as connection:
        await connection.run_sync(lambda c: Tuple.__table__.create(c, checkfirst=True))
    with tenant_execution_scope(101):
        async with AsyncSession(complete.engine) as session, session.begin():
            for offset in range(count):
                operation, rows = receipt(
                    8000 + offset, "knowledge_file", str(10000 + offset), 1, store_id="native", model_id="old"
                )
                session.add_all([operation, *rows])
        complete.queries.clear()
        async with AsyncSession(complete.engine) as session, session.begin():
            facts = []
            for offset in range(0, count, 200):
                candidates = {
                    ("knowledge_file", str(10000 + i)): (8000 + i, 2) for i in range(offset, min(offset + 200, count))
                }
                facts.extend(await load_facts(session, candidates=candidates))
            assert len(facts) == count and all(asdict(f)["reason"] for f in facts)
        assert len(complete.queries) == count // 200 * 2


async def seed_closed_empty_root(database):
    await database.insert(resources.Knowledge, [resources.resource(15000, model=None)])
    async with database.engine.begin() as connection:
        await connection.run_sync(lambda c: Tuple.__table__.create(c, checkfirst=True))
    with tenant_execution_scope(101):
        async with AsyncSession(database.engine) as session, session.begin():
            pin = (
                await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
            ).authorization
            operation, rows = receipt(
                9500, "knowledge_library", "15000", 0, store_id=pin.store_id, model_id=pin.model_id
            )
            session.add_all(
                [
                    operation,
                    *rows,
                    Mode(
                        id=15000,
                        tenant_id=101,
                        resource_type="knowledge_library",
                        resource_id="15000",
                        mode="CUSTOM",
                        version=1,
                        projection_state="CURRENT",
                        operation_id=9500,
                    ),
                ]
            )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_closed_empty_root}], indirect=True)
async def test_closed_empty_root_normal_conversion_and_completed_coverage_keep_access_disabled(published_input):
    value = published_input
    result = await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)
    assert (
        result.complete
        and await original.reference_tests.app(value).arun_references(**value.input, operator_id=7) == result
    )
    assert not any(obj in {"knowledge_library:15000", "knowledge_space:15000"} for _, _, obj in value.store.tuples)
    async with value.sessions() as session, session.begin():
        row = await session.get(resources.Knowledge, 15000)
        assert row.type == 3 and row.user_id == 7
        assert (await production_coverage_factory(session).arequire_global_ready()).verified_tenant_ids
