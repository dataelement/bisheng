"""F048 resource permission-mode and lifecycle projection compiler."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Protocol

from loguru import logger

from bisheng.common.errcode.permission import (
    InvalidPermissionModeError,
    PermissionImpactExpiredError,
    PermissionVersionConflictError,
)
from bisheng.permission.domain.models import (
    PermissionProjectionOperation,
    ProjectionOperationStatus,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantSnapshot,
    GrantSourceRecord,
    GrantSourceService,
)
from bisheng.permission.domain.services.projection_service import (
    ProjectionOutcome,
    ProjectionPlan,
    ProjectionTupleDelta,
)
from bisheng.permission.domain.services.resource_lifecycle_policy import (
    FLEXIBLE_MODE_TYPES,
    build_create_plan,
    build_delete_plan,
    build_move_plan,
    copy_permission_mode,
    default_permission_mode,
)


@dataclass(frozen=True, slots=True)
class ModeContext:
    target: VerifiedPermissionTarget
    mode: str
    current_catalog_release_id: int
    store_id: str
    model_id: str
    operator_id: int
    local_grants: tuple[GrantSnapshot, ...]
    inherited_grants: tuple[GrantSnapshot, ...]


@dataclass(frozen=True, slots=True)
class PermissionModeDraft:
    draft_id: str
    current_mode: str
    target_mode: str
    tenant_id: int
    resource_type: str
    resource_id: str
    resource_version: int
    catalog_release_id: int
    context_version: str
    parent_type: str | None
    parent_id: str | None
    context_checksum: str
    impact_checksum: str
    snapshot_sources: tuple[GrantSourceRecord, ...]
    staging_deltas: tuple[ProjectionTupleDelta, ...]
    result_grants: tuple[GrantSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ModeApplyResult:
    applied: bool
    mode: str
    resource_version: int
    grants: tuple[GrantSnapshot, ...]
    projection: ProjectionOutcome | None = None


class ModeProjectionPort(Protocol):
    async def prepare(
        self,
        plan: ProjectionPlan,
    ) -> PermissionProjectionOperation: ...

    async def abandon_prepared(
        self,
        plan: ProjectionPlan,
        error: Exception,
    ) -> None: ...

    async def execute(self, plan: ProjectionPlan) -> ProjectionOutcome: ...


class ModeStatePort(Protocol):
    async def allocate_source_ids(self, count: int) -> tuple[int, ...]: ...

    async def save_draft(self, draft: PermissionModeDraft) -> None: ...

    async def prepare(
        self,
        context: ModeContext,
        draft: PermissionModeDraft,
        grants: tuple[GrantSnapshot, ...],
        *,
        idempotency_key: str,
        operation_id: int,
    ) -> None: ...

    async def finalize(
        self,
        context: ModeContext,
        draft: PermissionModeDraft,
        grants: tuple[GrantSnapshot, ...],
        outcome: ProjectionOutcome,
    ) -> None: ...


class ModeEventPort(Protocol):
    async def emit(self, name: str, fields: dict) -> None: ...


class _NullEvents:
    async def emit(self, name: str, fields: dict) -> None:
        return None


def _checksum(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


class ModeService:
    """Switch only mode gates; business parent and resource data are inputs."""

    def __init__(
        self,
        *,
        source_service: GrantSourceService,
        projection: ModeProjectionPort,
        state: ModeStatePort,
        events: ModeEventPort | None = None,
    ) -> None:
        self._sources = source_service
        self._projection = projection
        self._state = state
        self._events = events or _NullEvents()

    default_mode = staticmethod(default_permission_mode)
    copy_mode = staticmethod(copy_permission_mode)
    create_plan = staticmethod(build_create_plan)
    move_plan = staticmethod(build_move_plan)
    delete_plan = staticmethod(build_delete_plan)

    async def create_draft(
        self,
        context: ModeContext,
        *,
        target_mode: str,
    ) -> PermissionModeDraft:
        target_mode = target_mode.upper()
        self._validate_switch(context, target_mode)
        if target_mode == "CUSTOM":
            result_grants, snapshot_sources, staging = await self._snapshot_inherited(context)
        else:
            result_grants = self._protected_only(context.local_grants)
            snapshot_sources = ()
            staging = ()

        context_checksum = self._context_checksum(context)
        impact_payload = {
            "catalog_release_id": context.current_catalog_release_id,
            "context_checksum": context_checksum,
            "current_mode": context.mode,
            "snapshot_fingerprints": [source.source_fingerprint for source in snapshot_sources],
            "target_mode": target_mode,
        }
        impact_checksum = _checksum(impact_payload)
        draft = PermissionModeDraft(
            draft_id=impact_checksum[:26],
            current_mode=context.mode,
            target_mode=target_mode,
            tenant_id=context.target.tenant_id,
            resource_type=context.target.resource_type,
            resource_id=context.target.resource_id,
            resource_version=context.target.resource_version,
            catalog_release_id=context.current_catalog_release_id,
            context_version=context.target.context_version,
            parent_type=context.target.parent_type,
            parent_id=context.target.parent_id,
            context_checksum=context_checksum,
            impact_checksum=impact_checksum,
            snapshot_sources=snapshot_sources,
            staging_deltas=staging,
            result_grants=result_grants,
        )
        await self._state.save_draft(draft)
        return draft

    async def apply(
        self,
        context: ModeContext,
        draft: PermissionModeDraft,
        *,
        expected_resource_version: int,
        expected_catalog_release_id: int,
        confirmed: bool,
        idempotency_key: str,
    ) -> ModeApplyResult:
        if not confirmed:
            return ModeApplyResult(
                applied=False,
                mode=context.mode,
                resource_version=context.target.resource_version,
                grants=context.local_grants,
            )
        self._validate_draft(
            context,
            draft,
            expected_resource_version=expected_resource_version,
            expected_catalog_release_id=expected_catalog_release_id,
        )
        commit_deltas = (
            self._mode_delta(
                context.target,
                mode=draft.current_mode,
                action="DELETE",
                sequence=0,
            ),
            self._mode_delta(
                context.target,
                mode=draft.target_mode,
                action="WRITE",
                sequence=1,
            ),
        )
        deltas = tuple(
            replace(delta, sequence=index) for index, delta in enumerate((*draft.staging_deltas, *commit_deltas))
        )
        plan = ProjectionPlan(
            tenant_id=context.target.tenant_id,
            idempotency_key=idempotency_key,
            operation_type="MODE_SWITCH",
            scope_type="resource",
            scope_key=(f"{context.target.resource_type}:{context.target.resource_id}"),
            expected_version=context.target.resource_version,
            target_version=context.target.resource_version + 1,
            store_id=context.store_id,
            model_id=context.model_id,
            operator_id=context.operator_id,
            change_item_count=1,
            deltas=deltas,
        )
        operation = await self._projection.prepare(plan)
        if str(operation.status) == ProjectionOperationStatus.PREPARED.value:
            try:
                await self._state.prepare(
                    context,
                    draft,
                    draft.result_grants,
                    idempotency_key=idempotency_key,
                    operation_id=int(operation.id),
                )
            except Exception as exc:
                await self._projection.abandon_prepared(plan, exc)
                raise
        outcome = await self._projection.execute(plan)
        await self._state.finalize(
            context,
            draft,
            draft.result_grants,
            outcome,
        )
        await self._emit(context, draft, outcome)
        return ModeApplyResult(
            applied=True,
            mode=draft.target_mode,
            resource_version=outcome.target_version,
            grants=draft.result_grants,
            projection=outcome,
        )

    def _validate_switch(self, context: ModeContext, target_mode: str) -> None:
        resource_type = context.target.resource_type
        if resource_type not in FLEXIBLE_MODE_TYPES:
            raise InvalidPermissionModeError(msg=f"{resource_type} has fixed CUSTOM permission mode")
        if target_mode not in {"INHERIT", "CUSTOM"}:
            raise InvalidPermissionModeError(msg=f"Unsupported permission mode: {target_mode}")
        if target_mode == context.mode:
            raise InvalidPermissionModeError(msg=f"Resource already uses {target_mode}")
        if target_mode == "INHERIT" and (context.target.parent_type is None or context.target.parent_id is None):
            raise InvalidPermissionModeError(msg="INHERIT requires a canonical direct parent")

    def _validate_draft(
        self,
        context: ModeContext,
        draft: PermissionModeDraft,
        *,
        expected_resource_version: int,
        expected_catalog_release_id: int,
    ) -> None:
        if (
            expected_resource_version != context.target.resource_version
            or expected_resource_version != draft.resource_version
        ):
            raise PermissionVersionConflictError(msg="Resource permission version changed")
        if (
            expected_catalog_release_id != context.current_catalog_release_id
            or expected_catalog_release_id != draft.catalog_release_id
        ):
            raise PermissionVersionConflictError(msg="Permission Catalog release changed")
        if context.mode != draft.current_mode or self._context_checksum(context) != draft.context_checksum:
            raise PermissionImpactExpiredError(msg="Permission mode draft context changed")

    async def _snapshot_inherited(
        self,
        context: ModeContext,
    ) -> tuple[
        tuple[GrantSnapshot, ...],
        tuple[GrantSourceRecord, ...],
        tuple[ProjectionTupleDelta, ...],
    ]:
        local_by_model = {grant.model.model_key: grant for grant in context.local_grants}
        protected_refs = {
            (grant.model.model_key, source.projected_subject)
            for grant in context.local_grants
            for source in grant.sources
            if source.active and source.protected
        }
        candidates = [
            (grant.model.model_key, source)
            for grant in context.inherited_grants
            for source in grant.sources
            if source.active
            and (
                grant.model.model_key,
                source.projected_subject,
            )
            not in protected_refs
        ]
        source_ids = await self._state.allocate_source_ids(len(candidates))
        snapshots: list[GrantSourceRecord] = []
        staging: list[ProjectionTupleDelta] = []
        for source_id, (model_key, source) in zip(
            source_ids,
            candidates,
            strict=True,
        ):
            snapshot = self._sources.canonicalize_source(
                source_id=source_id,
                subject_type=source.subject_type,
                subject_id=source.subject_id,
                userset_relation=source.userset_relation,
                include_children=source.include_children,
                source_type="SNAPSHOT_FROM_PARENT",
                source_ref=(f"{context.target.parent_type}:{context.target.parent_id}:assignee:{source.source_id}"),
                protected=False,
            )
            grant = local_by_model.get(model_key)
            if grant is None:
                raise InvalidPermissionModeError(msg=f"Local Grant row missing for model {model_key}")
            mutation = self._sources.add_source(grant, snapshot)
            local_by_model[model_key] = mutation.grant
            snapshots.append(snapshot)
            staging.extend(
                replace(delta, phase="STAGE", sequence=len(staging) + index)
                for index, delta in enumerate(mutation.deltas)
            )
        result_grants = tuple(local_by_model[grant.model.model_key] for grant in context.local_grants)
        return result_grants, tuple(snapshots), tuple(staging)

    @staticmethod
    def _protected_only(
        grants: tuple[GrantSnapshot, ...],
    ) -> tuple[GrantSnapshot, ...]:
        result = []
        for grant in grants:
            protected = tuple(source for source in grant.sources if source.active and source.protected)
            result.append(
                replace(
                    grant,
                    active=bool(protected),
                    sources=protected,
                )
            )
        return tuple(result)

    @staticmethod
    def _context_checksum(context: ModeContext) -> str:
        return _checksum(
            {
                "catalog_release_id": context.current_catalog_release_id,
                "context_version": context.target.context_version,
                "mode": context.mode,
                "parent_id": context.target.parent_id,
                "parent_type": context.target.parent_type,
                "resource_id": context.target.resource_id,
                "resource_type": context.target.resource_type,
                "resource_version": context.target.resource_version,
                "tenant_id": context.target.tenant_id,
            }
        )

    @staticmethod
    def _mode_delta(
        target: VerifiedPermissionTarget,
        *,
        mode: str,
        action: str,
        sequence: int,
    ) -> ProjectionTupleDelta:
        return ProjectionTupleDelta(
            phase="COMMIT",
            sequence=sequence,
            action=action,
            user="user:*",
            relation=f"{mode.lower()}_mode",
            object=f"{target.resource_type}:{target.resource_id}",
        )

    async def _emit(
        self,
        context: ModeContext,
        draft: PermissionModeDraft,
        outcome: ProjectionOutcome,
    ) -> None:
        try:
            await self._events.emit(
                "permission_mode_switch",
                {
                    "from_mode": draft.current_mode,
                    "operation_id": outcome.operation_id,
                    "resource_type": context.target.resource_type,
                    "status": outcome.status,
                    "tenant_id": context.target.tenant_id,
                    "to_mode": draft.target_mode,
                },
            )
        except Exception:
            logger.exception("Failed to emit the F048 permission mode event")
            return
