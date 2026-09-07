"""Pure compiler for flattened visible source contributions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.common.services.metric_log import emit_metric
from bisheng.permission.domain.schemas import VisibleSourceProjectionDTO
from bisheng.permission.domain.services.grant_source_service import (
    GrantSnapshot,
    GrantSourceRecord,
)
from bisheng.permission.domain.services.projection_plan import ProjectionTupleDelta

_GRANT_SOURCE_TYPES = frozenset(
    {
        "DIRECT",
        "DEPARTMENT",
        "USER_GROUP",
        "CREATOR",
        "CREATOR_GRANT",
        "SPACE_MEMBERSHIP",
        "CHANNEL_MEMBERSHIP",
        "SNAPSHOT_FROM_PARENT",
        "OTHER",
    }
)


@dataclass(frozen=True, slots=True)
class VisibilityProjectionCompilation:
    active_sources: tuple[VisibleSourceProjectionDTO, ...]
    retired_sources: tuple[VisibleSourceProjectionDTO, ...]
    deltas: tuple[ProjectionTupleDelta, ...]
    source_checksum: str
    aggregate_checksum: str


@dataclass(frozen=True, slots=True)
class VisibilityProjectionReconcilePlan:
    """Exact source and aggregate differences for one fenced resource."""

    upsert_sources: tuple[VisibleSourceProjectionDTO, ...]
    retire_sources: tuple[VisibleSourceProjectionDTO, ...]
    deltas: tuple[ProjectionTupleDelta, ...]
    source_checksum: str
    target_checksum: str
    live_checksum: str
    blockers: tuple[str, ...] = ()


def _hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _checksum(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode()).hexdigest()


def _aggregate_key(
    source: VisibleSourceProjectionDTO,
) -> tuple[str, str, str]:
    return (
        source.resource_type,
        source.resource_id,
        source.projected_subject,
    )


def _source_payload(source: VisibleSourceProjectionDTO) -> dict[str, object]:
    return source.model_dump(mode="json")


class VisibilityProjectionCompiler:
    """Compile canonical Grant sources without resolving organization members."""

    def compile(
        self,
        *,
        tenant_id: int,
        grants: tuple[GrantSnapshot, ...],
        existing_sources: tuple[VisibleSourceProjectionDTO, ...],
    ) -> VisibilityProjectionCompilation:
        started = perf_counter()
        if tenant_id <= 0:
            raise ValueError("visibility projection tenant_id must be positive")
        if any(grant.tenant_id != tenant_id for grant in grants):
            raise ValueError("visibility projection cannot mix tenants")
        if any(source.tenant_id != tenant_id for source in existing_sources):
            raise ValueError("visibility projection cannot mix existing tenants")

        desired = tuple(
            sorted(
                (
                    self._compile_source(tenant_id, grant, source)
                    for grant in grants
                    if grant.active
                    for source in grant.sources
                    if source.active and source.source_type in _GRANT_SOURCE_TYPES
                ),
                key=lambda row: (
                    row.resource_type,
                    row.resource_id,
                    row.visibility_class,
                    row.projected_subject,
                    row.contribution_fingerprint,
                ),
            )
        )
        desired_by_fingerprint = {source.contribution_fingerprint: source for source in desired}
        if len(desired_by_fingerprint) != len(desired):
            raise ValueError("visibility contribution fingerprints must be unique")

        existing_active = tuple(source for source in existing_sources if source.state == "ACTIVE")
        existing_by_fingerprint = {source.contribution_fingerprint: source for source in existing_active}
        active_sources: list[VisibleSourceProjectionDTO] = []
        for fingerprint, source in desired_by_fingerprint.items():
            previous = existing_by_fingerprint.get(fingerprint)
            if previous is None:
                active_sources.append(source)
                continue
            self._assert_same_canonical_source(previous, source)
            active_sources.append(
                source.model_copy(
                    update={
                        "source_version": max(previous.source_version, source.source_version),
                        "operation_id": previous.operation_id,
                        "migration_item_id": previous.migration_item_id,
                    }
                )
            )

        retired_sources = tuple(
            sorted(
                (
                    source.model_copy(update={"state": "RETIRED"})
                    for fingerprint, source in existing_by_fingerprint.items()
                    if fingerprint not in desired_by_fingerprint
                ),
                key=lambda row: row.contribution_fingerprint,
            )
        )
        active_sources_tuple = tuple(
            sorted(
                active_sources,
                key=lambda row: (
                    row.resource_type,
                    row.resource_id,
                    row.visibility_class,
                    row.projected_subject,
                    row.contribution_fingerprint,
                ),
            )
        )

        before_aggregates = {_aggregate_key(source) for source in existing_active}
        after_aggregates = {_aggregate_key(source) for source in active_sources_tuple}
        deltas = self._aggregate_deltas(
            before=before_aggregates,
            after=after_aggregates,
        )
        source_checksum = _checksum([_source_payload(source) for source in (*active_sources_tuple, *retired_sources)])
        aggregate_checksum = _checksum([list(key) for key in sorted(after_aggregates)])
        result = VisibilityProjectionCompilation(
            active_sources=active_sources_tuple,
            retired_sources=retired_sources,
            deltas=deltas,
            source_checksum=source_checksum,
            aggregate_checksum=aggregate_checksum,
        )
        emit_metric(
            "permission_visibility_projection",
            operation="project",
            tenant=tenant_id,
            source_count=len(result.active_sources),
            unique_tuple_count=len(after_aggregates),
            stale_count=len(result.retired_sources),
            orphan_count=0,
            source_checksum=result.source_checksum,
            aggregate_checksum=result.aggregate_checksum,
            elapsed_ms=(perf_counter() - started) * 1000,
            alert=None,
        )
        return result

    @staticmethod
    def _compile_source(
        tenant_id: int,
        grant: GrantSnapshot,
        source: GrantSourceRecord,
    ) -> VisibleSourceProjectionDTO:
        visibility_class = "protected" if source.protected else "ordinary"
        relation = "visible"
        source_owner_key = f"grant_assignee:{source.source_id}"
        contribution_fingerprint = _hash(
            "\0".join(
                (
                    "GRANT_ASSIGNEE",
                    source_owner_key,
                    source.source_fingerprint,
                    grant.model.model_key,
                )
            )
        )
        fga_object = f"{grant.resource_type}:{grant.resource_id}"
        tuple_fingerprint = _hash(
            "\0".join(
                (
                    "WRITE",
                    source.projected_subject,
                    relation,
                    fga_object,
                )
            )
        )
        return VisibleSourceProjectionDTO(
            tenant_id=tenant_id,
            resource_type=grant.resource_type,
            resource_id=grant.resource_id,
            visibility_class=visibility_class,
            projected_subject=source.projected_subject,
            source_kind="GRANT_ASSIGNEE",
            source_owner_key=source_owner_key,
            source_locator=source.source_locator,
            source_fingerprint=source.source_fingerprint,
            contribution_fingerprint=contribution_fingerprint,
            model_key=grant.model.model_key,
            source_version=source.version,
            tuple_fingerprint=tuple_fingerprint,
            state="ACTIVE",
        )

    @staticmethod
    def _aggregate_deltas(
        *,
        before: set[tuple[str, str, str]],
        after: set[tuple[str, str, str]],
    ) -> tuple[ProjectionTupleDelta, ...]:
        changes = [("DELETE", key) for key in sorted(before - after)] + [
            ("WRITE", key) for key in sorted(after - before)
        ]
        return tuple(
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=index,
                action=action,
                user=projected_subject,
                relation="visible",
                object=f"{resource_type}:{resource_id}",
            )
            for index, (
                action,
                (resource_type, resource_id, projected_subject),
            ) in enumerate(changes)
        )

    @staticmethod
    def _assert_same_canonical_source(
        previous: VisibleSourceProjectionDTO,
        current: VisibleSourceProjectionDTO,
    ) -> None:
        immutable_fields = (
            "tenant_id",
            "resource_type",
            "resource_id",
            "visibility_class",
            "projected_subject",
            "source_kind",
            "source_owner_key",
            "source_locator",
            "source_fingerprint",
            "contribution_fingerprint",
            "model_key",
            "tuple_fingerprint",
        )
        if any(getattr(previous, field) != getattr(current, field) for field in immutable_fields):
            raise ValueError("visibility contribution fingerprint collision")


class VisibilityProjectionReconciler:
    """Plan fail-closed convergence from canonical sources to live tuples."""

    def plan(
        self,
        *,
        canonical_sources: tuple[VisibleSourceProjectionDTO, ...],
        persisted_sources: tuple[VisibleSourceProjectionDTO, ...],
        live_tuples: frozenset[tuple[str, str, str]],
        ledger_complete: bool = True,
    ) -> VisibilityProjectionReconcilePlan:
        started = perf_counter()
        blockers: list[str] = []
        if not ledger_complete:
            blockers.append("visibility projection ledger is incomplete")
        if any(source.state == "FAILED_CLOSED" for source in persisted_sources):
            blockers.append("visibility source projection contains FAILED_CLOSED rows")

        canonical_by_fingerprint = self._unique_sources(
            canonical_sources,
            label="canonical",
            blockers=blockers,
        )
        persisted_by_fingerprint = self._unique_sources(
            persisted_sources,
            label="persisted",
            blockers=blockers,
        )
        self._validate_scope(
            (*canonical_sources, *persisted_sources),
            live_tuples,
            blockers,
        )

        upsert: list[VisibleSourceProjectionDTO] = []
        for fingerprint, desired in canonical_by_fingerprint.items():
            existing = persisted_by_fingerprint.get(fingerprint)
            if existing is None:
                upsert.append(desired.model_copy(update={"state": "ACTIVE"}))
                continue
            try:
                VisibilityProjectionCompiler._assert_same_canonical_source(existing, desired)
            except ValueError:
                blockers.append(
                    f"visibility contribution collision: {fingerprint}",
                )
                continue
            if existing.state != "ACTIVE" or existing.source_version != desired.source_version:
                upsert.append(desired.model_copy(update={"state": "ACTIVE"}))

        retire = tuple(
            sorted(
                (
                    source
                    for fingerprint, source in persisted_by_fingerprint.items()
                    if fingerprint not in canonical_by_fingerprint and source.state in {"ACTIVE", "PENDING"}
                ),
                key=lambda row: row.contribution_fingerprint,
            )
        )
        upsert_tuple = tuple(sorted(upsert, key=lambda row: row.contribution_fingerprint))
        target_tuples = frozenset(self._live_key(source) for source in canonical_by_fingerprint.values())
        changes = [("DELETE", key) for key in sorted(live_tuples - target_tuples)] + [
            ("WRITE", key) for key in sorted(target_tuples - live_tuples)
        ]
        deltas = tuple(
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=index,
                action=action,
                user=key[0],
                relation=key[1],
                object=key[2],
            )
            for index, (action, key) in enumerate(changes)
        )
        active_canonical = tuple(
            sorted(
                (source.model_copy(update={"state": "ACTIVE"}) for source in canonical_by_fingerprint.values()),
                key=lambda row: row.contribution_fingerprint,
            )
        )
        result = VisibilityProjectionReconcilePlan(
            upsert_sources=upsert_tuple,
            retire_sources=retire,
            deltas=deltas,
            source_checksum=_checksum([_source_payload(source) for source in active_canonical]),
            target_checksum=self._tuple_checksum(target_tuples),
            live_checksum=self._tuple_checksum(live_tuples),
            blockers=tuple(dict.fromkeys(blockers)),
        )
        orphan_count = len(live_tuples - target_tuples)
        emit_metric(
            "permission_visibility_projection",
            operation="reconcile",
            source_count=len(active_canonical),
            unique_tuple_count=len(target_tuples),
            stale_count=len(retire),
            orphan_count=orphan_count,
            source_checksum=result.source_checksum,
            aggregate_checksum=result.target_checksum,
            live_checksum=result.live_checksum,
            elapsed_ms=(perf_counter() - started) * 1000,
            alert=(
                "orphan_visible_tuple"
                if orphan_count
                else "checksum_mismatch"
                if result.target_checksum != result.live_checksum
                else "projection_blocked"
                if result.blockers
                else None
            ),
        )
        return result

    @staticmethod
    def ensure_ready(plan: VisibilityProjectionReconcilePlan) -> None:
        if plan.blockers:
            raise PermissionPublishNotReadyError(msg="; ".join(plan.blockers))

    @staticmethod
    def _unique_sources(
        sources: tuple[VisibleSourceProjectionDTO, ...],
        *,
        label: str,
        blockers: list[str],
    ) -> dict[str, VisibleSourceProjectionDTO]:
        result: dict[str, VisibleSourceProjectionDTO] = {}
        for source in sources:
            fingerprint = source.contribution_fingerprint
            if fingerprint in result:
                blockers.append(
                    f"duplicate {label} visibility contribution: {fingerprint}",
                )
                continue
            result[fingerprint] = source
        return result

    @staticmethod
    def _live_key(
        source: VisibleSourceProjectionDTO,
    ) -> tuple[str, str, str]:
        return (
            source.projected_subject,
            "visible",
            f"{source.resource_type}:{source.resource_id}",
        )

    @staticmethod
    def _tuple_checksum(tuples: frozenset[tuple[str, str, str]]) -> str:
        return _checksum([list(key) for key in sorted(tuples)])

    @classmethod
    def _validate_scope(
        cls,
        sources: tuple[VisibleSourceProjectionDTO, ...],
        live_tuples: frozenset[tuple[str, str, str]],
        blockers: list[str],
    ) -> None:
        scopes = {(source.tenant_id, source.resource_type, source.resource_id) for source in sources}
        if len(scopes) > 1:
            blockers.append("visibility reconcile cannot mix resource scopes")
        resource_keys = {f"{resource_type}:{resource_id}" for _, resource_type, resource_id in scopes}
        if resource_keys and any(key[2] not in resource_keys for key in live_tuples):
            blockers.append("visibility reconcile live tuple is outside the fenced scope")
        if any(key[1] != "visible" for key in live_tuples):
            blockers.append("visibility reconcile received a non-flattened relation")
