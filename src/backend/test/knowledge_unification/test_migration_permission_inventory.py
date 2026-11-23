"""T1028: native permission facts must close the complete frozen namespace."""

import importlib
from dataclasses import replace

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.knowledge.application.unification_inventory_codec import record_from_row, record_from_values
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification.test_permission_namespace_resource import mapped
from test.knowledge_unification.test_permission_namespace_resource import original as original
from test.knowledge_unification.test_permission_namespace_resource import storage as storage

ERRORS = (KnowledgeOperationPlanConflictError, PermissionMigrationBlockedError)


def module():
    return importlib.import_module("bisheng.knowledge.application.unification_permission_inventory")


def producer():
    return importlib.import_module("bisheng.knowledge.application.unification_permission_namespace")


def physical(before, *, kind=0):
    return record_from_values(
        "resource",
        tenant_id=before.tenant_id,
        id=int(before.resource_id),
        type=kind,
        user_id=7,
        state=None,
        model=None,
        index_name=None,
        collection_name=None,
        creation_request_id=None,
        creation_payload_hash=None,
        old_business_digest="a" * 64,
        neutral_digest="b" * 64,
    )


def baseline_rows(catalog, before):
    yield "resources", physical(before)
    yield "permission", record_from_row(before.mode)
    for rows in (before.grants, before.assignees, before.visible_sources):
        for row in rows:
            yield "permission", record_from_row(row)


def baseline_metadata(catalog):
    descriptor = {"object_key": "original/proof", "sha256": "a" * 64}
    return record_from_values(
        "run",
        writer_contract_version=catalog.writer_contract_version,
        environment="test",
        tenant_count=1,
        tenant_inventory_digest="a" * 64,
        backup_ref=descriptor,
        schema_ref=descriptor,
        catalog_digest=catalog.before.release.checksum,
        authorization_model_checksum=catalog.before.authorization.model_checksum,
        baseline_ref=None,
    )


def make(catalog):
    return module().PermissionInventoryVerifier(
        run_id=catalog.run_id,
        writer_contract_version=catalog.writer_contract_version,
        target_model_checksum=catalog.target_model_checksum,
        catalog_plan_checksum=catalog.checksum,
    )


def feed(verifier, kind, section, tenant, record):
    verifier.observe(kind=kind, section=section, tenant_id=tenant, record=record)


def start(verifier, catalog):
    feed(verifier, "baseline", "manifest", None, baseline_metadata(catalog))
    for row in (catalog.before.release, catalog.before.authorization, *catalog.before.actions, *catalog.before.models):
        feed(verifier, "baseline", "catalog", None, record_from_row(row))


def plan_rows(catalog, plan):
    for row in (*catalog.after_actions, *catalog.after_models):
        yield "catalog", None, record_from_row(row)
    for row in producer().catalog_namespace_records(plans.ResourceRetirementPlanner(catalog_plan=catalog)):
        yield "permission_namespace", None, row
    for section, row in producer().namespace_plan_records(plan):
        yield section, plan.before.tenant_id, row


def changed(row, **changes):
    return record_from_values(row.record_type, **(row.data | changes))


async def test_native_complete_original_sources_and_explicit_after_are_verified(original):
    _, before_catalog, before = original
    catalog = mapped(before_catalog)
    verifier = make(catalog)
    start(verifier, catalog)
    for section, row in baseline_rows(catalog, before):
        feed(verifier, "baseline", section, before.tenant_id, row)
    plan = plans.ResourceRetirementPlanner(catalog_plan=catalog).build(
        before=before, namespace_target=replace(before.mode, resource_type="knowledge_space")
    )
    for section, tenant, row in plan_rows(catalog, plan):
        feed(verifier, "plan", section, tenant, row)
    verifier.finish()


@pytest.mark.parametrize(
    "defect",
    [
        "target_namespace",
        "target_parent",
        "target_version",
        "target_tenant",
        "missing_target",
        "missing_grant",
        "duplicate_grant",
        "missing_assignee",
        "inactive_assignee_changed",
        "retired_visible_missing",
        "source_metadata_changed",
        "source_nested_tenant",
        "hint_only",
        "wrong_hint",
        "wrong_before_digest",
        "wrong_after_digest",
        "wrong_count",
        "wrong_plan_checksum",
        "matrix_missing",
        "matrix_duplicate",
        "matrix_action_order",
        "catalog_declaration_missing",
        "catalog_after_model_changed",
        "catalog_before_metadata",
        "physical_missing",
        "physical_wrong_type",
    ],
)
async def test_rehashed_closed_rows_cannot_hide_namespace_or_source_drift(original, defect):
    _, before_catalog, before = original
    catalog = mapped(before_catalog)
    verifier = make(catalog)
    with pytest.raises(ERRORS):
        metadata = baseline_metadata(catalog)
        if defect == "catalog_before_metadata":
            metadata = changed(metadata, catalog_digest="0" * 64)
        feed(verifier, "baseline", "manifest", None, metadata)
        for row in (
            catalog.before.release,
            catalog.before.authorization,
            *catalog.before.actions,
            *catalog.before.models,
        ):
            feed(verifier, "baseline", "catalog", None, record_from_row(row))
        for section, row in baseline_rows(catalog, before):
            if row.record_type == "resource" and defect == "physical_missing":
                continue
            if row.record_type == "resource" and defect == "physical_wrong_type":
                row = changed(row, type=3)
            feed(verifier, "baseline", section, before.tenant_id, row)
        plan = plans.ResourceRetirementPlanner(catalog_plan=catalog).build(
            before=before, namespace_target=replace(before.mode, resource_type="knowledge_space")
        )
        touched = False
        for section, tenant, row in plan_rows(catalog, plan):
            tag, data = row.record_type, row.data
            if defect == "hint_only" and section == "permission_namespace":
                continue
            if tag == "namespace_target_mode":
                if defect == "missing_target":
                    continue
                changes = {
                    "target_namespace": {"resource_type": "knowledge_library"},
                    "target_parent": {"parent_type": "folder", "parent_id": "42"},
                    "target_version": {"version": data["version"] + 1},
                    "target_tenant": {"tenant_id": 202},
                }.get(defect)
                if changes:
                    row = changed(row, **changes)
            if tag == "namespace_after_grant":
                if defect == "missing_grant":
                    continue
                if defect == "duplicate_grant":
                    feed(verifier, "plan", section, tenant, row)
            if tag == "namespace_after_assignee":
                if defect == "missing_assignee" and not touched:
                    touched = True
                    continue
                if defect == "inactive_assignee_changed" and data["state"] == "INACTIVE":
                    row = changed(row, state="ACTIVE")
            if tag == "namespace_after_visible_source":
                if defect == "retired_visible_missing" and data["source"]["state"] == "RETIRED":
                    continue
                if defect == "source_metadata_changed":
                    row = changed(row, source=data["source"] | {"source_version": 99})
                if defect == "source_nested_tenant":
                    row = changed(row, source=data["source"] | {"tenant_id": 202})
            if tag == "permission_plan":
                changes = {
                    "wrong_hint": {"target_resource_type": "knowledge_library"},
                    "wrong_before_digest": {"before_digest": "0" * 64},
                    "wrong_after_digest": {"after_digest": "0" * 64},
                    "wrong_count": {"assignee_count": data["assignee_count"] + 1},
                    "wrong_plan_checksum": {"plan_checksum": "0" * 64},
                }.get(defect)
                if changes:
                    row = changed(row, **changes)
            if tag == "namespace_catalog" and defect == "catalog_declaration_missing":
                continue
            if tag == "namespace_applicability" and not touched:
                if defect == "matrix_missing":
                    touched = True
                    continue
                if defect == "matrix_duplicate":
                    touched = True
                    feed(verifier, "plan", section, tenant, row)
                if defect == "matrix_action_order" and len(data["after_action_codes"]) > 1:
                    touched = True
                    row = changed(row, after_action_codes=list(reversed(data["after_action_codes"])))
            if tag == "permission_model" and defect == "catalog_after_model_changed" and not touched:
                touched = True
                row = changed(row, name=data["name"] + " changed")
            feed(verifier, "plan", section, tenant, row)
        verifier.finish()


async def test_late_baseline_catalog_and_reopened_business_tenant_segment_fail(original):
    _, before_catalog, before = original
    catalog = mapped(before_catalog)
    verifier = make(catalog)
    start(verifier, catalog)
    for section, row in baseline_rows(catalog, before):
        feed(verifier, "baseline", section, before.tenant_id, row)
    with pytest.raises(ERRORS):
        feed(verifier, "baseline", "catalog", None, record_from_row(catalog.before.models[0]))


async def test_nonbusiness_tenant_sections_do_not_reopen_permission_bucket(original):
    _, before_catalog, before = original
    catalog = mapped(before_catalog)
    verifier = make(catalog)
    start(verifier, catalog)
    for section, row in baseline_rows(catalog, before):
        feed(verifier, "baseline", section, before.tenant_id, row)
    for tenant in (202, 101):
        feed(
            verifier,
            "baseline",
            "tasks",
            tenant,
            record_from_values(
                "queued_task",
                tenant_id=tenant,
                task_kind="original",
                task_id="original",
                space_id=None,
                file_id=None,
                document_id=None,
                version_id=None,
                state="original",
                configuration_digest="a" * 64,
                record_digest="b" * 64,
            ),
        )
    plan = plans.ResourceRetirementPlanner(catalog_plan=catalog).build(
        before=before, namespace_target=replace(before.mode, resource_type="knowledge_space")
    )
    for section, tenant, row in plan_rows(catalog, plan):
        feed(verifier, "plan", section, tenant, row)
    verifier.finish()
