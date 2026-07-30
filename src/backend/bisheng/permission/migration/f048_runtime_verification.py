"""Live D4 evidence collection for a completed F048 write phase."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select

from bisheng.common.models.config import Config
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.database.models.failed_tuple import FailedTuple
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionMigrationItem,
)
from bisheng.permission.domain.repositories.migration_repository import (
    MigrationRepository,
)
from bisheng.permission.migration.f048_coordinator import (
    INITIAL_CATALOG_RELEASE_KEY,
    MigrationRunState,
)
from bisheng.permission.migration.f048_runtime_source import (
    LEGACY_CONFIG_KEYS,
)
from bisheng.permission.migration.f048_runtime_storage import (
    SqlOpenFGAMigrationTargetWriter,
)
from bisheng.permission.migration.f048_tuple_mapper import (
    PRESERVED_RELATIONS,
    STANDARD_RELATION_MODELS,
)
from bisheng.permission.migration.f048_verifier import (
    InstancePinEvidence,
    MigrationVerificationEvidence,
)


def _checksum(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["user"]),
        str(row["relation"]),
        str(row["object"]),
    )


class LiveMigrationEvidenceProvider:
    """Collect independent SQL, Store, semantic, and runtime-pin evidence."""

    def __init__(
        self,
        *,
        source_client: FGAClient,
        target_writer: SqlOpenFGAMigrationTargetWriter,
        runtime_config: Any,
    ) -> None:
        self._source_client = source_client
        self._target_writer = target_writer
        self._runtime_config = runtime_config
        self._migration_repository = MigrationRepository()

    async def acollect(
        self,
        *,
        run: MigrationRunState,
        consistency: str,
    ) -> MigrationVerificationEvidence:
        if consistency != "HIGHER_CONSISTENCY":
            raise ValueError("D4 requires higher consistency")
        if not run.target_model_id:
            raise ValueError("D4 run has no target model")

        items = await self._items(run.id)
        target_tuples = self._target_tuples(items)
        actual_rows = await self._source_client.read_tuples(consistency=consistency)
        actual_identities = {_identity(row) for row in actual_rows}
        expected_identities = {_identity(row) for row in target_tuples}
        present_tuples = tuple(row for row in target_tuples if _identity(row) in actual_identities)
        control_checksum = await self._target_writer.acontrol_plane_checksum()
        expected_target_checksum = _checksum(
            {
                "control": control_checksum,
                "tuples": target_tuples,
            }
        )
        actual_target_checksum = _checksum(
            {
                "control": control_checksum,
                "tuples": present_tuples,
            }
        )
        source_checksum = await self._migration_repository.aget_run_checksum(run.id)
        if source_checksum is None:
            source_checksum = ""

        resource_items = [row for row in items if row.source_kind == "RESOURCE"]
        semantic_results = await self._semantic_results(
            run=run,
            resources=resource_items,
            expected_tuples=target_tuples,
            consistency=consistency,
        )
        difference_types = [row.difference_type for row in items if row.difference_type]
        catalog, model_release = await self._release_rows(run.target_model_id)
        preserved_expected = self._preserved_tuple_identities(items)
        return MigrationVerificationEvidence(
            source_checksum=source_checksum,
            expected_target_checksum=expected_target_checksum,
            actual_target_checksum=actual_target_checksum,
            expected_target_count=len(expected_identities),
            actual_target_count=len(expected_identities & actual_identities),
            blocker_count=sum(row.severity == "BLOCKER" for row in items),
            unapproved_manual_count=sum(row.status == "MANUAL" and row.approved_at is None for row in items),
            cross_tenant_count=sum(
                value
                in {
                    "CROSS_TENANT_TUPLE",
                    "CROSS_TENANT_PARENT",
                }
                for value in difference_types
            )
            + await self._cross_tenant_control_count(),
            orphan_count=sum(value in {"ORPHAN_TUPLE", "MISSING_BINDING_MODEL"} for value in difference_types),
            invalid_parent_count=sum(
                value
                in {
                    "MISSING_CANONICAL_PARENT",
                    "CANONICAL_PARENT_CYCLE",
                    "CROSS_TENANT_PARENT",
                }
                for value in difference_types
            ),
            invalid_owner_count=sum(
                value
                in {
                    "INVALID_CANONICAL_OWNER",
                    "MISSING_CANONICAL_OWNER",
                    "MULTIPLE_ACTIVE_CREATORS",
                }
                for value in difference_types
            )
            + await self._invalid_owner_count(resource_items),
            failed_tuple_count=await self._failed_tuple_count(),
            legacy_tuple_count=self._legacy_tuple_count(actual_rows),
            legacy_config_count=await self._legacy_config_count(),
            preserved_tuple_checksum_matches=(preserved_expected <= actual_identities),
            model_checksum_matches=(
                model_release is not None
                and model_release.model_checksum == authorization_model_checksum(build_authorization_model_f048())
                and model_release.model_id == run.target_model_id
            ),
            semantic_results=semantic_results,
            instance_pins=(
                self._configured_pin(
                    run=run,
                    catalog=catalog,
                ),
            ),
        )

    @staticmethod
    async def _items(run_id: int) -> list[PermissionMigrationItem]:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = (
                    select(PermissionMigrationItem)
                    .where(PermissionMigrationItem.run_id == run_id)
                    .order_by(
                        PermissionMigrationItem.source_kind,
                        PermissionMigrationItem.source_locator,
                    )
                )
                return list((await session.execute(statement)).scalars().all())

    @staticmethod
    def _target_tuples(
        items: list[PermissionMigrationItem],
    ) -> tuple[dict[str, str], ...]:
        rows: list[dict[str, str]] = []
        for item in items:
            if item.source_kind != "TARGET_TUPLE":
                continue
            try:
                value = json.loads(item.message or "")
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid target tuple item {item.source_locator}") from exc
            if not isinstance(value, dict) or set(value) != {"user", "relation", "object"}:
                raise ValueError(f"invalid target tuple payload {item.source_locator}")
            rows.append({key: str(value[key]) for key in value})
        return tuple(sorted(rows, key=_identity))

    async def _semantic_results(
        self,
        *,
        run: MigrationRunState,
        resources: list[PermissionMigrationItem],
        expected_tuples: tuple[dict[str, str], ...],
        consistency: str,
    ) -> dict[str, bool]:
        client = self._source_client.for_model(run.target_model_id or "")
        try:
            results: dict[str, bool] = {
                "target_tuple_graph": await self._raw_tuple_checks(
                    client,
                    expected_tuples,
                    consistency,
                )
            }
            parsed = [json.loads(row.message or "{}") for row in resources]
            dashboard = next(
                (
                    row
                    for row in parsed
                    if row.get("resource_type") == "dashboard" and row.get("ownership_kind") == "USER"
                ),
                None,
            )
            if dashboard is not None:
                owner = self._protected_owner(dashboard)
                checks = [
                    {
                        "user": f"user:{owner}",
                        "relation": relation,
                        "object": (f"dashboard:{dashboard['resource_id']}"),
                    }
                    for relation in (
                        "visible",
                        "can_edit",
                        "can_delete",
                        "can_manage_permission",
                    )
                ]
                results["dashboard_owner_actions"] = all(
                    await client.batch_check(
                        checks,
                        consistency=consistency,
                    )
                )
            file_row = next(
                (
                    row
                    for row in parsed
                    if row.get("resource_type") == "knowledge_file" and row.get("ownership_kind") == "USER"
                ),
                None,
            )
            if file_row is not None:
                results["file_download"] = await client.check(
                    user=f"user:{self._protected_owner(file_row)}",
                    relation="can_download",
                    object=f"knowledge_file:{file_row['resource_id']}",
                    consistency=consistency,
                )
            return results
        finally:
            await client.close()

    @staticmethod
    async def _raw_tuple_checks(
        client: FGAClient,
        tuples: tuple[dict[str, str], ...],
        consistency: str,
    ) -> bool:
        for index in range(0, len(tuples), 100):
            batch = list(tuples[index : index + 100])
            if not all(
                await client.batch_check(
                    batch,
                    consistency=consistency,
                )
            ):
                return False
        return True

    @staticmethod
    def _protected_owner(resource: dict[str, Any]) -> int:
        creators = resource.get("creator_user_ids") or ()
        if resource.get("resource_type") in {"knowledge_space", "channel"} and len(creators) == 1:
            return int(creators[0])
        return int(resource["owner_user_id"])

    @staticmethod
    async def _release_rows(
        model_id: str,
    ) -> tuple[
        PermissionCatalogRelease | None,
        AuthorizationModelRelease | None,
    ]:
        async with get_async_db_session() as session:
            catalog = (
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
            model_release = (
                (
                    await session.execute(
                        select(AuthorizationModelRelease).where(AuthorizationModelRelease.model_id == model_id)
                    )
                )
                .scalars()
                .first()
            )
        return catalog, model_release

    @staticmethod
    async def _cross_tenant_control_count() -> int:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = (
                    select(func.count())
                    .select_from(PermissionGrantAssignee)
                    .join(
                        PermissionGrant,
                        PermissionGrant.id == PermissionGrantAssignee.grant_id,
                    )
                    .where(PermissionGrantAssignee.tenant_id != PermissionGrant.tenant_id)
                )
                return int((await session.execute(statement)).scalar_one())

    @staticmethod
    async def _invalid_owner_count(
        resources: list[PermissionMigrationItem],
    ) -> int:
        invalid = 0
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                for item in resources:
                    resource = json.loads(item.message or "{}")
                    if resource.get("ownership_kind") != "USER":
                        continue
                    owner_id = LiveMigrationEvidenceProvider._protected_owner(resource)
                    statement = (
                        select(func.count())
                        .select_from(PermissionGrantAssignee)
                        .join(
                            PermissionGrant,
                            PermissionGrant.id == PermissionGrantAssignee.grant_id,
                        )
                        .where(
                            PermissionGrant.tenant_id == resource.get("tenant_id"),
                            PermissionGrant.resource_type == resource.get("resource_type"),
                            PermissionGrant.resource_id == str(resource.get("resource_id")),
                            PermissionGrant.model_key == "owner",
                            PermissionGrantAssignee.subject_type == "user",
                            PermissionGrantAssignee.subject_id == str(owner_id),
                            PermissionGrantAssignee.protected.is_(True),
                            PermissionGrantAssignee.state == "ACTIVE",
                        )
                    )
                    count = int((await session.execute(statement)).scalar_one())
                    if count != 1:
                        invalid += 1
        return invalid

    @staticmethod
    async def _failed_tuple_count() -> int:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = (
                    select(func.count())
                    .select_from(FailedTuple)
                    .where(col(FailedTuple.status).in_(("pending", "dead", "failed", "retrying")))
                )
                return int((await session.execute(statement)).scalar_one())

    @staticmethod
    async def _legacy_config_count() -> int:
        async with get_async_db_session() as session:
            statement = select(func.count()).select_from(Config).where(col(Config.key).in_(LEGACY_CONFIG_KEYS))
            return int((await session.execute(statement)).scalar_one())

    @staticmethod
    def _legacy_tuple_count(rows: list[dict]) -> int:
        legacy_relations = set(STANDARD_RELATION_MODELS) - set(PRESERVED_RELATIONS)
        migrated_types = {
            "knowledge_space",
            "knowledge_library",
            "folder",
            "knowledge_file",
            "workflow",
            "assistant",
            "tool",
            "channel",
            "dashboard",
        }
        return sum(
            str(row.get("relation")) in legacy_relations and str(row.get("object")).partition(":")[0] in migrated_types
            for row in rows
        )

    @staticmethod
    def _preserved_tuple_identities(
        items: list[PermissionMigrationItem],
    ) -> set[tuple[str, str, str]]:
        expected: set[tuple[str, str, str]] = set()
        for item in items:
            if item.source_kind != "TUPLE" or not item.message:
                continue
            source = json.loads(item.message)
            if source.get("relation") in PRESERVED_RELATIONS:
                expected.add(_identity(source))
        return expected

    def _configured_pin(
        self,
        *,
        run: MigrationRunState,
        catalog: PermissionCatalogRelease | None,
    ) -> InstancePinEvidence:
        config = self._runtime_config
        return InstancePinEvidence(
            role="configured-runtime",
            ready=bool(
                catalog
                and config.store_id == run.store_id
                and config.model_id == run.target_model_id
                and config.model_checksum == authorization_model_checksum(build_authorization_model_f048())
                and config.current_catalog_release_id == catalog.id
                and config.current_catalog_checksum == catalog.checksum
            ),
            store_id=str(config.store_id or ""),
            model_id=str(config.model_id or ""),
            catalog_release_id=(int(config.current_catalog_release_id) if config.current_catalog_release_id else None),
            dual_model_mode=bool(config.dual_model_mode),
            legacy_model_id=config.legacy_model_id,
        )
