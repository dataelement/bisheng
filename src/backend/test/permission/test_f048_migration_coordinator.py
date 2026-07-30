"""Forward-only F048 formal migration coordinator contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.common.errcode.permission import (
    PermissionMigrationBlockedError,
    PermissionVersionConflictError,
)
from bisheng.permission.migration.f048_coordinator import (
    FORMAL_PHASES,
    F048MigrationCoordinator,
    MigrationRunRequest,
    MigrationRunState,
)
from bisheng.permission.migration.f048_source_inventory import (
    LegacyConfigSource,
    LegacyTupleSource,
    MigrationEnvironmentFacts,
    PermissionMigrationResourceDTO,
    SourceInventorySnapshot,
    build_source_inventory,
)


def _snapshot(*, schema_ready: bool = True) -> SourceInventorySnapshot:
    return SourceInventorySnapshot(
        environment=MigrationEnvironmentFacts(
            schema_ready=schema_ready,
            services_stopped=True,
            active_heartbeats=0,
            expected_store_id="store-live",
            actual_store_id="store-live",
            source_model_id="legacy-model",
            source_watermark="wm-1",
            observed_watermark="wm-1",
        ),
        config_sources=(
            LegacyConfigSource(
                key="permission_relation_models_v1",
                row_version="1",
                raw_value="[]",
            ),
            LegacyConfigSource(
                key="permission_relation_model_bindings_v1",
                row_version="1",
                raw_value="[]",
            ),
        ),
        resources=(
            PermissionMigrationResourceDTO(
                tenant_id=7,
                resource_type="workflow",
                resource_id="wf-1",
                status="ONLINE",
                owner_user_id=11,
                ownership_kind="USER",
                source_locator="workflow:wf-1",
            ),
        ),
        tuples=(
            LegacyTupleSource(
                tenant_id=7,
                user="user:11",
                relation="owner",
                object="workflow:wf-1",
            ),
        ),
    )


def test_ready_to_start_is_the_terminal_migration_run_phase() -> None:
    assert FORMAL_PHASES[-1] == "READY_TO_START"
    assert "ACTIVE" not in FORMAL_PHASES


class FakeSourceProvider:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = 0

    async def aload_snapshot(self, *, expected_store_id):
        self.calls += 1
        assert expected_store_id == "store-live"
        return self.snapshot


class FakeRunStore:
    def __init__(
        self,
        *,
        phase: str = "CREATED",
        acquire: bool = True,
        frozen_snapshot: SourceInventorySnapshot | None = None,
    ):
        self.run = None
        self.initial_phase = phase
        self.acquire = acquire
        self.frozen_snapshot = frozen_snapshot or _snapshot()
        self.items = []
        self.advances = []

    async def aget_run(self, run_id: int):
        assert run_id == 1
        return self.run

    async def aget_or_create(self, request: MigrationRunRequest):
        if self.run is None:
            frozen_checksum = (
                build_source_inventory(self.frozen_snapshot).checksum if self.initial_phase != "CREATED" else None
            )
            self.run = MigrationRunState(
                id=1,
                environment_fingerprint=request.environment_fingerprint,
                phase=self.initial_phase,
                status="RUNNING",
                store_id=request.store_id,
                source_model_id=request.source_model_id,
                target_model_id=("new-model" if self.initial_phase != "CREATED" else None),
                source_watermark=request.source_watermark,
                version=1,
                source_checksum=frozen_checksum,
                target_checksum=(
                    "t" * 64
                    if self.initial_phase
                    in {
                        "RETIRING_LEGACY",
                        "VERIFYING",
                        "READY_TO_START",
                    }
                    else None
                ),
            )
        return self.run

    async def aload_source_snapshot(self, *, run_id: int):
        assert run_id == 1
        return self.frozen_snapshot

    async def aacquire_lease(self, *, run_id, expected_version, lock_token):
        if not self.acquire:
            return None
        assert run_id == 1
        assert expected_version == self.run.version
        self.run = replace(
            self.run,
            version=self.run.version + 1,
            lock_token=lock_token,
        )
        return self.run

    async def abind_target_model(
        self,
        *,
        run_id,
        expected_version,
        target_model_id,
    ):
        assert run_id == 1
        assert expected_version == self.run.version
        self.run = replace(
            self.run,
            target_model_id=target_model_id,
            version=self.run.version + 1,
        )
        return self.run

    async def aput_source_items(self, *, run_id, items):
        assert run_id == 1
        self.items.extend(items)

    async def aadvance(
        self,
        *,
        run_id,
        expected_version,
        phase,
        status,
        checkpoint,
        source_checksum,
        target_checksum,
    ):
        assert run_id == 1
        assert expected_version == self.run.version
        self.advances.append((phase, checkpoint))
        self.run = replace(
            self.run,
            phase=phase,
            status=status,
            checkpoint=checkpoint,
            source_checksum=source_checksum,
            target_checksum=target_checksum,
            version=self.run.version + 1,
        )
        return self.run


class FakeModelPublisher:
    def __init__(self):
        self.calls = []

    async def aget_or_publish(self, *, store_id, model, checksum):
        self.calls.append((store_id, checksum, model["schema_version"]))
        return "new-model"


class FakeTargetWriter:
    def __init__(self):
        self.events = []
        self.written_tuples = []

    async def aapply_control_plane(self, **kwargs):
        self.events.append(("control", kwargs["run_id"]))
        return "c" * 64

    async def acontrol_plane_checksum(self):
        return "c" * 64

    async def awrite_target_tuples(
        self,
        *,
        store_id,
        model_id,
        tuples,
        idempotency_key,
    ):
        assert len(tuples) <= 90
        self.written_tuples.extend(tuples)
        self.events.append(("write", len(tuples), store_id, model_id))

    async def averify_target_tuples(
        self,
        *,
        store_id,
        model_id,
        tuples,
    ):
        self.events.append(("verify", len(tuples), store_id, model_id))
        return True

    async def adelete_legacy_tuples(self, *, store_id, tuples):
        assert len(tuples) <= 90
        self.events.append(("delete", len(tuples), store_id))

    async def aretire_legacy_configs(self, *, keys):
        self.events.append(("retire_config", tuple(keys)))


async def test_formal_migration_uses_same_store_batches_and_delete_after_verify():
    store = FakeRunStore()
    publisher = FakeModelPublisher()
    writer = FakeTargetWriter()
    coordinator = F048MigrationCoordinator(
        source_provider=FakeSourceProvider(_snapshot()),
        run_store=store,
        model_publisher=publisher,
        target_writer=writer,
    )

    result = await coordinator.migrate(
        expected_store_id="store-live",
        lock_token="operator-1",
    )

    assert result.phase == "VERIFYING"
    assert result.store_id == "store-live"
    assert result.target_model_id == "new-model"
    assert publisher.calls[0][0] == "store-live"
    event_names = [event[0] for event in writer.events]
    assert event_names.index("verify") < event_names.index("delete")
    assert event_names[-1] == "retire_config"
    assert all(event[2] == "store-live" for event in writer.events if event[0] in {"write", "verify"})
    assert store.items


async def test_formal_migration_writes_department_child_mirror() -> None:
    base = _snapshot()
    snapshot = replace(
        base,
        tuples=(
            *base.tuples,
            LegacyTupleSource(
                tenant_id=7,
                user="department:10",
                relation="parent",
                object="department:20",
            ),
        ),
    )
    writer = FakeTargetWriter()
    coordinator = F048MigrationCoordinator(
        source_provider=FakeSourceProvider(snapshot),
        run_store=FakeRunStore(frozen_snapshot=snapshot),
        model_publisher=FakeModelPublisher(),
        target_writer=writer,
    )

    await coordinator.migrate(
        expected_store_id="store-live",
        lock_token="operator-1",
    )

    assert {
        "user": "department:20",
        "relation": "child",
        "object": "department:10",
    } in writer.written_tuples


async def test_source_blocker_stops_before_model_or_target_writes():
    publisher = FakeModelPublisher()
    writer = FakeTargetWriter()
    coordinator = F048MigrationCoordinator(
        source_provider=FakeSourceProvider(_snapshot(schema_ready=False)),
        run_store=FakeRunStore(),
        model_publisher=publisher,
        target_writer=writer,
    )

    with pytest.raises(PermissionMigrationBlockedError):
        await coordinator.migrate(
            expected_store_id="store-live",
            lock_token="operator-1",
        )

    assert publisher.calls == []
    assert writer.events == []


async def test_resume_from_retire_phase_does_not_publish_or_rewrite_target():
    store = FakeRunStore(phase="RETIRING_LEGACY")
    publisher = FakeModelPublisher()
    writer = FakeTargetWriter()
    coordinator = F048MigrationCoordinator(
        source_provider=FakeSourceProvider(_snapshot()),
        run_store=store,
        model_publisher=publisher,
        target_writer=writer,
    )

    result = await coordinator.migrate(
        expected_store_id="store-live",
        lock_token="operator-1",
    )

    assert result.phase == "VERIFYING"
    assert publisher.calls == []
    assert [event[0] for event in writer.events] == [
        "delete",
        "retire_config",
    ]
    assert result.target_checksum == "t" * 64


async def test_resume_uses_frozen_source_after_partial_target_writes():
    frozen = _snapshot()
    changed_live = replace(
        frozen,
        tuples=(
            *frozen.tuples,
            LegacyTupleSource(
                tenant_id=7,
                user="permission_model:model-owner",
                relation="grants_model",
                object="workflow:wf-1",
            ),
        ),
    )
    store = FakeRunStore(
        phase="MIGRATING_TUPLES",
        frozen_snapshot=frozen,
    )
    await store.aget_or_create(
        MigrationRunRequest(
            environment_fingerprint="environment",
            store_id="store-live",
            source_model_id="legacy-model",
            source_watermark="wm-1",
        )
    )
    coordinator = F048MigrationCoordinator(
        source_provider=FakeSourceProvider(changed_live),
        run_store=store,
        model_publisher=FakeModelPublisher(),
        target_writer=FakeTargetWriter(),
    )

    result = await coordinator.migrate(
        expected_store_id="store-live",
        lock_token="operator-resume",
        run_id=1,
    )

    assert result.phase == "VERIFYING"
    assert any(event[0] == "write" for event in coordinator._target_writer.events)


async def test_concurrent_formal_run_fails_closed_on_sql_lease():
    coordinator = F048MigrationCoordinator(
        source_provider=FakeSourceProvider(_snapshot()),
        run_store=FakeRunStore(acquire=False),
        model_publisher=FakeModelPublisher(),
        target_writer=FakeTargetWriter(),
    )

    with pytest.raises(PermissionVersionConflictError):
        await coordinator.migrate(
            expected_store_id="store-live",
            lock_token="operator-2",
        )
