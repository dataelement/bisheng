"""Live source acquisition for the explicit F048 maintenance script."""

from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from typing import Any, Protocol

from loguru import logger
from sqlalchemy import func, inspect
from sqlmodel import col, select

from bisheng.common.models.config import Config
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.runtime_heartbeat import list_runtime_heartbeats
from bisheng.database.models.failed_tuple import FailedTuple
from bisheng.permission.domain.models import PermissionMigrationRun
from bisheng.permission.migration.f048_source_inventory import (
    MIGRATED_RESOURCE_TYPES,
    LegacyConfigSource,
    LegacyFailedTupleSource,
    LegacyTupleSource,
    MigrationEnvironmentFacts,
    PermissionMigrationResourceDTO,
    PermissionMigrationSourcePort,
    SourceInventorySnapshot,
)

LEGACY_CONFIG_KEYS = (
    "permission_relation_models_v1",
    "permission_relation_model_bindings_v1",
)


def _canonical_checksum(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


class DashboardMigrationMaintenancePort(Protocol):
    """Business-owned pre-migration maintenance used by the script layer."""

    async def abackfill_custom_dashboard_tenants(self) -> int: ...


class LegacyIdentityStatePort(Protocol):
    """Resolve canonical business state for legacy identity tuples."""

    async def aresolve_expected_states(
        self,
        tuple_identities: tuple[tuple[str, str, str], ...],
    ) -> dict[tuple[str, str, str], bool]: ...


class LiveMigrationSourceProvider:
    """Acquire frozen business DTOs and Store facts without domain leakage."""

    def __init__(
        self,
        *,
        source_client: FGAClient,
        actual_store_id: str,
        source_model_id: str,
        sources: tuple[PermissionMigrationSourcePort, ...],
        dashboard_repository: DashboardMigrationMaintenancePort,
        identity_state_source: LegacyIdentityStatePort | None = None,
    ) -> None:
        self._source_client = source_client
        self._actual_store_id = actual_store_id
        self._source_model_id = source_model_id
        self._dashboard_repository = dashboard_repository
        self._sources = sources
        self._identity_state_source = identity_state_source

    async def aload_snapshot(
        self,
        *,
        expected_store_id: str,
    ) -> SourceInventorySnapshot:
        schema_ready = await self._schema_ready()
        active_heartbeats = await self._active_heartbeats()
        services_stopped = active_heartbeats == 0
        preconditions_ready = (
            schema_ready
            and services_stopped
            and bool(expected_store_id)
            and expected_store_id == self._actual_store_id
            and bool(self._source_model_id)
        )
        if not preconditions_ready:
            marker = "not-scanned"
            return SourceInventorySnapshot(
                environment=MigrationEnvironmentFacts(
                    schema_ready=schema_ready,
                    services_stopped=services_stopped,
                    active_heartbeats=active_heartbeats,
                    expected_store_id=expected_store_id,
                    actual_store_id=self._actual_store_id,
                    source_model_id=self._source_model_id,
                    source_watermark=marker,
                    observed_watermark=marker,
                )
            )

        await self._dashboard_repository.abackfill_custom_dashboard_tenants()
        first = await self._load_sources()
        source_watermark = self._watermark(first)
        second = await self._load_sources()
        observed_watermark = self._watermark(second)
        active_heartbeats = await self._active_heartbeats()
        return SourceInventorySnapshot(
            environment=MigrationEnvironmentFacts(
                schema_ready=True,
                services_stopped=active_heartbeats == 0,
                active_heartbeats=active_heartbeats,
                expected_store_id=expected_store_id,
                actual_store_id=self._actual_store_id,
                source_model_id=self._source_model_id,
                source_watermark=source_watermark,
                observed_watermark=observed_watermark,
            ),
            config_sources=first["configs"],
            resources=first["resources"],
            tuples=first["tuples"],
            failed_tuples=first["failed_tuples"],
        )

    async def _schema_ready(self) -> bool:
        try:
            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    await session.execute(select(func.count()).select_from(PermissionMigrationRun))
                    connection = await session.connection()
                    dashboard_columns = await connection.run_sync(
                        lambda sync_connection: {
                            str(column["name"]).casefold()
                            for column in inspect(sync_connection).get_columns("dashboard")
                        }
                    )
                    if "tenant_id" not in dashboard_columns:
                        return False
        except Exception:
            logger.exception("Failed to verify the F048 migration schema gate")
            return False
        return True

    @staticmethod
    async def _active_heartbeats() -> int:
        try:
            return len(await list_runtime_heartbeats())
        except Exception:
            # The formal migration must prove stop-state; Redis uncertainty
            # therefore behaves like one active process.
            logger.exception("Failed to read F048 runtime heartbeats")
            return 1

    async def _load_sources(self) -> dict[str, tuple[Any, ...]]:
        resources: list[PermissionMigrationResourceDTO] = []
        for source in self._sources:
            cursor: str | None = None
            seen: set[str | None] = set()
            while True:
                if cursor in seen:
                    raise ValueError("migration source returned a repeating cursor")
                seen.add(cursor)
                page = await source.aexport(cursor=cursor, limit=500)
                resources.extend(page.items)
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor

        configs = await self._load_configs()
        tuples = await self._load_tuples(tuple(resources))
        failed_tuples = await self._load_failed_tuples(
            resources=tuple(resources),
            tuples=tuples,
        )
        return {
            "configs": configs,
            "resources": tuple(resources),
            "tuples": tuples,
            "failed_tuples": failed_tuples,
        }

    @staticmethod
    async def _load_configs() -> tuple[LegacyConfigSource, ...]:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = select(Config).where(col(Config.key).in_(LEGACY_CONFIG_KEYS)).order_by(Config.key)
                rows = list((await session.execute(statement)).scalars().all())
        return tuple(
            LegacyConfigSource(
                key=row.key,
                row_version=(row.update_time.isoformat() if row.update_time is not None else str(row.id or 0)),
                raw_value=row.value or "",
            )
            for row in rows
        )

    async def _load_tuples(
        self,
        resources: tuple[PermissionMigrationResourceDTO, ...],
    ) -> tuple[LegacyTupleSource, ...]:
        tenant_by_object = {resource.key: resource.tenant_id for resource in resources}
        rows = await self._source_client.read_tuples()
        return tuple(
            LegacyTupleSource(
                tenant_id=tenant_by_object.get(str(row.get("object") or "")),
                user=str(row.get("user") or ""),
                relation=str(row.get("relation") or ""),
                object=str(row.get("object") or ""),
                condition=self._condition_name(row.get("condition")),
            )
            for row in rows
        )

    @staticmethod
    def _condition_name(value: object) -> str | None:
        if isinstance(value, dict):
            name = value.get("name")
            return str(name) if name else None
        return str(value) if value else None

    @staticmethod
    def _failed_tuple_error_category(error_message: str | None) -> str | None:
        normalized = (error_message or "").casefold()
        if "validation_error" in normalized and "invalid tuple" in normalized:
            return "MODEL_VALIDATION_REJECTED"
        if "deadline_exceeded" in normalized or "timed out" in normalized:
            return "TRANSIENT_TRANSPORT_FAILURE"
        return "OTHER" if normalized else None

    @staticmethod
    def _failed_tuple_resolution(
        *,
        status: str,
        action: str,
        tuple_identity: tuple[str, str, str],
        error_category: str | None,
        canonical_state: bool | None,
        resource_keys: set[str],
        store_tuples: set[tuple[str, str, str]],
    ) -> str | None:
        if status.casefold() == "succeeded":
            return "SUCCEEDED"

        normalized_action = action.casefold()
        store_state_matches = (normalized_action == "write" and tuple_identity in store_tuples) or (
            normalized_action == "delete" and tuple_identity not in store_tuples
        )
        if store_state_matches:
            return "STORE_STATE_MATCHES"

        object_key = tuple_identity[2]
        object_type, separator, _ = object_key.partition(":")
        if separator and object_type in MIGRATED_RESOURCE_TYPES and object_key not in resource_keys:
            return "RESOURCE_ABSENT"
        if canonical_state is not None:
            return "CANONICAL_IDENTITY_STATE"
        if error_category == "MODEL_VALIDATION_REJECTED":
            return "SOURCE_MODEL_REJECTED"
        if separator and object_type in MIGRATED_RESOURCE_TYPES and object_key in resource_keys:
            return "RESOURCE_STATE_REBUILT"
        return None

    async def _canonical_identity_states(
        self,
        rows: list[FailedTuple],
    ) -> dict[tuple[str, str, str], bool]:
        if self._identity_state_source is None:
            return {}
        identities = tuple(sorted({(row.fga_user, row.relation, row.object) for row in rows}))
        return await self._identity_state_source.aresolve_expected_states(identities)

    async def _load_failed_tuples(
        self,
        *,
        resources: tuple[PermissionMigrationResourceDTO, ...],
        tuples: tuple[LegacyTupleSource, ...],
    ) -> tuple[LegacyFailedTupleSource, ...]:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = select(FailedTuple).order_by(FailedTuple.id)
                rows = list((await session.execute(statement)).scalars().all())
        canonical_states = await self._canonical_identity_states(rows)
        resource_keys = {resource.key for resource in resources}
        store_tuples = {(row.user, row.relation, row.object) for row in tuples}
        result: list[LegacyFailedTupleSource] = []
        for row in rows:
            tuple_identity = (row.fga_user, row.relation, row.object)
            error_category = self._failed_tuple_error_category(row.error_message)
            canonical_state = canonical_states.get(tuple_identity)
            result.append(
                LegacyFailedTupleSource(
                    locator=f"failed_tuple:{row.id}",
                    status=row.status,
                    tuple_key="|".join(tuple_identity),
                    resolution=self._failed_tuple_resolution(
                        status=row.status,
                        action=row.action,
                        tuple_identity=tuple_identity,
                        error_category=error_category,
                        canonical_state=canonical_state,
                        resource_keys=resource_keys,
                        store_tuples=store_tuples,
                    ),
                    action=row.action,
                    error_category=error_category,
                    canonical_state=canonical_state,
                )
            )
        return tuple(result)

    @staticmethod
    def _watermark(
        sources: dict[str, tuple[Any, ...]],
    ) -> str:
        return _canonical_checksum(
            {
                "configs": [
                    {
                        "key": row.key,
                        "row_version": row.row_version,
                        "value_checksum": sha256(row.raw_value.encode("utf-8")).hexdigest(),
                    }
                    for row in sources["configs"]
                ],
                "resources": [
                    {
                        "key": row.key,
                        "source_locator": row.source_locator,
                        "source_version": row.source_version,
                        "tenant_id": row.tenant_id,
                    }
                    for row in sources["resources"]
                ],
                "tuples": [
                    {
                        **asdict(row),
                        "key": row.key,
                    }
                    for row in sources["tuples"]
                ],
                "failed_tuples": [asdict(row) for row in sources["failed_tuples"]],
            }
        )
