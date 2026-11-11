"""T1020: one real Catalog compile across multiple tenant/resource batches."""

from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.services.model_policy import CustomModelSelection
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification import test_perm_migration_snapshot as native
from test.knowledge_unification.test_perm_migration_snapshot import storage as storage
from test.knowledge_unification.test_permission_floor_retirement_signing import legacy_catalog
from test.knowledge_unification.test_permission_namespace_catalog import MAPPING, build
from test.knowledge_unification.test_permission_namespace_resource_scale import measure, resource_rows


def mixed_rows(catalog, count):
    models = {row.model_key: row for row in catalog.models}
    scopes = {row.code: row.resource_types for row in catalog.actions}
    for index, row in enumerate(resource_rows(catalog, count)):
        tenant = (101, 202, 303)[index % 3]
        row = replace(
            row,
            tenant_id=tenant,
            mode=replace(row.mode, tenant_id=tenant),
            grants=tuple(replace(grant, tenant_id=tenant) for grant in row.grants),
            assignees=tuple(replace(source, tenant_id=tenant) for source in row.assignees),
        )
        buckets = {}
        for source in row.assignees:
            buckets.setdefault(source.grant_id, []).append(source.to_source_record())
        snapshots = plans._grants(row, models, scopes, {key: tuple(value) for key, value in buckets.items()})
        visible = (
            VisibilityProjectionCompiler()
            .compile(tenant_id=tenant, grants=snapshots, existing_sources=())
            .active_sources
        )
        retired = tuple(
            VisibilityProjectionCompiler._compile_source(tenant, grant, grant.sources[-1]).model_copy(
                update={"state": "RETIRED"}
            )
            for grant in snapshots
        )
        yield replace(
            row,
            visible_sources=tuple(
                plans.PermissionVisibleSourceBaseline(index * 100 + n, value)
                for n, value in enumerate((*visible, *retired), 1)
            ),
        )


@pytest.mark.parametrize(("resources", "models"), [(401, 27), (1001, 27), (5, 401), (5, 1001)])
async def test_one_native_catalog_index_is_reused_across_mixed_tenants_and_small_batches(
    storage, monkeypatch, resources, models
):
    original = legacy_catalog(
        customs=tuple(
            CustomModelSelection(f"custom-{i}", f"Custom {i}", ("download", "use")) for i in range(models - 4)
        )
    )
    monkeypatch.setattr(native, "baseline", lambda _module: original)
    async with AsyncSession(storage) as session, session.begin():
        await native.seed_catalog(session)
    async with AsyncSession(storage) as session, session.begin():
        baseline = await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
    assert baseline == original and len(baseline.models) == models
    catalog = build(baseline, namespace_type_mappings=MAPPING)
    rows = tuple(mixed_rows(baseline, resources))
    sql, matrices = [], []
    matrix = plans._namespace_applicability

    def record_matrix(*args, **kwargs):
        matrices.append(1)
        return matrix(*args, **kwargs)

    def capture(_c, _cu, statement, _p, _ctx, _many):
        sql.append(statement)

    def consume():
        compiler = plans.ResourceRetirementPlanner(catalog_plan=catalog)
        count = 0
        for tenant in (101, 202, 303):
            selected = tuple(row for row in rows if row.tenant_id == tenant)
            for offset in range(0, len(selected), 7):
                batch = selected[offset : offset + 7]
                for value in compiler.build_many(
                    before=iter(batch),
                    target_modes=(replace(row.mode, resource_type="knowledge_space") for row in batch),
                ):
                    assert value.after.assignees is value.before.assignees
                    assert value.after.tenant_id == tenant
                    count += 1
        return count

    monkeypatch.setattr(plans, "_namespace_applicability", record_matrix)
    sa.event.listen(storage.sync_engine, "before_cursor_execute", capture)
    try:
        result, counts = measure(monkeypatch, consume)
    finally:
        sa.event.remove(storage.sync_engine, "before_cursor_execute", capture)
    assert result == resources and not sql and len(matrices) == 1
    assert counts["catalog"] == counts["derive"] == 1
    assert counts["model_candidates"] == models
    assert counts["source_reads"] <= 8 * resources * 100
    assert counts["compiled_sources"] <= 4 * resources * 100
    print({"resources": resources, "models": models, "tenants": 3, "SQL": len(sql), "matrix": len(matrices), **counts})
