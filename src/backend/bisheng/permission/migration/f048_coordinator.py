"""Forward-only coordinator for the one formal F048 data migration run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from bisheng.common.errcode.permission import (
    PermissionMigrationBlockedError,
    PermissionVersionConflictError,
)
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.permission.domain.services.model_policy import (
    CustomModelSelection,
    derive_permission_models,
)
from bisheng.permission.migration.f048_mode_mapper import (
    ModeMappingResult,
    map_resource_modes,
)
from bisheng.permission.migration.f048_model_mapper import (
    LegacyModelMappingResult,
    LegacyPermissionModel,
    map_legacy_models,
)
from bisheng.permission.migration.f048_source_inventory import (
    PermissionMigrationResourceDTO,
    SourceInventory,
    SourceInventorySnapshot,
    build_source_inventory,
)
from bisheng.permission.migration.f048_tuple_mapper import (
    LegacyGrantBinding,
    TupleMappingResult,
    compile_department_child_mirrors,
    map_legacy_tuples,
)

DB_BATCH_SIZE = 500
FGA_BATCH_SIZE = 90
INITIAL_CATALOG_RELEASE_KEY = "f048-initial"
FORMAL_PHASES = (
    "CREATED",
    "SOURCE_VALIDATING",
    "MODEL_PUBLISHED",
    "MIGRATING_CONTROL_PLANE",
    "MIGRATING_TUPLES",
    "RETIRING_LEGACY",
    "VERIFYING",
    "READY_TO_START",
)
_PHASE_RANK = {phase: index for index, phase in enumerate(FORMAL_PHASES)}


def _checksum(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationRunRequest:
    environment_fingerprint: str
    store_id: str
    source_model_id: str
    source_watermark: str


@dataclass(frozen=True, slots=True)
class MigrationRunState:
    id: int
    environment_fingerprint: str
    phase: str
    status: str
    store_id: str
    source_model_id: str
    target_model_id: str | None
    source_watermark: str
    version: int
    checkpoint: str | None = None
    source_checksum: str | None = None
    target_checksum: str | None = None
    lock_token: str | None = None


@dataclass(frozen=True, slots=True)
class MigrationResult:
    run_id: int
    phase: str
    status: str
    store_id: str
    source_model_id: str
    target_model_id: str
    source_checksum: str
    target_checksum: str


class MigrationSourceProviderPort(Protocol):
    async def aload_snapshot(
        self,
        *,
        expected_store_id: str,
    ) -> SourceInventorySnapshot: ...


class MigrationRunStorePort(Protocol):
    async def aget_run(
        self,
        run_id: int,
    ) -> MigrationRunState | None: ...

    async def aget_or_create(
        self,
        request: MigrationRunRequest,
    ) -> MigrationRunState: ...

    async def aload_source_snapshot(
        self,
        *,
        run_id: int,
    ) -> SourceInventorySnapshot: ...

    async def aacquire_lease(
        self,
        *,
        run_id: int,
        expected_version: int,
        lock_token: str,
    ) -> MigrationRunState | None: ...

    async def abind_target_model(
        self,
        *,
        run_id: int,
        expected_version: int,
        target_model_id: str,
    ) -> MigrationRunState: ...

    async def aput_source_items(
        self,
        *,
        run_id: int,
        items: tuple[object, ...],
    ) -> None: ...

    async def aadvance(
        self,
        *,
        run_id: int,
        expected_version: int,
        phase: str,
        status: str,
        checkpoint: str | None,
        source_checksum: str | None,
        target_checksum: str | None,
    ) -> MigrationRunState: ...


class MigrationModelPublisherPort(Protocol):
    async def aget_or_publish(
        self,
        *,
        store_id: str,
        model: dict,
        checksum: str,
    ) -> str: ...


class MigrationTargetWriterPort(Protocol):
    async def aapply_control_plane(self, **kwargs: Any) -> str: ...

    async def acontrol_plane_checksum(self) -> str: ...

    async def awrite_target_tuples(
        self,
        *,
        store_id: str,
        model_id: str,
        tuples: tuple[dict[str, str], ...],
        idempotency_key: str,
    ) -> None: ...

    async def averify_target_tuples(
        self,
        *,
        store_id: str,
        model_id: str,
        tuples: tuple[dict[str, str], ...],
    ) -> bool: ...

    async def adelete_legacy_tuples(
        self,
        *,
        store_id: str,
        tuples: tuple[dict[str, str], ...],
    ) -> None: ...

    async def aretire_legacy_configs(
        self,
        *,
        keys: tuple[str, ...],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _MigrationPlan:
    inventory: SourceInventory
    model_mapping: LegacyModelMappingResult
    tuple_mapping: TupleMappingResult
    mode_mapping: ModeMappingResult
    target_tuples: tuple[dict[str, str], ...]
    legacy_tuples: tuple[dict[str, str], ...]
    legacy_config_keys: tuple[str, ...]
    blockers: tuple[str, ...]


def _config_rows(
    snapshot: SourceInventorySnapshot,
    key: str,
) -> list[dict[str, Any]]:
    matches = [row for row in snapshot.config_sources if row.key == key]
    if not matches:
        return []
    if len(matches) != 1:
        raise ValueError(f"duplicate legacy config source: {key}")
    parsed = json.loads(matches[0].raw_value)
    if not isinstance(parsed, list) or any(not isinstance(row, dict) for row in parsed):
        raise ValueError(f"legacy config {key} must contain a list of objects")
    return parsed


def _legacy_models(
    snapshot: SourceInventorySnapshot,
) -> tuple[
    LegacyPermissionModel,
    ...,
]:
    rows = _config_rows(snapshot, "permission_relation_models_v1")
    return tuple(
        LegacyPermissionModel(
            source_key=str(row.get("id") or row.get("model_id") or row.get("key") or ""),
            name=str(row.get("name") or row.get("id") or ""),
            relation=(str(row["relation"]) if row.get("relation") is not None else None),
            permissions=tuple(str(item) for item in row.get("permissions", ())),
            is_system=bool(row.get("is_system", False)),
            permissions_explicit=bool(row.get("permissions_explicit", True)),
            active=(bool(row["active"]) if row.get("active") is not None else None),
            grantable_relations=tuple(str(item) for item in row.get("grantable_relations", ())),
        )
        for row in rows
    )


def _legacy_bindings(
    snapshot: SourceInventorySnapshot,
) -> tuple[LegacyGrantBinding, ...]:
    rows = _config_rows(
        snapshot,
        "permission_relation_model_bindings_v1",
    )
    tenant_by_resource = {
        (resource.resource_type, resource.resource_id): resource.tenant_id for resource in snapshot.resources
    }
    return tuple(
        LegacyGrantBinding(
            binding_key=str(row.get("binding_key") or row.get("key") or row.get("id") or ""),
            tenant_id=int(
                row.get("tenant_id")
                or tenant_by_resource.get(
                    (
                        str(row.get("resource_type") or ""),
                        str(row.get("resource_id") or ""),
                    ),
                    0,
                )
            ),
            resource_type=str(row.get("resource_type") or ""),
            resource_id=str(row.get("resource_id") or ""),
            relation=str(row.get("relation") or ""),
            model_source_key=str(row.get("model_id") or row.get("model_key") or ""),
            subject_type=(str(row["subject_type"]) if row.get("subject_type") is not None else None),
            subject_id=(str(row["subject_id"]) if row.get("subject_id") is not None else None),
            userset_relation=(str(row["userset_relation"]) if row.get("userset_relation") is not None else None),
            include_children=bool(row.get("include_children", False)),
            source_type=(str(row["source_type"]) if row.get("source_type") is not None else None),
            source_ref=(str(row["source_ref"]) if row.get("source_ref") is not None else None),
            protected=bool(row.get("protected", False)),
        )
        for row in rows
    )


def _compile_target_tuples(
    model_mapping: LegacyModelMappingResult,
    tuple_mapping: TupleMappingResult,
    mode_mapping: ModeMappingResult,
    resources: tuple[PermissionMigrationResourceDTO, ...],
) -> tuple[dict[str, str], ...]:
    tuples: dict[tuple[str, str, str], dict[str, str]] = {}

    def add(user: str, relation: str, object_key: str) -> None:
        tuples[(user, relation, object_key)] = {
            "user": user,
            "relation": relation,
            "object": object_key,
        }

    custom_selections = tuple(
        CustomModelSelection(
            model_key=model.model_key,
            name=model.name,
            action_codes=model.action_codes,
            active=model.active,
            allow_same_level=model.allow_same_level,
        )
        for model in model_mapping.custom_models
    )
    model_release = derive_permission_models(
        model_mapping.action_release,
        custom_models=custom_selections,
    )
    catalog_object = f"permission_catalog_release:{INITIAL_CATALOG_RELEASE_KEY}"
    add("user:*", "active", catalog_object)
    for model in model_release.models:
        model_object = f"permission_model:{model.model_key}"
        release_object = f"permission_model_release:{INITIAL_CATALOG_RELEASE_KEY}~{model.model_key}"
        add(release_object, "release", model_object)
        add(catalog_object, "catalog", release_object)
        add("user:*", "enabled_marker", release_object)
        for action_code in model.action_codes:
            add("user:*", f"{action_code}_marker", release_object)
        if "manage_permission" in model.action_codes and model.derived_level is not None:
            upper = model.derived_level if model.allow_same_level else model.derived_level - 1
            for level in range(1, max(upper, 0) + 1):
                add(
                    "user:*",
                    f"grant_level_{level}_marker",
                    release_object,
                )

    for grant in tuple_mapping.grants:
        grant_object = f"permission_grant:{grant.grant_key}"
        resource_object = f"{grant.resource_type}:{grant.resource_id}"
        add(
            f"permission_model:{grant.model_key}",
            "model",
            grant_object,
        )
        add(grant_object, "grant", resource_object)
        for assignee in grant.assignees:
            subject = f"{assignee.subject_type}:{assignee.subject_id}"
            if assignee.userset_relation:
                subject = f"{subject}#{assignee.userset_relation}"
            add(
                subject,
                ("protected_assignee" if assignee.protected else "ordinary_assignee"),
                grant_object,
            )
    for mode in mode_mapping.modes:
        resource_object = mode.resource_key
        add("user:*", f"{mode.mode.casefold()}_mode", resource_object)
        add("user:*", "permission_enabled", resource_object)
        if mode.parent_key:
            add(mode.parent_key, "parent", resource_object)
    for resource in resources:
        if resource.ownership_kind.upper() != "SYSTEM" or not resource.system_allowlisted:
            continue
        resource_object = f"{resource.resource_type}:{resource.resource_id}"
        add("user:*", "system_visible_marker", resource_object)
        if resource.resource_type in {
            "knowledge_library",
            "workflow",
            "assistant",
            "tool",
        }:
            add("user:*", "system_use_marker", resource_object)
    for row in compile_department_child_mirrors(tuple_mapping.preserved_tuples):
        add(row["user"], row["relation"], row["object"])
    return tuple(tuples[key] for key in sorted(tuples))


def _compile_plan(snapshot: SourceInventorySnapshot) -> _MigrationPlan:
    inventory = build_source_inventory(snapshot)
    if inventory.blockers:
        return _MigrationPlan(
            inventory=inventory,
            model_mapping=map_legacy_models(()),
            tuple_mapping=map_legacy_tuples(
                (),
                (),
                model_key_by_source={},
            ),
            mode_mapping=map_resource_modes((), ()),
            target_tuples=(),
            legacy_tuples=(),
            legacy_config_keys=(),
            blockers=inventory.blockers,
        )
    try:
        model_mapping = map_legacy_models(_legacy_models(snapshot))
        model_key_by_source = {
            **model_mapping.standard_references,
            **{row.legacy_source_key: row.model_key for row in model_mapping.custom_models},
        }
        tuple_mapping = map_legacy_tuples(
            snapshot.tuples,
            _legacy_bindings(snapshot),
            model_key_by_source=model_key_by_source,
            resources=snapshot.resources,
        )
        mode_mapping = map_resource_modes(
            snapshot.resources,
            tuple_mapping.grants,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PermissionMigrationBlockedError(msg=f"Invalid legacy permission source: {exc}") from exc
    blockers = tuple(
        dict.fromkeys(
            (
                *model_mapping.blockers,
                *tuple_mapping.blockers,
                *mode_mapping.blockers,
            )
        )
    )
    retired = set(tuple_mapping.retired_tuple_keys)
    legacy_tuples = tuple(
        {
            "user": row.user,
            "relation": row.relation,
            "object": row.object,
        }
        for row in snapshot.tuples
        if row.key in retired
    )
    try:
        target_tuples = _compile_target_tuples(
            model_mapping,
            tuple_mapping,
            mode_mapping,
            snapshot.resources,
        )
    except ValueError as exc:
        raise PermissionMigrationBlockedError(msg=f"Invalid preserved permission topology: {exc}") from exc
    return _MigrationPlan(
        inventory=inventory,
        model_mapping=model_mapping,
        tuple_mapping=tuple_mapping,
        mode_mapping=mode_mapping,
        target_tuples=target_tuples,
        legacy_tuples=legacy_tuples,
        legacy_config_keys=tuple(sorted({row.key for row in snapshot.config_sources})),
        blockers=blockers,
    )


def _batches(
    rows: tuple[dict[str, str], ...],
    size: int,
) -> tuple[tuple[dict[str, str], ...], ...]:
    return tuple(rows[index : index + size] for index in range(0, len(rows), size))


class F048MigrationCoordinator:
    """Execute D2/D3 once, resumably, against one existing Store."""

    def __init__(
        self,
        *,
        source_provider: MigrationSourceProviderPort,
        run_store: MigrationRunStorePort,
        model_publisher: MigrationModelPublisherPort,
        target_writer: MigrationTargetWriterPort,
    ) -> None:
        self._source_provider = source_provider
        self._run_store = run_store
        self._model_publisher = model_publisher
        self._target_writer = target_writer

    async def _advance(
        self,
        run: MigrationRunState,
        *,
        phase: str,
        status: str = "RUNNING",
        checkpoint: str | None,
        source_checksum: str | None,
        target_checksum: str | None,
    ) -> MigrationRunState:
        return await self._run_store.aadvance(
            run_id=run.id,
            expected_version=run.version,
            phase=phase,
            status=status,
            checkpoint=checkpoint,
            source_checksum=source_checksum,
            target_checksum=target_checksum,
        )

    async def _renew_lease(
        self,
        run: MigrationRunState,
        *,
        lock_token: str,
    ) -> MigrationRunState:
        leased = await self._run_store.aacquire_lease(
            run_id=run.id,
            expected_version=run.version,
            lock_token=lock_token,
        )
        if leased is None:
            raise PermissionVersionConflictError(msg="F048 migration SQL lease was lost")
        return leased

    async def migrate(
        self,
        *,
        expected_store_id: str,
        lock_token: str,
        run_id: int | None = None,
    ) -> MigrationResult:
        """Run or resume the formal migration; there is no preview path."""

        live_snapshot = await self._source_provider.aload_snapshot(
            expected_store_id=expected_store_id,
        )
        live_inventory = build_source_inventory(live_snapshot)
        environment = live_snapshot.environment
        if not environment.source_model_id:
            raise PermissionMigrationBlockedError(msg="SOURCE_MODEL_ID_MISSING")
        environment_blockers = tuple(
            blocker
            for blocker in live_inventory.blockers
            if blocker
            in {
                "SCHEMA_NOT_READY",
                "SERVICES_NOT_STOPPED",
                "STORE_ID_MISMATCH",
                "SOURCE_WATERMARK_CHANGED",
            }
        )
        if environment_blockers:
            raise PermissionMigrationBlockedError(msg=";".join(environment_blockers))
        environment_fingerprint = _checksum(
            {
                "source_model_id": environment.source_model_id,
                "store_id": environment.actual_store_id,
            }
        )
        if run_id is None:
            run = await self._run_store.aget_or_create(
                MigrationRunRequest(
                    environment_fingerprint=environment_fingerprint,
                    store_id=environment.actual_store_id,
                    source_model_id=environment.source_model_id,
                    source_watermark=environment.source_watermark,
                )
            )
        else:
            run = await self._run_store.aget_run(run_id)
            if run is None:
                raise PermissionMigrationBlockedError(msg=f"Migration run {run_id} does not exist")
        if run.store_id != expected_store_id or run.source_model_id != environment.source_model_id:
            raise PermissionVersionConflictError(msg="Formal migration run is bound to different source facts")
        has_frozen_source = bool(
            run.source_checksum and _PHASE_RANK.get(run.phase, -1) >= _PHASE_RANK["SOURCE_VALIDATING"]
        )
        if not has_frozen_source and (run.source_watermark != environment.source_watermark):
            raise PermissionVersionConflictError(msg="Formal migration source watermark changed before checkpoint")
        if run.phase not in _PHASE_RANK:
            raise PermissionMigrationBlockedError(msg=f"Unknown migration phase: {run.phase}")
        leased = await self._run_store.aacquire_lease(
            run_id=run.id,
            expected_version=run.version,
            lock_token=lock_token,
        )
        if leased is None:
            raise PermissionVersionConflictError(msg="Another F048 migration process holds the SQL lease")
        run = leased

        if has_frozen_source:
            snapshot = await self._run_store.aload_source_snapshot(run_id=run.id)
            plan = _compile_plan(snapshot)
            if plan.inventory.checksum != run.source_checksum:
                raise PermissionVersionConflictError(msg="Frozen migration source checksum changed")
        else:
            snapshot = live_snapshot
            inventory = live_inventory
            for index in range(0, len(inventory.items), DB_BATCH_SIZE):
                run = await self._renew_lease(
                    run,
                    lock_token=lock_token,
                )
                batch = inventory.items[index : index + DB_BATCH_SIZE]
                await self._run_store.aput_source_items(
                    run_id=run.id,
                    items=batch,
                )
                run = await self._advance(
                    run,
                    phase="SOURCE_VALIDATING",
                    checkpoint=f"source-items:{index + len(batch)}",
                    source_checksum=None,
                    target_checksum=None,
                )
            if inventory.blockers:
                await self._advance(
                    run,
                    phase="SOURCE_VALIDATING",
                    status="BLOCKED",
                    checkpoint="source-blocked",
                    source_checksum=inventory.checksum,
                    target_checksum=None,
                )
                raise PermissionMigrationBlockedError(msg=";".join(inventory.blockers))
            plan = _compile_plan(snapshot)
            if plan.blockers:
                await self._advance(
                    run,
                    phase="SOURCE_VALIDATING",
                    status="BLOCKED",
                    checkpoint="mapping-blocked",
                    source_checksum=plan.inventory.checksum,
                    target_checksum=None,
                )
                raise PermissionMigrationBlockedError(msg=";".join(plan.blockers))
            run = await self._advance(
                run,
                phase="SOURCE_VALIDATING",
                checkpoint="source-frozen",
                source_checksum=plan.inventory.checksum,
                target_checksum=None,
            )

        if plan.blockers:
            raise PermissionMigrationBlockedError(msg=";".join(plan.blockers))

        model = build_authorization_model_f048(
            tuple(action.code for action in plan.model_mapping.action_release.actions)
        )
        model_checksum = authorization_model_checksum(model)
        if _PHASE_RANK[run.phase] < _PHASE_RANK["MODEL_PUBLISHED"]:
            run = await self._renew_lease(
                run,
                lock_token=lock_token,
            )
            target_model_id = await self._model_publisher.aget_or_publish(
                store_id=run.store_id,
                model=model,
                checksum=model_checksum,
            )
            run = await self._run_store.abind_target_model(
                run_id=run.id,
                expected_version=run.version,
                target_model_id=target_model_id,
            )
            run = await self._advance(
                run,
                phase="MODEL_PUBLISHED",
                checkpoint="model-published",
                source_checksum=plan.inventory.checksum,
                target_checksum=model_checksum,
            )
        if not run.target_model_id:
            raise PermissionMigrationBlockedError(msg="Formal migration run has no target model")

        control_checksum = run.target_checksum or model_checksum
        if _PHASE_RANK[run.phase] < _PHASE_RANK["MIGRATING_TUPLES"]:
            run = await self._advance(
                run,
                phase="MIGRATING_CONTROL_PLANE",
                checkpoint="control-plane-start",
                source_checksum=plan.inventory.checksum,
                target_checksum=model_checksum,
            )

            async def checkpoint_control_batch(
                kind: str,
                completed: int,
            ) -> None:
                nonlocal run
                run = await self._renew_lease(
                    run,
                    lock_token=lock_token,
                )
                run = await self._advance(
                    run,
                    phase="MIGRATING_CONTROL_PLANE",
                    checkpoint=f"control:{kind}:{completed}",
                    source_checksum=plan.inventory.checksum,
                    target_checksum=model_checksum,
                )

            control_checksum = await self._target_writer.aapply_control_plane(
                run_id=run.id,
                store_id=run.store_id,
                model_id=run.target_model_id,
                action_release=plan.model_mapping.action_release,
                custom_models=plan.model_mapping.custom_models,
                grants=plan.tuple_mapping.grants,
                modes=plan.mode_mapping.modes,
                batch_size=DB_BATCH_SIZE,
                checkpoint_callback=checkpoint_control_batch,
            )
            run = await self._advance(
                run,
                phase="MIGRATING_TUPLES",
                checkpoint="control-plane-complete",
                source_checksum=plan.inventory.checksum,
                target_checksum=control_checksum,
            )

        if _PHASE_RANK[run.phase] >= _PHASE_RANK["RETIRING_LEGACY"]:
            if not run.target_checksum:
                raise PermissionMigrationBlockedError(msg="Final target checksum is missing from checkpoint")
            target_checksum = run.target_checksum
        else:
            target_checksum = _checksum(
                {
                    "control": control_checksum,
                    "tuples": plan.target_tuples,
                }
            )
        if _PHASE_RANK[run.phase] < _PHASE_RANK["RETIRING_LEGACY"]:
            for index, batch in enumerate(_batches(plan.target_tuples, FGA_BATCH_SIZE)):
                run = await self._renew_lease(
                    run,
                    lock_token=lock_token,
                )
                await self._target_writer.awrite_target_tuples(
                    store_id=run.store_id,
                    model_id=run.target_model_id,
                    tuples=batch,
                    idempotency_key=f"f048:{run.id}:target:{index}",
                )
                run = await self._advance(
                    run,
                    phase="MIGRATING_TUPLES",
                    checkpoint=f"target-tuples:{index + 1}",
                    source_checksum=plan.inventory.checksum,
                    target_checksum=control_checksum,
                )
            verified = await self._target_writer.averify_target_tuples(
                store_id=run.store_id,
                model_id=run.target_model_id,
                tuples=plan.target_tuples,
            )
            if not verified:
                raise PermissionMigrationBlockedError(msg="Target tuple verification failed")
            run = await self._advance(
                run,
                phase="RETIRING_LEGACY",
                checkpoint="target-tuples-verified",
                source_checksum=plan.inventory.checksum,
                target_checksum=target_checksum,
            )

        if _PHASE_RANK[run.phase] < _PHASE_RANK["VERIFYING"]:
            for index, batch in enumerate(_batches(plan.legacy_tuples, FGA_BATCH_SIZE)):
                run = await self._renew_lease(
                    run,
                    lock_token=lock_token,
                )
                await self._target_writer.adelete_legacy_tuples(
                    store_id=run.store_id,
                    tuples=batch,
                )
                run = await self._advance(
                    run,
                    phase="RETIRING_LEGACY",
                    checkpoint=f"legacy-tuples:{index + 1}",
                    source_checksum=plan.inventory.checksum,
                    target_checksum=target_checksum,
                )
            run = await self._renew_lease(
                run,
                lock_token=lock_token,
            )
            await self._target_writer.aretire_legacy_configs(
                keys=plan.legacy_config_keys,
            )
            run = await self._advance(
                run,
                phase="VERIFYING",
                checkpoint="legacy-retired",
                source_checksum=plan.inventory.checksum,
                target_checksum=target_checksum,
            )

        return MigrationResult(
            run_id=run.id,
            phase=run.phase,
            status=run.status,
            store_id=run.store_id,
            source_model_id=run.source_model_id,
            target_model_id=run.target_model_id,
            source_checksum=run.source_checksum or plan.inventory.checksum,
            target_checksum=run.target_checksum or target_checksum,
        )
