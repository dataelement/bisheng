"""Contracts for the forward-only F048 source inventory."""

from __future__ import annotations

from bisheng.permission.migration.f048_source_inventory import (
    LegacyConfigSource,
    LegacyFailedTupleSource,
    LegacyTupleSource,
    MigrationEnvironmentFacts,
    PermissionMigrationResourceDTO,
    SourceInventorySnapshot,
    build_source_inventory,
)


def _environment(**overrides) -> MigrationEnvironmentFacts:
    values = {
        "schema_ready": True,
        "services_stopped": True,
        "active_heartbeats": 0,
        "expected_store_id": "store-live",
        "actual_store_id": "store-live",
        "source_model_id": "legacy-model",
        "source_watermark": "wm-001",
        "observed_watermark": "wm-001",
    }
    values.update(overrides)
    return MigrationEnvironmentFacts(**values)


def _resource(**overrides) -> PermissionMigrationResourceDTO:
    values = {
        "tenant_id": 7,
        "resource_type": "workflow",
        "resource_id": "wf-1",
        "status": "ONLINE",
        "owner_user_id": 11,
        "ownership_kind": "USER",
        "source_locator": "workflow:wf-1",
    }
    values.update(overrides)
    return PermissionMigrationResourceDTO(**values)


def test_inventory_is_deterministic_and_keeps_normalized_source_facts():
    snapshot = SourceInventorySnapshot(
        environment=_environment(),
        config_sources=(
            LegacyConfigSource(
                key="permission_relation_models_v1",
                row_version="4",
                raw_value='[{"id":"custom-a","name":"A","permissions":["edit_app"]}]',
            ),
            LegacyConfigSource(
                key="permission_relation_model_bindings_v1",
                row_version="8",
                raw_value="[]",
            ),
        ),
        resources=(_resource(),),
        tuples=(
            LegacyTupleSource(
                tenant_id=7,
                user="user:11",
                relation="owner",
                object="workflow:wf-1",
            ),
        ),
    )

    first = build_source_inventory(snapshot)
    second = build_source_inventory(snapshot)

    assert first.checksum == second.checksum
    assert first.blockers == ()
    assert {item.source_kind for item in first.items} >= {
        "CONFIG",
        "RESOURCE",
        "TUPLE",
    }
    assert first.environment.store_id == "store-live"
    assert first.environment.source_watermark == "wm-001"


def test_inventory_blocks_before_scanning_when_d1_freeze_or_store_is_invalid():
    snapshot = SourceInventorySnapshot(
        environment=_environment(
            schema_ready=False,
            services_stopped=False,
            active_heartbeats=2,
            actual_store_id="other-store",
            observed_watermark="wm-002",
        ),
    )

    inventory = build_source_inventory(snapshot)

    assert set(inventory.blockers) == {
        "SCHEMA_NOT_READY",
        "SERVICES_NOT_STOPPED",
        "STORE_ID_MISMATCH",
        "SOURCE_WATERMARK_CHANGED",
    }
    assert inventory.items == ()


def test_inventory_classifies_corrupt_config_stale_cross_tenant_and_failed_tuple():
    snapshot = SourceInventorySnapshot(
        environment=_environment(),
        config_sources=(
            LegacyConfigSource(
                key="permission_relation_models_v1",
                row_version="4",
                raw_value="{broken",
            ),
        ),
        resources=(_resource(),),
        tuples=(
            LegacyTupleSource(
                tenant_id=8,
                user="user:11",
                relation="owner",
                object="workflow:wf-1",
            ),
            LegacyTupleSource(
                tenant_id=7,
                user="user:12",
                relation="viewer",
                object="workflow:missing",
            ),
        ),
        failed_tuples=(
            LegacyFailedTupleSource(
                locator="failed_tuple:9",
                status="pending",
                tuple_key="user:11|owner|workflow:wf-1",
            ),
        ),
    )

    inventory = build_source_inventory(snapshot)
    difference_types = {item.difference_type for item in inventory.items}

    assert {
        "CORRUPT_CONFIG_JSON",
        "CROSS_TENANT_TUPLE",
        "STALE_RESOURCE_TUPLE",
        "UNRESOLVED_FAILED_TUPLE",
    } <= difference_types
    assert inventory.blocker_count == 3
    stale = next(item for item in inventory.items if item.difference_type == "STALE_RESOURCE_TUPLE")
    assert stale.severity == "INFO"


def test_inventory_accepts_evidence_reconciled_failed_tuple():
    snapshot = SourceInventorySnapshot(
        environment=_environment(),
        failed_tuples=(
            LegacyFailedTupleSource(
                locator="failed_tuple:9",
                status="dead",
                tuple_key="user:11|owner|workflow:wf-1",
                resolution="SOURCE_MODEL_REJECTED",
                error_category="MODEL_VALIDATION_REJECTED",
            ),
        ),
    )

    inventory = build_source_inventory(snapshot)

    assert inventory.blockers == ()
    assert inventory.items[0].difference_type is None


def test_inventory_rejects_invalid_owner_and_parent_facts_without_guessing():
    snapshot = SourceInventorySnapshot(
        environment=_environment(),
        resources=(
            _resource(owner_user_id=0),
            _resource(
                resource_type="knowledge_file",
                resource_id="file-1",
                source_locator="knowledge_file:file-1",
                parent_type=None,
                parent_id=None,
            ),
        ),
    )

    inventory = build_source_inventory(snapshot)

    assert {item.difference_type for item in inventory.items} >= {
        "INVALID_CANONICAL_OWNER",
        "MISSING_CANONICAL_PARENT",
    }
