"""Durable SQL/OpenFGA adapters for the formal F048 migration."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy import func, update
from sqlmodel import col, select

from bisheng.common.errcode.permission import (
    PermissionMigrationBlockedError,
    PermissionVersionConflictError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.openfga.authorization_model_f048 import (
    MODEL_VERSION,
    authorization_model_checksum,
    required_relations_checksum,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionMigrationItem,
    PermissionMigrationRun,
    PermissionModel,
    PermissionModelAction,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.migration_repository import (
    MigrationRepository,
)
from bisheng.permission.domain.services.model_policy import (
    CustomModelSelection,
    derive_permission_models,
)
from bisheng.permission.migration.f048_coordinator import (
    INITIAL_CATALOG_RELEASE_KEY,
    MigrationRunRequest,
    MigrationRunState,
)
from bisheng.permission.migration.f048_source_inventory import (
    LegacyConfigSource,
    LegacyFailedTupleSource,
    LegacyTupleSource,
    MigrationEnvironmentFacts,
    MigrationSourceItem,
    PermissionMigrationResourceDTO,
    SourceInventorySnapshot,
)

OPENFGA_RELEASE_VERSION = "1.15.1"


def _checksum(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _run_state(row: PermissionMigrationRun) -> MigrationRunState:
    if row.id is None:
        raise RuntimeError("migration run was not flushed")
    return MigrationRunState(
        id=int(row.id),
        environment_fingerprint=row.environment_fingerprint,
        phase=row.phase,
        status=row.status,
        store_id=row.store_id,
        source_model_id=row.source_model_id,
        target_model_id=row.target_model_id,
        source_watermark=row.source_watermark or "",
        version=row.version,
        checkpoint=row.checkpoint,
        source_checksum=row.source_checksum,
        target_checksum=row.target_checksum,
        lock_token=row.lock_token,
    )


class SqlMigrationRunStore:
    """Adapt the permission migration Repository to coordinator/verifier ports."""

    def __init__(
        self,
        repository: MigrationRepository | None = None,
    ) -> None:
        self._repository = repository or MigrationRepository()

    async def aget_or_create(
        self,
        request: MigrationRunRequest,
    ) -> MigrationRunState:
        row = await self._repository.aget_or_create_run(
            PermissionMigrationRun(
                environment_fingerprint=request.environment_fingerprint,
                phase="CREATED",
                status="RUNNING",
                store_id=request.store_id,
                source_model_id=request.source_model_id,
                target_model_id=None,
                source_watermark=request.source_watermark,
            )
        )
        return _run_state(row)

    async def aget_run(
        self,
        run_id: int,
    ) -> MigrationRunState | None:
        row = await self._repository.aget_run(run_id)
        return _run_state(row) if row is not None else None

    async def aload_source_snapshot(
        self,
        *,
        run_id: int,
    ) -> SourceInventorySnapshot:
        run = await self._require_run(run_id)
        items = await self._repository.alist_source_items(run_id=run_id)
        configs: list[LegacyConfigSource] = []
        resources: list[PermissionMigrationResourceDTO] = []
        tuples: list[LegacyTupleSource] = []
        failed_tuples: list[LegacyFailedTupleSource] = []
        for item in items:
            if not item.message:
                raise PermissionMigrationBlockedError(msg=(f"Frozen source payload missing: {item.source_locator}"))
            try:
                payload = json.loads(item.message)
            except json.JSONDecodeError as exc:
                raise PermissionMigrationBlockedError(
                    exception=exc,
                    msg=(f"Frozen source payload is invalid: {item.source_locator}"),
                ) from exc
            if item.source_kind == "CONFIG":
                configs.append(
                    LegacyConfigSource(
                        key=str(payload["key"]),
                        row_version=str(payload["row_version"]),
                        raw_value=json.dumps(
                            payload["value"],
                            ensure_ascii=True,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    )
                )
            elif item.source_kind == "RESOURCE":
                payload["creator_user_ids"] = tuple(payload.get("creator_user_ids") or ())
                resources.append(PermissionMigrationResourceDTO(**payload))
            elif item.source_kind == "TUPLE":
                tuples.append(LegacyTupleSource(**payload))
            elif item.source_kind == "FAILED_TUPLE":
                failed_tuples.append(LegacyFailedTupleSource(**payload))
            else:
                raise PermissionMigrationBlockedError(msg=f"Unknown frozen source kind: {item.source_kind}")
        snapshot = SourceInventorySnapshot(
            environment=MigrationEnvironmentFacts(
                schema_ready=True,
                services_stopped=True,
                active_heartbeats=0,
                expected_store_id=run.store_id,
                actual_store_id=run.store_id,
                source_model_id=run.source_model_id,
                source_watermark=run.source_watermark,
                observed_watermark=run.source_watermark,
            ),
            config_sources=tuple(configs),
            resources=tuple(resources),
            tuples=tuple(tuples),
            failed_tuples=tuple(failed_tuples),
        )
        return snapshot

    async def aacquire_lease(
        self,
        *,
        run_id: int,
        expected_version: int,
        lock_token: str,
    ) -> MigrationRunState | None:
        acquired = await self._repository.aacquire_environment_lease(
            run_id=run_id,
            expected_version=expected_version,
            lock_token=lock_token,
            expires_at=datetime.now() + timedelta(minutes=5),
        )
        if not acquired:
            return None
        return await self._require_run(run_id)

    async def abind_target_model(
        self,
        *,
        run_id: int,
        expected_version: int,
        target_model_id: str,
    ) -> MigrationRunState:
        updated = await self._repository.abind_target_model_cas(
            run_id=run_id,
            expected_version=expected_version,
            target_model_id=target_model_id,
        )
        if not updated:
            raise PermissionVersionConflictError(msg="Target model binding changed concurrently")
        return await self._require_run(run_id)

    async def aput_source_items(
        self,
        *,
        run_id: int,
        items: tuple[object, ...],
    ) -> None:
        rows: list[PermissionMigrationItem] = []
        for item in items:
            if not isinstance(item, MigrationSourceItem):
                raise TypeError("unexpected F048 migration source item")
            rows.append(
                PermissionMigrationItem(
                    run_id=run_id,
                    tenant_id=item.tenant_id,
                    source_kind=item.source_kind,
                    source_locator=item.source_locator,
                    source_checksum=item.source_checksum,
                    status=item.status,
                    severity=item.severity,
                    difference_type=item.difference_type,
                    message=(
                        json.dumps(
                            dict(item.payload),
                            ensure_ascii=True,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    ),
                )
            )
        for index in range(0, len(rows), 500):
            await self._repository.aupsert_items(tuple(rows[index : index + 500]))

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
    ) -> MigrationRunState:
        updated = await self._repository.aupdate_run_state_cas(
            run_id=run_id,
            expected_version=expected_version,
            phase=phase,
            status=status,
            checkpoint=checkpoint,
            source_checksum=source_checksum,
            target_checksum=target_checksum,
        )
        if not updated:
            raise PermissionVersionConflictError(msg="Migration phase changed concurrently")
        return await self._require_run(run_id)

    async def amark_ready(
        self,
        *,
        run_id: int,
        expected_version: int,
        evidence_checksum: str,
    ) -> MigrationRunState:
        run = await self._require_run(run_id)
        if not run.target_model_id:
            raise PermissionMigrationBlockedError(msg="Migration run has no target model")
        async with get_async_db_session() as session:
            async with session.begin():
                target_release = (
                    (
                        await session.execute(
                            select(AuthorizationModelRelease).where(
                                AuthorizationModelRelease.store_id == run.store_id,
                                AuthorizationModelRelease.model_id == run.target_model_id,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if target_release is None:
                    raise PermissionMigrationBlockedError(msg="Target authorization model release is missing")
                result = await session.execute(
                    update(PermissionMigrationRun)
                    .where(
                        PermissionMigrationRun.id == run_id,
                        PermissionMigrationRun.version == expected_version,
                    )
                    .values(
                        phase="READY_TO_START",
                        status="COMPLETED",
                        checkpoint="d4-verified",
                        source_checksum=run.source_checksum,
                        target_checksum=run.target_checksum,
                        report_checksum=evidence_checksum,
                        version=expected_version + 1,
                        update_time=func.now(),
                    )
                )
                if not result.rowcount:
                    raise PermissionVersionConflictError(msg="Migration verification changed concurrently")
                await session.execute(
                    update(AuthorizationModelRelease)
                    .where(
                        AuthorizationModelRelease.store_id == run.store_id,
                        AuthorizationModelRelease.model_id == run.target_model_id,
                    )
                    .values(
                        status="ACTIVE",
                        activated_at=func.now(),
                        retired_at=None,
                        update_time=func.now(),
                    )
                )
                if run.source_model_id != run.target_model_id:
                    await session.execute(
                        update(AuthorizationModelRelease)
                        .where(
                            AuthorizationModelRelease.store_id == run.store_id,
                            AuthorizationModelRelease.model_id == run.source_model_id,
                        )
                        .values(
                            status="RETIRED",
                            retired_at=func.now(),
                            update_time=func.now(),
                        )
                    )
        return await self._require_run(run_id)

    async def _require_run(self, run_id: int) -> MigrationRunState:
        row = await self._repository.aget_run(run_id)
        if row is None:
            raise PermissionMigrationBlockedError(msg=f"Migration run {run_id} does not exist")
        return _run_state(row)


class OpenFGAMigrationModelPublisher:
    """Publish or reuse the one immutable F048 model in the existing Store."""

    def __init__(
        self,
        *,
        source_client: FGAClient,
        environment: str,
        predecessor_model_id: str,
    ) -> None:
        self._source_client = source_client
        self._environment = environment[:64]
        self._predecessor_model_id = predecessor_model_id

    async def aget_or_publish(
        self,
        *,
        store_id: str,
        model: dict,
        checksum: str,
    ) -> str:
        if store_id != self._source_client.store_id:
            raise PermissionMigrationBlockedError(msg="STORE_ID_MISMATCH")
        if authorization_model_checksum(model) != checksum:
            raise PermissionMigrationBlockedError(msg="AUTHORIZATION_MODEL_CHECKSUM_MISMATCH")
        existing = await self._find_sql_release(store_id, checksum)
        if existing is not None:
            return existing.model_id

        model_id = await self._find_remote_model(checksum)
        if model_id is None:
            model_id = await self._source_client.write_authorization_model(model)
        await self._persist_release(
            store_id=store_id,
            model_id=model_id,
            model=model,
            checksum=checksum,
        )
        return model_id

    async def _find_sql_release(
        self,
        store_id: str,
        checksum: str,
    ) -> AuthorizationModelRelease | None:
        async with get_async_db_session() as session:
            statement = (
                select(AuthorizationModelRelease)
                .where(
                    AuthorizationModelRelease.environment == self._environment,
                    AuthorizationModelRelease.store_id == store_id,
                    AuthorizationModelRelease.model_checksum == checksum,
                )
                .order_by(AuthorizationModelRelease.id)
            )
            return (await session.execute(statement)).scalars().first()

    async def _find_remote_model(self, checksum: str) -> str | None:
        for raw in await self._source_client.list_authorization_models():
            normalized = {
                "schema_version": raw.get("schema_version"),
                "type_definitions": raw.get("type_definitions"),
            }
            if raw.get("conditions"):
                normalized["conditions"] = raw["conditions"]
            if (
                normalized["schema_version"]
                and normalized["type_definitions"]
                and authorization_model_checksum(normalized) == checksum
            ):
                model_id = raw.get("id") or raw.get("authorization_model_id")
                if model_id:
                    return str(model_id)
        return None

    async def _persist_release(
        self,
        *,
        store_id: str,
        model_id: str,
        model: dict,
        checksum: str,
    ) -> None:
        existing = await self._find_sql_release(store_id, checksum)
        if existing is not None:
            if existing.model_id != model_id:
                raise PermissionVersionConflictError(msg="Model checksum is bound to another model ID")
            return
        async with get_async_db_session() as session:
            async with session.begin():
                session.add(
                    AuthorizationModelRelease(
                        environment=self._environment,
                        store_id=store_id,
                        model_version=MODEL_VERSION,
                        model_id=model_id,
                        predecessor_model_id=self._predecessor_model_id,
                        model_checksum=checksum,
                        required_relations_checksum=(required_relations_checksum(model)),
                        openfga_version=OPENFGA_RELEASE_VERSION,
                        status="STAGED",
                    )
                )


class SqlOpenFGAMigrationTargetWriter:
    """Idempotently materialize the F048 control plane and tuple graph."""

    def __init__(
        self,
        *,
        source_client: FGAClient,
    ) -> None:
        self._source_client = source_client
        self._target_clients: dict[str, FGAClient] = {}
        self._tuple_cache: set[tuple[str, str, str]] | None = None

    async def aapply_control_plane(self, **kwargs: Any) -> str:
        batch_size = int(kwargs["batch_size"])
        if not 1 <= batch_size <= 500:
            raise ValueError("control-plane batch size must be 1..500")
        model_id = str(kwargs["model_id"])
        action_release = kwargs["action_release"]
        custom_models = tuple(kwargs["custom_models"])
        grants = tuple(kwargs["grants"])
        modes = tuple(kwargs["modes"])
        checkpoint_callback = kwargs.get("checkpoint_callback")
        auth_release = await self._authorization_release(model_id)
        custom_selections = tuple(
            CustomModelSelection(
                model_key=model.model_key,
                name=model.name,
                action_codes=model.action_codes,
                active=model.active,
                allow_same_level=model.allow_same_level,
            )
            for model in custom_models
        )
        model_release = derive_permission_models(
            action_release,
            custom_models=custom_selections,
        )
        catalog_checksum = _checksum(
            {
                "actions": action_release.checksum,
                "models": model_release.checksum,
            }
        )
        release_id = await self._ensure_catalog(
            run_id=int(kwargs["run_id"]),
            auth_release_id=int(auth_release.id),
            checksum=catalog_checksum,
            action_release=action_release,
            model_release=model_release,
            custom_models=custom_models,
        )
        if checkpoint_callback is not None:
            await checkpoint_callback("catalog", 1)
        for index in range(0, len(grants), batch_size):
            if checkpoint_callback is not None:
                await checkpoint_callback("grants", index)
            await self._upsert_grants(grants[index : index + batch_size])
        for index in range(0, len(modes), batch_size):
            if checkpoint_callback is not None:
                await checkpoint_callback("modes", index)
            await self._upsert_modes(modes[index : index + batch_size])
        control_checksum = await self.acontrol_plane_checksum()
        async with get_async_db_session() as session:
            async with session.begin():
                await session.execute(
                    update(PermissionCatalogRelease)
                    .where(PermissionCatalogRelease.id == release_id)
                    .values(
                        status="CURRENT",
                        write_fenced=False,
                        commit_checksum=control_checksum,
                        published_at=func.now(),
                    )
                )
        return control_checksum

    async def acontrol_plane_checksum(self) -> str:
        """Checksum normalized persisted rows used by D4 verification."""

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                release = (
                    (
                        await session.execute(
                            select(PermissionCatalogRelease).where(
                                PermissionCatalogRelease.release_key == INITIAL_CATALOG_RELEASE_KEY
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if release is None or release.id is None:
                    raise PermissionMigrationBlockedError(msg="TARGET_CATALOG_MISSING")
                authorization_release = await session.get(
                    AuthorizationModelRelease,
                    release.required_authorization_model_release_id,
                )
                if authorization_release is None:
                    raise PermissionMigrationBlockedError(msg="TARGET_MODEL_RELEASE_MISSING")
                actions = list(
                    (
                        await session.execute(
                            select(PermissionAction)
                            .where(PermissionAction.catalog_release_id == release.id)
                            .order_by(PermissionAction.code)
                        )
                    )
                    .scalars()
                    .all()
                )
                action_ids = [int(row.id) for row in actions if row.id]
                scopes = (
                    list(
                        (
                            await session.execute(
                                select(PermissionActionResourceScope)
                                .where(col(PermissionActionResourceScope.action_id).in_(action_ids))
                                .order_by(
                                    PermissionActionResourceScope.action_id,
                                    PermissionActionResourceScope.resource_type,
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if action_ids
                    else []
                )
                models = list(
                    (
                        await session.execute(
                            select(PermissionModel)
                            .where(PermissionModel.catalog_release_id == release.id)
                            .order_by(PermissionModel.model_key)
                        )
                    )
                    .scalars()
                    .all()
                )
                model_ids = [int(row.id) for row in models if row.id]
                model_actions = (
                    list(
                        (
                            await session.execute(
                                select(PermissionModelAction)
                                .where(col(PermissionModelAction.model_id).in_(model_ids))
                                .order_by(
                                    PermissionModelAction.model_id,
                                    PermissionModelAction.action_id,
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if model_ids
                    else []
                )
                grants = list(
                    (
                        await session.execute(
                            select(PermissionGrant).order_by(
                                PermissionGrant.tenant_id,
                                PermissionGrant.resource_type,
                                PermissionGrant.resource_id,
                                PermissionGrant.model_key,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                grant_ids = [int(row.id) for row in grants if row.id]
                assignees = (
                    list(
                        (
                            await session.execute(
                                select(PermissionGrantAssignee)
                                .where(col(PermissionGrantAssignee.grant_id).in_(grant_ids))
                                .order_by(
                                    PermissionGrantAssignee.tenant_id,
                                    PermissionGrantAssignee.grant_id,
                                    PermissionGrantAssignee.source_fingerprint,
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if grant_ids
                    else []
                )
                modes = list(
                    (
                        await session.execute(
                            select(ResourcePermissionMode).order_by(
                                ResourcePermissionMode.tenant_id,
                                ResourcePermissionMode.resource_type,
                                ResourcePermissionMode.resource_id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
        action_code_by_id = {int(row.id): row.code for row in actions if row.id is not None}
        model_key_by_id = {int(row.id): row.model_key for row in models if row.id is not None}
        grant_key_by_id = {
            int(row.id): (
                row.tenant_id,
                row.resource_type,
                row.resource_id,
                row.model_key,
            )
            for row in grants
            if row.id is not None
        }
        payload = {
            "release": {
                "release_key": release.release_key,
                "checksum": release.checksum,
                "authorization_model": (
                    authorization_release.store_id,
                    authorization_release.model_id,
                    authorization_release.model_checksum,
                ),
            },
            "actions": [
                (
                    row.code,
                    row.name,
                    row.level,
                    row.active,
                    row.sort_order,
                )
                for row in actions
            ],
            "scopes": sorted(
                (
                    action_code_by_id[int(row.action_id)],
                    row.resource_type,
                )
                for row in scopes
            ),
            "models": [
                (
                    row.model_key,
                    row.name,
                    row.kind,
                    row.config_scope,
                    row.derived_level,
                    row.active,
                    row.allow_same_level,
                    row.legacy_source_key,
                )
                for row in models
            ],
            "model_actions": sorted(
                (
                    model_key_by_id[int(row.model_id)],
                    action_code_by_id[int(row.action_id)],
                )
                for row in model_actions
            ),
            "grants": [
                (
                    row.tenant_id,
                    row.resource_type,
                    row.resource_id,
                    row.model_key,
                    row.state,
                    row.projection_state,
                )
                for row in grants
            ],
            "assignees": sorted(
                (
                    row.tenant_id,
                    grant_key_by_id[int(row.grant_id)],
                    row.subject_type,
                    row.subject_id,
                    row.userset_relation,
                    row.include_children,
                    row.source_type,
                    row.source_ref,
                    row.source_fingerprint,
                    row.projected_subject,
                    row.protected,
                    row.state,
                )
                for row in assignees
            ),
            "modes": [
                (
                    row.tenant_id,
                    row.resource_type,
                    row.resource_id,
                    row.mode,
                    row.parent_type,
                    row.parent_id,
                    row.projection_state,
                )
                for row in modes
            ],
        }
        return _checksum(payload)

    async def _authorization_release(
        self,
        model_id: str,
    ) -> AuthorizationModelRelease:
        async with get_async_db_session() as session:
            statement = select(AuthorizationModelRelease).where(
                AuthorizationModelRelease.store_id == self._source_client.store_id,
                AuthorizationModelRelease.model_id == model_id,
            )
            row = (await session.execute(statement)).scalars().first()
        if row is None or row.id is None:
            raise PermissionMigrationBlockedError(msg="TARGET_MODEL_RELEASE_MISSING")
        return row

    async def _ensure_catalog(
        self,
        *,
        run_id: int,
        auth_release_id: int,
        checksum: str,
        action_release,
        model_release,
        custom_models: tuple[Any, ...],
    ) -> int:
        legacy_by_key = {row.model_key: row.legacy_source_key for row in custom_models}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                async with session.begin():
                    statement = select(PermissionCatalogRelease).where(
                        PermissionCatalogRelease.release_key == INITIAL_CATALOG_RELEASE_KEY
                    )
                    release = (await session.execute(statement)).scalars().first()
                    if release is None:
                        release = PermissionCatalogRelease(
                            release_key=INITIAL_CATALOG_RELEASE_KEY,
                            version=1,
                            status="PROJECTING",
                            write_fenced=True,
                            predecessor_id=None,
                            required_authorization_model_release_id=(auth_release_id),
                            draft_owner_id=0,
                            idempotency_key=f"f048-migration-{run_id}",
                            checksum=checksum,
                        )
                        session.add(release)
                        await session.flush()
                    elif (
                        release.checksum != checksum
                        or release.required_authorization_model_release_id != auth_release_id
                    ):
                        raise PermissionVersionConflictError(msg="Initial F048 Catalog differs from checkpoint")
                    if release.id is None:
                        raise RuntimeError("Catalog release was not flushed")
                    action_ids: dict[str, int] = {}
                    for action in action_release.actions:
                        action_row = (
                            (
                                await session.execute(
                                    select(PermissionAction).where(
                                        PermissionAction.catalog_release_id == release.id,
                                        PermissionAction.code == action.code,
                                    )
                                )
                            )
                            .scalars()
                            .first()
                        )
                        if action_row is None:
                            action_row = PermissionAction(
                                catalog_release_id=release.id,
                                code=action.code,
                                name=action.name,
                                level=action.level,
                                active=action.active,
                                sort_order=action.sort_order,
                            )
                            session.add(action_row)
                            await session.flush()
                        if action_row.id is None:
                            raise RuntimeError("Action row was not flushed")
                        action_ids[action.code] = int(action_row.id)
                        for resource_type in sorted(action.resource_types):
                            exists = (
                                await session.execute(
                                    select(PermissionActionResourceScope.id).where(
                                        PermissionActionResourceScope.action_id == action_row.id,
                                        PermissionActionResourceScope.resource_type == resource_type,
                                    )
                                )
                            ).scalar_one_or_none()
                            if exists is None:
                                session.add(
                                    PermissionActionResourceScope(
                                        action_id=action_row.id,
                                        resource_type=resource_type,
                                    )
                                )
                    for model in model_release.models:
                        model_row = (
                            (
                                await session.execute(
                                    select(PermissionModel).where(
                                        PermissionModel.catalog_release_id == release.id,
                                        PermissionModel.model_key == model.model_key,
                                    )
                                )
                            )
                            .scalars()
                            .first()
                        )
                        if model_row is None:
                            model_row = PermissionModel(
                                catalog_release_id=release.id,
                                model_key=model.model_key,
                                normalized_name=model.name.casefold(),
                                name=model.name,
                                kind=model.kind,
                                config_scope=model.config_scope,
                                derived_level=model.derived_level,
                                active=model.active,
                                allow_same_level=model.allow_same_level,
                                legacy_source_key=legacy_by_key.get(model.model_key),
                            )
                            session.add(model_row)
                            await session.flush()
                        if model_row.id is None:
                            raise RuntimeError("Model row was not flushed")
                        for action_code in model.action_codes:
                            exists = (
                                await session.execute(
                                    select(PermissionModelAction.id).where(
                                        PermissionModelAction.model_id == model_row.id,
                                        PermissionModelAction.action_id == action_ids[action_code],
                                    )
                                )
                            ).scalar_one_or_none()
                            if exists is None:
                                session.add(
                                    PermissionModelAction(
                                        model_id=model_row.id,
                                        action_id=action_ids[action_code],
                                    )
                                )
                    return int(release.id)

    async def _upsert_grants(self, grants: tuple[Any, ...]) -> None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                async with session.begin():
                    for mapped in grants:
                        statement = select(PermissionGrant).where(
                            PermissionGrant.tenant_id == mapped.tenant_id,
                            PermissionGrant.resource_type == mapped.resource_type,
                            PermissionGrant.resource_id == mapped.resource_id,
                            PermissionGrant.model_key == mapped.model_key,
                        )
                        grant = (await session.execute(statement)).scalars().first()
                        if grant is None:
                            grant = PermissionGrant(
                                tenant_id=mapped.tenant_id,
                                resource_type=mapped.resource_type,
                                resource_id=mapped.resource_id,
                                model_key=mapped.model_key,
                                state="ACTIVE",
                                projection_state="CURRENT",
                            )
                            session.add(grant)
                            await session.flush()
                        if grant.id is None:
                            raise RuntimeError("Grant row was not flushed")
                        for assignee in mapped.assignees:
                            source_locator = (f"migration:{assignee.source_type}:{assignee.source_ref}")[:256]
                            projected = f"{assignee.subject_type}:{assignee.subject_id}"
                            if assignee.userset_relation:
                                projected += f"#{assignee.userset_relation}"
                            existing = (
                                (
                                    await session.execute(
                                        select(PermissionGrantAssignee).where(
                                            PermissionGrantAssignee.tenant_id == mapped.tenant_id,
                                            PermissionGrantAssignee.grant_id == grant.id,
                                            PermissionGrantAssignee.source_fingerprint == assignee.source_checksum,
                                        )
                                    )
                                )
                                .scalars()
                                .first()
                            )
                            if existing is None:
                                session.add(
                                    PermissionGrantAssignee(
                                        tenant_id=mapped.tenant_id,
                                        grant_id=grant.id,
                                        subject_type=assignee.subject_type,
                                        subject_id=assignee.subject_id,
                                        userset_relation=(assignee.userset_relation),
                                        include_children=(assignee.include_children),
                                        source_type=assignee.source_type,
                                        source_ref=assignee.source_ref[:256],
                                        source_locator=source_locator,
                                        source_fingerprint=(assignee.source_checksum),
                                        projected_subject=projected,
                                        protected=assignee.protected,
                                        state="ACTIVE",
                                    )
                                )

    async def _upsert_modes(self, modes: tuple[Any, ...]) -> None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                async with session.begin():
                    for mapped in modes:
                        statement = select(ResourcePermissionMode).where(
                            ResourcePermissionMode.tenant_id == mapped.tenant_id,
                            ResourcePermissionMode.resource_type == mapped.resource_type,
                            ResourcePermissionMode.resource_id == mapped.resource_id,
                        )
                        row = (await session.execute(statement)).scalars().first()
                        if row is None:
                            session.add(
                                ResourcePermissionMode(
                                    tenant_id=mapped.tenant_id,
                                    resource_type=mapped.resource_type,
                                    resource_id=mapped.resource_id,
                                    mode=mapped.mode,
                                    parent_type=mapped.parent_type,
                                    parent_id=mapped.parent_id,
                                    projection_state="CURRENT",
                                )
                            )
                        elif (
                            row.mode != mapped.mode
                            or row.parent_type != mapped.parent_type
                            or row.parent_id != mapped.parent_id
                        ):
                            raise PermissionVersionConflictError(
                                msg=(f"Resource mode differs from migration checkpoint: {mapped.resource_key}")
                            )

    async def awrite_target_tuples(
        self,
        *,
        store_id: str,
        model_id: str,
        tuples: tuple[dict[str, str], ...],
        idempotency_key: str,
    ) -> None:
        client = self._target_client(store_id, model_id)
        existing = await self._tuples()
        missing = [row for row in tuples if self._tuple_identity(row) not in existing]
        if missing:
            FGAClient.validate_business_mutation_size(len(missing))
            await client.write_tuples(writes=missing)
            existing.update(self._tuple_identity(row) for row in missing)
        await self._persist_target_tuple_items(
            idempotency_key=idempotency_key,
            tuples=tuples,
        )

    async def averify_target_tuples(
        self,
        *,
        store_id: str,
        model_id: str,
        tuples: tuple[dict[str, str], ...],
    ) -> bool:
        client = self._target_client(store_id, model_id)
        actual = {self._tuple_identity(row) for row in await client.read_tuples(consistency="HIGHER_CONSISTENCY")}
        if any(self._tuple_identity(row) not in actual for row in tuples):
            return False
        for index in range(0, len(tuples), 100):
            checks = list(tuples[index : index + 100])
            results = await client.batch_check(
                checks,
                consistency="HIGHER_CONSISTENCY",
            )
            if len(results) != len(checks) or not all(results):
                return False
        return True

    async def adelete_legacy_tuples(
        self,
        *,
        store_id: str,
        tuples: tuple[dict[str, str], ...],
    ) -> None:
        if store_id != self._source_client.store_id:
            raise PermissionMigrationBlockedError(msg="STORE_ID_MISMATCH")
        existing = await self._tuples()
        present = [row for row in tuples if self._tuple_identity(row) in existing]
        if present:
            await self._source_client.delete_tuples_store_scoped(present)
            existing.difference_update(self._tuple_identity(row) for row in present)

    async def aclose(self) -> None:
        for client in self._target_clients.values():
            await client.close()
        self._target_clients.clear()

    @staticmethod
    async def _persist_target_tuple_items(
        *,
        idempotency_key: str,
        tuples: tuple[dict[str, str], ...],
    ) -> None:
        parts = idempotency_key.split(":")
        if len(parts) < 3 or parts[0] != "f048" or not parts[1].isdigit():
            raise ValueError("invalid F048 target tuple idempotency key")
        run_id = int(parts[1])
        repository = MigrationRepository()
        items: list[PermissionMigrationItem] = []
        for row in tuples:
            canonical = json.dumps(
                row,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            tuple_checksum = sha256(canonical.encode("utf-8")).hexdigest()
            items.append(
                PermissionMigrationItem(
                    run_id=run_id,
                    tenant_id=None,
                    source_kind="TARGET_TUPLE",
                    source_locator=f"target_tuple:{tuple_checksum}",
                    source_checksum=tuple_checksum,
                    target_kind="FGA_TUPLE",
                    target_id=tuple_checksum[:64],
                    target_checksum=tuple_checksum,
                    status="MIGRATED",
                    severity="INFO",
                    message=canonical[:1000],
                )
            )
        await repository.aupsert_items(tuple(items))

    def _target_client(self, store_id: str, model_id: str) -> FGAClient:
        if store_id != self._source_client.store_id:
            raise PermissionMigrationBlockedError(msg="STORE_ID_MISMATCH")
        return self._target_clients.setdefault(
            model_id,
            self._source_client.for_model(model_id),
        )

    async def _tuples(self) -> set[tuple[str, str, str]]:
        if self._tuple_cache is None:
            self._tuple_cache = {self._tuple_identity(row) for row in await self._source_client.read_tuples()}
        return self._tuple_cache

    @staticmethod
    def _tuple_identity(row: dict[str, str]) -> tuple[str, str, str]:
        return (row["user"], row["relation"], row["object"])
