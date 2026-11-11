"""T1026: native physical ownership qualifies every original namespace plan."""

import importlib
from dataclasses import asdict, replace
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application.unification_inventory_codec import (
    decode_inventory_page,
    digest,
    encode_inventory_page,
    record_from_row,
    record_from_values,
)
from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
from bisheng.permission.domain.models import ResourcePermissionMode
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification import test_migration_preflight as preflight
from test.knowledge_unification import test_migration_resource_repository as raw
from test.knowledge_unification.test_permission_namespace_resource import mapped
from test.knowledge_unification.test_permission_namespace_resource import original as original
from test.knowledge_unification.test_permission_namespace_resource import storage as storage

ERRORS = (KnowledgeOperationPlanConflictError, PermissionMigrationBlockedError)


def module():
    return importlib.import_module("bisheng.knowledge.application.unification_permission_namespace")


async def physical_tables(engine, monkeypatch):
    names = {raw.Knowledge.__tablename__, raw.KnowledgeFile.__tablename__}
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    async with engine.begin() as connection:
        for model in (raw.Knowledge, raw.KnowledgeFile):
            await connection.run_sync(lambda active, model=model: model.__table__.create(active, checkfirst=True))


@pytest.fixture
async def namespace_native(original, monkeypatch):
    engine, catalog, before = original
    await physical_tables(engine, monkeypatch)
    async with engine.begin() as connection:
        await connection.execute(sa.insert(raw.Knowledge.__table__), raw.resource(40))
    return engine, catalog, before


async def insert(engine, model, values):
    async with engine.begin() as connection:
        await connection.execute(sa.insert(model.__table__), values)


def mode(ident, kind, resource_id, **changes):
    return {**asdict(plans.ResourceModeBaseline(ident, 101, kind, str(resource_id), "CUSTOM")), **changes}


async def facts(engine):
    result = []
    async with AsyncSession(engine) as session, session.begin():
        resources = UnificationResourceRepository()
        for method in ("resources", "files"):
            after = None
            while True:
                page = await getattr(resources, "alist_" + method)(session, after_id=after, limit=200)
                result.extend(("resources", record_from_row(row)) for row in page.items)
                if page.next_after is None:
                    break
                after = page.next_after
        permissions = PermissionMigrationSnapshotRepository()
        for method in ("resource_modes", "grants", "assignees", "visible_sources"):
            after = None
            while True:
                rows = await getattr(permissions, "alist_" + method)(session, after_id=after, limit=200)
                result.extend(("permission", record_from_row(row)) for row in rows)
                if len(rows) < 200:
                    break
                after = rows[-1].id
        assert not session.identity_map and not session.new and not session.dirty
    return result


def collect(catalog, rows):
    collector = module().PermissionNamespacePlan(
        permission_planner=plans.ResourceRetirementPlanner(catalog_plan=catalog)
    )
    for section, record in rows:
        collector.observe(section=section, tenant_id=101, record=record)
    return tuple(collector.finish())


async def test_native_full_original_sources_are_compiled_and_wire_is_complete_canonical(namespace_native):
    engine, baseline, before = namespace_native
    catalog = mapped(baseline)
    acquired = await facts(engine)
    (result,) = collect(catalog, acquired)
    expected = plans.ResourceRetirementPlanner(catalog_plan=catalog).build(
        before=before, namespace_target=replace(before.mode, resource_type="knowledge_space")
    )
    assert result == expected
    wire = tuple(module().namespace_plan_records(result))
    assert [row.record_type for _, row in wire] == [
        "namespace_target_mode",
        *("namespace_after_grant" for _ in before.grants),
        *("namespace_after_assignee" for _ in before.assignees),
        *("namespace_after_visible_source" for _ in before.visible_sources),
        "permission_plan",
    ]
    assert all(row.data["mode_id"] == before.mode.id for _, row in wire)
    for section in ("permission_namespace", "conversion"):
        records = tuple(row for selected, row in wire if selected == section)
        content = encode_inventory_page(
            run_id=catalog.run_id,
            section=section,
            scope="tenant",
            tenant_id=101,
            page_index=0,
            records=records,
            kind="plan",
        )
        assert (
            decode_inventory_page(
                content,
                run_id=catalog.run_id,
                section=section,
                scope="tenant",
                tenant_id=101,
                page_index=0,
                kind="plan",
            ).records
            == records
        )
    restored = tuple(module().restore_permission_row(row) for _, row in wire[:-1])
    assert restored == (
        expected.namespace_target,
        *expected.after.grants,
        *expected.after.assignees,
        *expected.after.visible_sources,
    )
    header = module().permission_plan_record(expected)
    assert header == wire[-1][1]
    assert header.data["after_digest"] == plans._checksum(expected.after)
    assert header.data["target_mode_digest"] == plans._checksum(expected.namespace_target)
    assert header.data["assignee_count"] == len(before.assignees)


async def test_real_folder_parent_edge_is_retained_even_when_it_is_not_the_last_path_item(namespace_native):
    engine, baseline, before = namespace_native
    await insert(
        engine,
        raw.KnowledgeFile,
        [
            raw.file(1, knowledge_id=40, file_type=0),
            raw.file(2, knowledge_id=40, file_type=0),
            raw.file(3, knowledge_id=40, file_level_path="/1", level=1),
        ],
    )
    await insert(
        engine,
        ResourcePermissionMode,
        [
            mode(5, "folder", 1, parent_type="knowledge_library", parent_id="40"),
            mode(6, "folder", 2, parent_type="knowledge_library", parent_id="40"),
            mode(7, "knowledge_file", 3, parent_type="folder", parent_id="2", mode="INHERIT"),
        ],
    )
    result = collect(mapped(baseline), await facts(engine))
    assert len(result) == 4 and result[0].before == before
    assert [(row.namespace_target.parent_type, row.namespace_target.parent_id) for row in result[1:]] == [
        ("knowledge_space", "40"),
        ("knowledge_space", "40"),
        ("folder", "2"),
    ]
    assert result[-1].after.mode.mode == "INHERIT"


async def test_qa_retired_existing_space_and_unmodelled_physical_files_are_not_converted_or_repaired(namespace_native):
    engine, baseline, _ = namespace_native
    await insert(
        engine,
        raw.Knowledge,
        [raw.resource(41, type=1), raw.resource(42, type=2), raw.resource(43, type=3), raw.resource(44, type=1)],
    )
    await insert(
        engine,
        raw.KnowledgeFile,
        [
            raw.file(1, knowledge_id=40),
            raw.file(2, knowledge_id=41),
            raw.file(3, knowledge_id=42, status=3, file_level_path="/999"),
            raw.file(4, knowledge_id=44),
        ],
    )
    await insert(
        engine,
        ResourcePermissionMode,
        [
            mode(5, "knowledge_library", 41),
            mode(6, "knowledge_library", 42),
            mode(7, "knowledge_space", 43),
            mode(8, "workflow", "flow-中文"),
        ],
    )
    result = collect(mapped(baseline), await facts(engine))
    assert len(result) == 5 and all(row.after == row.before for row in result[1:])
    header = module().permission_plan_record(result[-1]).data
    assert header["before_digest"] == plans._checksum(result[-1].before)
    assert header["before_digest"] != digest(asdict(result[-1].before))


@pytest.mark.parametrize(
    "defect",
    [
        "missing_root_mode",
        "missing_physical",
        "foreign_physical",
        "wrong_root_kind",
        "root_inherit",
        "root_parent",
        "alias_id",
        "wrong_file_kind",
        "missing_parent_mode",
        "foreign_folder_root",
        "folder_cycle",
    ],
)
async def test_actual_bad_physical_or_original_parent_qualification_blocks_without_repair(namespace_native, defect):
    engine, baseline, _ = namespace_native
    async with engine.begin() as connection:
        if defect == "missing_root_mode":
            await connection.execute(sa.insert(raw.Knowledge.__table__), raw.resource(41))
        elif defect == "missing_physical":
            await connection.execute(sa.delete(raw.Knowledge.__table__))
        elif defect == "foreign_physical":
            await connection.execute(sa.update(raw.Knowledge.__table__).values(tenant_id=202))
        elif defect == "wrong_root_kind":
            await connection.execute(sa.update(raw.Knowledge.__table__).values(type=3))
        elif defect == "root_inherit":
            await connection.execute(sa.update(ResourcePermissionMode.__table__).values(mode="INHERIT"))
        elif defect == "root_parent":
            await connection.execute(
                sa.update(ResourcePermissionMode.__table__).values(parent_type="folder", parent_id="1")
            )
        elif defect == "alias_id":
            await connection.execute(sa.update(ResourcePermissionMode.__table__).values(resource_id="040"))
        else:
            await connection.execute(
                sa.insert(raw.KnowledgeFile.__table__),
                [
                    raw.file(1, knowledge_id=40, file_type=1 if defect == "wrong_file_kind" else 0),
                    raw.file(2, knowledge_id=41 if defect == "foreign_folder_root" else 40, file_type=0),
                ],
            )
            if defect == "foreign_folder_root":
                await connection.execute(sa.insert(raw.Knowledge.__table__), raw.resource(41, type=1))
            await connection.execute(
                sa.insert(ResourcePermissionMode.__table__), mode(5, "folder", 1, parent_type="folder", parent_id="2")
            )
            if defect != "missing_parent_mode":
                await connection.execute(
                    sa.insert(ResourcePermissionMode.__table__),
                    mode(
                        6,
                        "folder",
                        2,
                        parent_type="folder" if defect == "folder_cycle" else "knowledge_library",
                        parent_id="1" if defect == "folder_cycle" else "40",
                    ),
                )
    rows = await facts(engine)
    with pytest.raises(ERRORS):
        collect(mapped(baseline), rows)


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "wrong_section",
        "wrong_tenant",
        "grant_without_mode",
        "assignee_without_grant",
        "visible_without_mode",
    ],
)
async def test_frozen_record_scope_and_exact_original_parent_sets_are_closed(namespace_native, defect):
    engine, baseline, _ = namespace_native
    rows = await facts(engine)
    if defect == "grant_without_mode":
        rows = [(section, row) for section, row in rows if row.record_type != "resource_mode"]
    elif defect == "assignee_without_grant":
        rows = [(section, row) for section, row in rows if row.record_type != "grant"]
    elif defect == "visible_without_mode":
        rows = [
            (section, row) for section, row in rows if row.record_type not in {"resource_mode", "grant", "assignee"}
        ]
    collector = module().PermissionNamespacePlan(
        permission_planner=plans.ResourceRetirementPlanner(catalog_plan=mapped(baseline))
    )
    with pytest.raises(ERRORS):
        for index, (section, row) in enumerate(rows):
            collector.observe(
                section="control" if defect == "wrong_section" else section,
                tenant_id=202 if defect == "wrong_tenant" else 101,
                record=row,
            )
            if index == 0 and defect == "duplicate":
                collector.observe(section=section, tenant_id=101, record=row)
        tuple(collector.finish())


async def test_catalog_and_every_original_typed_fact_restore_exactly_and_reject_extra_or_noncanonical_data(
    namespace_native,
):
    engine, baseline, _ = namespace_native
    records = tuple(
        record_from_row(row) for row in (baseline.release, baseline.authorization, *baseline.actions, *baseline.models)
    )
    assert module().catalog_from_records(iter(records)) == baseline
    catalog = mapped(baseline)
    declarations = module().catalog_namespace_records(plans.ResourceRetirementPlanner(catalog_plan=catalog))
    assert declarations[0].data["catalog_plan_checksum"] == catalog.checksum
    assert len(declarations) == len(baseline.models) + 1
    for _, row in await facts(engine):
        if row.record_type in {"resource_mode", "grant", "assignee", "visible_source"}:
            assert record_from_row(module().restore_permission_row(row)) == row
    for bad in (records[1:], (*records, records[0])):
        with pytest.raises(ERRORS):
            module().catalog_from_records(bad)
    action = next(row for row in records if row.record_type == "catalog_action" and len(row.data["resource_types"]) > 1)
    with pytest.raises(ERRORS):
        module().restore_permission_row(
            record_from_values(
                "catalog_action", **(action.data | {"resource_types": list(reversed(action.data["resource_types"]))})
            )
        )


async def test_real_preflight_accepts_only_required_shared_planner_and_emits_full_namespace(preflight_native):
    module()
    database = preflight_native
    await database.insert(raw.Knowledge, [raw.resource(9000)])
    await database.insert(ResourcePermissionMode, [mode(1, "knowledge_library", 9000)])
    catalog = plans.build_catalog_retirement_plan(
        run_id="formal-run",
        writer_contract_version="f118-v1",
        before=preflight.pure.baseline(plans),
        target_model_checksum="f" * 64,
        namespace_type_mappings=(("knowledge_library", "knowledge_space"),),
    )
    compiler = plans.ResourceRetirementPlanner(catalog_plan=catalog)
    async with AsyncSession(database.engine) as session, session.begin():
        result = [
            row
            async for row in preflight.module.__wrapped__()
            .UnificationPreflight()
            .aiter_tenant(session, permission_planner=compiler, planned_at=datetime(2026, 11, 7, 2, 3, 4))
        ]
        assert not session.identity_map and not session.new and not session.dirty
    assert sum(row.record_type == "resource_conversion" for _, row in result) == 1
    assert sum(row.record_type == "namespace_target_mode" for _, row in result) == 1
    assert sum(row.record_type == "permission_plan" for _, row in result) == 1


preflight_resource_native = preflight.resource_native


@pytest.fixture
async def preflight_native(preflight_resource_native, monkeypatch):
    return await preflight.native.__wrapped__(preflight_resource_native, monkeypatch)
