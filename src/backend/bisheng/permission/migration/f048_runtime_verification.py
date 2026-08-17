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
from bisheng.core.openfga.discovery import normalize_authorization_model
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionMigrationItem,
    PermissionVisibleSourceProjection,
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
    ) -> None:
        self._source_client = source_client
        self._target_writer = target_writer
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

        resource_items = [
            row
            for row in items
            if row.source_kind == "RESOURCE" and json.loads(row.message or "{}").get("migratable", True)
        ]
        semantic_results = await self._semantic_results(
            run=run,
            resources=resource_items,
            expected_tuples=target_tuples,
            consistency=consistency,
        )
        source_integrity = await self._visible_source_integrity()
        expected_visible = {
            _identity(row) for row in target_tuples if row["relation"] == "visible"
        }
        actual_visible = {
            _identity(row)
            for row in actual_rows
            if row.get("relation") == "visible"
            and str(row.get("object", "")).partition(":")[0]
            in {
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
        }
        difference_types = [row.difference_type for row in items if row.difference_type]
        catalog, model_release = await self._release_rows(
            run.store_id,
            run.target_model_id,
        )
        expected_model_checksum = authorization_model_checksum(build_authorization_model_f048())
        remote_model_checksum = await self._remote_model_checksum(run.target_model_id)
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
            failed_tuple_count=sum(
                row.source_kind == "FAILED_TUPLE" and row.difference_type == "UNRESOLVED_FAILED_TUPLE" for row in items
            ),
            legacy_tuple_count=self._legacy_tuple_count(actual_rows),
            legacy_config_count=await self._legacy_config_count(),
            preserved_tuple_checksum_matches=(preserved_expected <= actual_identities),
            model_checksum_matches=(
                model_release is not None
                and model_release.model_checksum == expected_model_checksum
                and model_release.model_id == run.target_model_id
                and remote_model_checksum == expected_model_checksum
            ),
            semantic_results=semantic_results,
            instance_pins=(
                self._migration_target_pin(
                    run=run,
                    catalog=catalog,
                    model_release=model_release,
                ),
            ),
            visible_source_checksum_matches=source_integrity,
            visible_aggregate_checksum_matches=(expected_visible == actual_visible),
            unattributed_visible_count=len(actual_visible - expected_visible),
            visible_stream_complete=semantic_results.get(
                "visible_stream_oracle",
                False,
            ),
        )

    async def _remote_model_checksum(self, model_id: str) -> str | None:
        for raw_model in await self._source_client.list_authorization_models():
            if not isinstance(raw_model, dict):
                continue
            remote_model_id = raw_model.get("id") or raw_model.get("authorization_model_id")
            if str(remote_model_id or "") != model_id:
                continue
            return authorization_model_checksum(normalize_authorization_model(raw_model))
        return None

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
            results.update(
                await self._visible_oracle_semantics(
                    client,
                    expected_tuples,
                    consistency,
                )
            )
            return results
        finally:
            await client.close()

    @staticmethod
    async def _visible_oracle_semantics(
        client: FGAClient,
        tuples: tuple[dict[str, str], ...],
        consistency: str,
    ) -> dict[str, bool]:
        users = sorted(
            {
                row["user"]
                for row in tuples
                if row["user"].startswith("user:") and "#" not in row["user"]
            }
        )
        objects_by_type: dict[str, list[str]] = {}
        for row in tuples:
            if row["relation"] != "visible":
                continue
            resource_type = row["object"].partition(":")[0]
            objects_by_type.setdefault(resource_type, []).append(row["object"])
        if not users or not objects_by_type:
            return {
                "visible_single_batch_oracle": True,
                "visible_stream_oracle": True,
            }

        single_batch_matches = True
        stream_matches = True
        for user in users:
            for resource_type, objects in sorted(objects_by_type.items()):
                checks = [
                    {
                        "user": user,
                        "relation": "visible",
                        "object": object_key,
                    }
                    for object_key in sorted(set(objects))
                ]
                batch_results: list[bool] = []
                for offset in range(0, len(checks), 50):
                    batch_results.extend(
                        await client.batch_check(
                            checks[offset : offset + 50],
                            consistency=consistency,
                        )
                    )
                single_results = [
                    await client.check(
                        user=user,
                        relation="visible",
                        object=check["object"],
                        consistency=consistency,
                    )
                    for check in checks
                ]
                single_batch_matches &= single_results == batch_results
                expected = {
                    check["object"]
                    for check, allowed in zip(checks, batch_results, strict=True)
                    if allowed
                }
                try:
                    streamed = set(
                        await client.stream_list_objects(
                            user=user,
                            relation="visible",
                            type=resource_type,
                            consistency=consistency,
                        )
                    )
                except Exception:
                    stream_matches = False
                else:
                    stream_matches &= (streamed & set(objects)) == expected
        return {
            "visible_single_batch_oracle": single_batch_matches,
            "visible_stream_oracle": stream_matches,
        }

    @staticmethod
    async def _visible_source_integrity() -> bool:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                assignees = list(
                    (
                        await session.execute(
                            select(PermissionGrantAssignee)
                            .join(PermissionGrant, PermissionGrant.id == PermissionGrantAssignee.grant_id)
                            .where(
                                PermissionGrant.state == "ACTIVE",
                                PermissionGrantAssignee.state == "ACTIVE",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                sources = list(
                    (
                        await session.execute(
                            select(PermissionVisibleSourceProjection).where(
                                PermissionVisibleSourceProjection.state == "ACTIVE",
                                PermissionVisibleSourceProjection.source_kind == "GRANT_ASSIGNEE",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
        expected = {f"grant_assignee:{row.id}" for row in assignees if row.id is not None}
        actual = [row.source_owner_key for row in sources]
        return len(actual) == len(set(actual)) and set(actual) == expected

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
        store_id: str,
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
                        select(AuthorizationModelRelease).where(
                            AuthorizationModelRelease.store_id == store_id,
                            AuthorizationModelRelease.model_id == model_id,
                        )
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
                            PermissionGrantAssignee.protected == 1,
                            PermissionGrantAssignee.state == "ACTIVE",
                        )
                    )
                    count = int((await session.execute(statement)).scalar_one())
                    if count != 1:
                        invalid += 1
        return invalid

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
        canonically_absent = {
            str(payload.get("tuple_key"))
            for item in items
            if item.source_kind == "FAILED_TUPLE"
            and item.message
            and (payload := json.loads(item.message)).get("resolution") == "CANONICAL_IDENTITY_STATE"
            and payload.get("canonical_state") is False
        }
        expected: set[tuple[str, str, str]] = set()
        for item in items:
            if item.source_kind != "TUPLE" or not item.message or item.difference_type == "STALE_RESOURCE_TUPLE":
                continue
            source = json.loads(item.message)
            source_identity = _identity(source)
            source_key = "|".join(source_identity)
            if source.get("relation") in PRESERVED_RELATIONS and source_key not in canonically_absent:
                expected.add(source_identity)
        return expected

    @staticmethod
    def _migration_target_pin(
        *,
        run: MigrationRunState,
        catalog: PermissionCatalogRelease | None,
        model_release: AuthorizationModelRelease | None,
    ) -> InstancePinEvidence:
        expected_checksum = authorization_model_checksum(build_authorization_model_f048())
        return InstancePinEvidence(
            role="migration-target",
            ready=bool(
                catalog
                and model_release
                and catalog.status == "CURRENT"
                and catalog.required_authorization_model_release_id == model_release.id
                and model_release.status == "STAGED"
                and model_release.store_id == run.store_id
                and model_release.model_id == run.target_model_id
                and model_release.model_checksum == expected_checksum
            ),
            store_id=str(model_release.store_id if model_release else ""),
            model_id=str(model_release.model_id if model_release else ""),
            catalog_release_id=(int(catalog.id) if catalog and catalog.id else None),
        )
