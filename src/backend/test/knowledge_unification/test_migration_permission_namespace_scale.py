"""T1026: actual SQL pages -> one compiled index -> linear namespace records."""

from dataclasses import asdict

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.model_policy import CustomModelSelection
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification import test_perm_migration_snapshot as native
from test.knowledge_unification.test_migration_permission_namespace import (
    facts,
    insert,
    mode,
    module,
    physical_tables,
    raw,
)
from test.knowledge_unification.test_migration_permission_namespace import storage as storage
from test.knowledge_unification.test_permission_floor_retirement_signing import legacy_catalog
from test.knowledge_unification.test_permission_namespace_catalog import build
from test.knowledge_unification.test_permission_namespace_resource_scale import measure


@pytest.mark.parametrize(
    ("roots", "source_count", "models"),
    [(401, 1, 27), (10001, 1, 27), (1, 401, 27), (1, 10001, 27), (3, 3, 401), (3, 3, 1001)],
)
async def test_real_root_source_pages_do_not_rebuild_catalog_or_scan_all_modes_per_resource(
    storage, monkeypatch, roots, source_count, models
):
    baseline = legacy_catalog(
        customs=tuple(CustomModelSelection(f"scale-{i}", f"Scale {i}", ("download", "use")) for i in range(models - 4))
    )
    monkeypatch.setattr(native, "baseline", lambda _module: baseline)
    async with AsyncSession(storage) as session, session.begin():
        await native.seed_catalog(session)
    await physical_tables(storage, monkeypatch)
    await insert(storage, raw.Knowledge, [raw.resource(1000 + i) for i in range(roots)])
    await insert(storage, ResourcePermissionMode, [mode(i + 1, "knowledge_library", 1000 + i) for i in range(roots)])
    grant_count = min(roots, source_count)
    grants = tuple(
        plans.PermissionGrantBaseline(i + 1, 101, "knowledge_library", str(1000 + i), "scale-0", "ACTIVE")
        for i in range(grant_count)
    )
    await insert(storage, PermissionGrant, [asdict(row) for row in grants])
    sources, buckets = [], {row.id: [] for row in grants}
    for index in range(source_count):
        original = GrantSourceService().canonicalize_source(
            source_id=index + 1, subject_type="user", subject_id="7", source_type="OTHER", source_ref=f"原来源:{index}"
        )
        values = asdict(original)
        del values["active"]
        row = plans.PermissionAssigneeBaseline(
            id=values.pop("source_id"),
            grant_id=index % grant_count + 1,
            tenant_id=101,
            state="INACTIVE" if index == source_count - 1 else "ACTIVE",
            **values,
        )
        sources.append(row)
        buckets[row.grant_id].append(row.to_source_record())
    await insert(storage, PermissionGrantAssignee, [asdict(row) for row in sources])
    by_model = {row.model_key: row for row in baseline.models}
    scopes = {row.code: row.resource_types for row in baseline.actions}
    visible = []
    for grant in grants:
        before = plans.PermissionResourceBaseline(
            101,
            "knowledge_library",
            grant.resource_id,
            plans.ResourceModeBaseline(grant.id, 101, "knowledge_library", grant.resource_id, "CUSTOM"),
            (grant,),
            tuple(row for row in sources if row.grant_id == grant.id),
            (),
        )
        (snapshot,) = plans._grants(before, by_model, scopes, {grant.id: tuple(buckets[grant.id])})
        for source in snapshot.sources:
            value = VisibilityProjectionCompiler._compile_source(101, snapshot, source)
            if not source.active:
                value = value.model_copy(update={"state": "RETIRED"})
            visible.append({"id": source.source_id, **value.model_dump()})
    await insert(storage, PermissionVisibleSourceProjection, visible)
    async with AsyncSession(storage) as session, session.begin():
        acquired = await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
    assert acquired == baseline
    catalog = build(acquired, namespace_type_mappings=(("knowledge_library", "knowledge_space"),))
    records = await facts(storage)
    sql = []

    def capture(_c, _cu, statement, _p, _ctx, _many):
        sql.append(statement)

    def consume():
        compiler = plans.ResourceRetirementPlanner(catalog_plan=catalog)
        collector = module().PermissionNamespacePlan(permission_planner=compiler)
        for section, row in records:
            collector.observe(section=section, tenant_id=101, record=row)
        count, wire = 0, 0
        for plan in collector.finish():
            count += 1
            wire += sum(1 for _ in module().namespace_plan_records(plan))
        assert count == roots and wire == 2 * roots + grant_count + 2 * source_count
        return count

    sa.event.listen(storage.sync_engine, "before_cursor_execute", capture)
    try:
        count, counters = measure(monkeypatch, consume)
    finally:
        sa.event.remove(storage.sync_engine, "before_cursor_execute", capture)
    assert not sql and count == roots
    assert counters["catalog"] == counters["derive"] == 1
    assert counters["model_candidates"] == models
    assert counters["source_reads"] <= 20 * source_count
    assert counters["compiled_sources"] <= 4 * source_count
    print({"roots": roots, "sources": source_count, "models": models, "SQL": len(sql), **counters})
