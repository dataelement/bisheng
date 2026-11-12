"""T975: preserve existing private floor facts through native M2 artifacts."""

import json
from dataclasses import fields, replace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.knowledge.application import unification_inventory_codec as codec
from bisheng.permission.domain.models import PermissionAction, PermissionModel, PermissionModelAction
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.migration import f118_plan as plans
from bisheng.permission.migration import f118_verify as verify
from test.knowledge_unification import test_migration_inventory_application as original
from test.knowledge_unification.test_perm_migration import after_catalog, baseline
from test.knowledge_unification.test_perm_migration_snapshot import seed_catalog
from test.knowledge_unification.test_perm_migration_snapshot import storage as storage

resource_native = original.resource_native
native = original.native
complete = original.complete
transport = original.transport
module = original.module


def controlled(floor=3, **changes):
    before = baseline(plans)
    row = next(model for model in before.models if model.model_key == "file-use")
    return replace(
        row,
        selected_action_codes=("download",),
        effective_action_codes=("download",),
        derived_level=3,
        visibility_only_resource_types=("tool",),
        visibility_level=3,
        retired_use_level_floor=floor,
        **changes,
    )


async def insert_floor(session):
    download = (
        await session.execute(sa.select(PermissionAction.id).where(PermissionAction.code == "download"))
    ).scalar_one()
    session.add(
        PermissionModel(
            id=80,
            catalog_release_id=1,
            model_key="controlled",
            name="Controlled",
            normalized_name="controlled",
            kind="CUSTOM",
            derived_level=3,
            visibility_only_resource_types=["tool"],
            visibility_level=3,
            retired_use_level_floor=3,
            legacy_source_key="original-controlled",
        )
    )
    session.add(PermissionModelAction(id=80, model_id=80, action_id=download))
    await session.flush()


def build(before):
    return plans.build_catalog_retirement_plan(
        run_id="existing-floor", writer_contract_version="f118-p1", before=before, target_model_checksum="f" * 64
    )


@pytest.mark.parametrize("floor", [None, 3])
def test_baseline_record_and_page_include_the_complete_nullable_fact(floor):
    row = controlled(floor)
    assert fields(row)[-1].name == "retired_use_level_floor"
    record = codec.record_from_row(row)
    assert record.data["retired_use_level_floor"] == floor
    arguments = {
        "run_id": "existing-floor",
        "section": "catalog",
        "scope": "global",
        "tenant_id": None,
        "page_index": 0,
    }
    content = codec.encode_inventory_page(**arguments, records=(record,))
    assert codec.decode_inventory_page(content, **arguments).records == (record,)
    assert codec.canonical(json.loads(content)) == content


@pytest.mark.parametrize("floor", [True, False, 0, -1, 5, 3.0, "3"])
def test_baseline_rejects_non_native_and_out_of_range_floor(floor):
    with pytest.raises((TypeError, ValueError)):
        controlled(floor)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "STANDARD"},
        {"visibility_only_resource_types": ()},
        {"visibility_only_resource_types": ("tool", "tool")},
        {"visibility_only_resource_types": ("unknown",)},
        {"visibility_level": 2},
        {"derived_level": 2},
        {"derived_level": True},
    ],
)
def test_existing_floor_requires_matching_canonical_provenance_and_original_tier(changes):
    with pytest.raises((TypeError, ValueError)):
        replace(controlled(), **changes)


@pytest.mark.parametrize("floor", [True, 0, 5, 3.0, "3"])
def test_codec_rejects_bad_floor_even_in_an_otherwise_complete_native_record(floor):
    values = codec.record_from_row(controlled()).data
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values("permission_model", **(values | {"retired_use_level_floor": floor}))


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_missing_preparatory_field_and_extra_provenance_are_not_formal_records(change):
    values = codec.record_from_row(controlled()).data
    if change == "missing":
        values.pop("retired_use_level_floor")
    else:
        values["issued_by_client"] = True
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values("permission_model", **values)


def test_existing_floor_is_carried_through_canonical_rebuild_and_original_verifier():
    before = baseline(plans)
    before = replace(
        before, models=tuple(controlled() if model.model_key == "file-use" else model for model in before.models)
    )
    catalog = build(before)
    after = next(model for model in catalog.after_models if model.model_key == "file-use")
    assert after == controlled()
    assert verify.verify_catalog_retirement(plan=catalog, actual=after_catalog(catalog)).complete
    tampered = replace(
        catalog,
        after_models=tuple(
            replace(model, retired_use_level_floor=None) if model.model_key == "file-use" else model
            for model in catalog.after_models
        ),
    )
    with pytest.raises(PermissionMigrationBlockedError):
        verify.verify_catalog_retirement(plan=tampered, actual=after_catalog(tampered))


def test_old_mixed_support_now_issues_only_its_exact_original_floor():
    from test.knowledge_unification.test_permission_floor_retirement_signing import legacy_catalog

    before = legacy_catalog()
    result = build(before)
    old = next(model for model in before.models if model.model_key == "mixed-use")
    after = next(model for model in result.after_models if model.model_key == "mixed-use")
    pure = next(model for model in result.after_models if model.model_key == "pure-use")
    assert old.retired_use_level_floor is None and old.derived_level == 3
    assert after.retired_use_level_floor == after.derived_level == 3
    assert pure.retired_use_level_floor is None and pure.derived_level == 3


async def test_native_snapshot_reflection_keeps_excluded_floor_without_repo_changes(storage):
    async with AsyncSession(storage) as session, session.begin():
        await seed_catalog(session)
        await insert_floor(session)
        model = await session.get(PermissionModel, 80)
        assert "retired_use_level_floor" not in model.model_dump()
        snapshot = await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
        row = next(model for model in snapshot.models if model.model_key == "controlled")
        assert row.retired_use_level_floor == 3 and row.legacy_source_key == "original-controlled"
        assert all(model.retired_use_level_floor is None for model in snapshot.models if model.id != 80)
        before = len(session.dirty), len(session.new)
        catalog = build(snapshot)
        assert next(model for model in catalog.after_models if model.id == 80).retired_use_level_floor == 3
        assert (len(session.dirty), len(session.new)) == before


async def test_real_native_m2_graph_roundtrip_and_corrupt_floor_bytes_are_rejected(module, complete, transport):
    async with AsyncSession(complete.engine) as session, session.begin():
        await insert_floor(session)
    application = original.application(module, transport)
    async with AsyncSession(complete.engine) as session, session.begin():
        frozen = await application.arun(session, **transport.inputs)
    reader = module.UnificationInventoryApplication(artifact_store=transport.store)
    arguments = {name: transport.inputs[name] for name in ("environment", "backup_ref", "schema_ref")}
    complete.queries.clear()
    pages = [page async for page in reader.aiter_frozen_pages(frozen, **arguments)]
    assert complete.queries == []
    records = []
    target = None
    for page in pages:
        if page.section != "catalog":
            continue
        decoded = codec.decode_inventory_page(
            page.content,
            run_id=frozen.run_id,
            section=page.section,
            scope=page.scope,
            tenant_id=page.tenant_id,
            page_index=page.page_index,
            kind=page.kind,
        )
        for record in decoded.records:
            if record.record_type == "permission_model":
                records.append((page.kind, record.data))
                if record.data["model_key"] == "controlled" and page.kind == "baseline":
                    target = page
    assert {
        kind for kind, data in records if data["model_key"] == "controlled" and data["retired_use_level_floor"] == 3
    } == {"baseline", "plan"}
    assert any(data["retired_use_level_floor"] is None for _, data in records)
    value = json.loads(target.content)
    next(row for row in value["records"] if row.get("model_key") == "controlled")["retired_use_level_floor"] = 2
    transport.objects[target.descriptor["object_key"]] = codec.canonical(value)
    with pytest.raises(ReferenceCoverageNotReadyError):
        async for _ in reader.aiter_frozen_pages(frozen, **arguments):
            pass
