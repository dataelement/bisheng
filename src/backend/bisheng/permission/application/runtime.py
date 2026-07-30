"""Production composition for the business-independent F048 runtime."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any

from loguru import logger

from bisheng.common.errcode.permission import (
    AuthorizationModelMismatchError,
    InvalidPermissionModeError,
    PermissionInvalidResourceError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.permission.application.control_state import (
    RuntimeCatalogSnapshot,
    SqlGrantMutationState,
    SqlModeState,
    SqlOwnerProjectionState,
    SqlPermissionControlState,
    require_owner_model,
)
from bisheng.permission.application.sql_runtime import (
    DenyListObjectsPolicy,
    ExternalProjectionScopePort,
    RedisConsistencyMarker,
    SqlCatalogDecisionState,
    SqlPermissionScopeFence,
    build_sql_projection_runtime,
    stable_assignee_id,
    stable_grant_key,
)
from bisheng.permission.domain.models import ProjectionOperationStatus
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import (
    CanonicalGrantChange,
    GrantCapability,
    GrantMutationContext,
    GrantService,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.mode_service import (
    ModeContext,
    ModeService,
    PermissionModeDraft,
)
from bisheng.permission.domain.services.owner_service import (
    F048OwnerProjectionService,
    OwnerProjectionContext,
)
from bisheng.permission.domain.services.permission_action_service import (
    F048PermissionService,
    PermissionActor,
)
from bisheng.permission.domain.services.permission_explain_service import (
    InheritedGrantSet,
    PermissionExplainContext,
    PermissionExplainService,
    PermissionExplanation,
)
from bisheng.permission.domain.services.projection_service import (
    ProjectionOutcome,
    ProjectionPlan,
    ProjectionService,
    ProjectionTupleDelta,
)
from bisheng.permission.domain.services.resource_lifecycle_policy import (
    build_delete_plan,
    build_move_plan,
    copy_permission_mode,
    default_permission_mode,
)

HIGHER_CONSISTENCY = "HIGHER_CONSISTENCY"


def _idempotency_key(*parts: object) -> str:
    canonical = "|".join(str(part) for part in parts)
    return f"f048:{sha256(canonical.encode()).hexdigest()[:54]}"


@dataclass(frozen=True, slots=True)
class F048RuntimeComponents:
    facade: F048PermissionRuntime
    state: SqlPermissionControlState
    projection: ProjectionService
    marker: RedisConsistencyMarker


class F048PermissionRuntime:
    """Sole online facade after a business Service verifies resource facts."""

    def __init__(
        self,
        *,
        client: FGAClient,
        state: SqlPermissionControlState,
        marker: RedisConsistencyMarker,
        decision: F048PermissionService,
        projection: ProjectionService,
        sources: GrantSourceService,
        owner: F048OwnerProjectionService,
        grants: GrantService,
        modes: ModeService,
        explain: PermissionExplainService,
    ) -> None:
        self._client = client
        self._state = state
        self._marker = marker
        self._decision = decision
        self._projection = projection
        self._sources = sources
        self._owner = owner
        self._grants = grants
        self._modes = modes
        self._explain = explain

    async def check_action(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool:
        if action == "visible":
            return await self._decision.check_visible(actor, target)
        return await self._decision.check_action(actor, target, action)

    async def batch_check_actions(
        self,
        actor: PermissionActor,
        targets: tuple[VerifiedPermissionTarget, ...],
        action: str,
    ) -> tuple[bool, ...]:
        if action != "visible":
            return await self._decision.batch_check_actions(
                actor,
                targets,
                action,
            )
        return await self._decision.batch_check_visible(actor, targets)

    async def current_catalog(self) -> RuntimeCatalogSnapshot:
        return await self._runtime_catalog()

    async def allocate_source_ids(self, count: int) -> tuple[int, ...]:
        return await self._state.allocate_source_ids(count)

    async def require_manage_permission(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> None:
        await self._require_manage_permission(actor, target)

    async def current_mode(
        self,
        target: VerifiedPermissionTarget,
    ):
        return await self._require_current_target(target)

    async def list_action_objects(
        self,
        actor: PermissionActor,
        *,
        resource_type: str,
        action: str,
        max_results: int,
    ) -> tuple[str, ...] | None:
        return await self._decision.list_action_objects(
            actor,
            resource_type=resource_type,
            action=action,
            max_results=max_results,
        )

    async def get_permission_version(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
    ) -> tuple[int, str]:
        return await self._state.permission_version(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )

    async def authorize_created(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        owner_user_id: int | None,
        mode: str,
        source_type: str = "CREATOR",
        protected: bool = True,
        idempotency_key: str | None = None,
    ):
        if (
            owner_user_id is None
            or owner_user_id <= 0
            or source_type != "CREATOR"
            or not protected
            or target.resource_version != 0
        ):
            raise PermissionInvalidResourceError()
        expected_mode = default_permission_mode(
            target.resource_type,
            has_parent=target.parent_type is not None,
        )
        if mode.upper() != expected_mode:
            raise InvalidPermissionModeError(msg=f"{target.resource_type} must start in {expected_mode}")
        catalog = await self._runtime_catalog()
        owner_model = require_owner_model(catalog)
        grant, source_id = await self._state.owner_grant(
            target=target,
            owner_user_id=owner_user_id,
            source_service=self._sources,
            owner_model=owner_model,
        )
        return await self._owner.project_created(
            OwnerProjectionContext(
                target=target,
                owner_grant=grant,
                source_id=source_id,
                owner_user_id=owner_user_id,
                system_owned=False,
                system_predicate=False,
                store_id=catalog.store_id,
                model_id=catalog.model_id,
                operator_id=actor.user_id,
                idempotency_key=idempotency_key
                or _idempotency_key(
                    "create",
                    target.tenant_id,
                    target.resource_type,
                    target.resource_id,
                    owner_user_id,
                ),
                permission_mode=mode.upper(),
            )
        )

    async def authorize_system_owned(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action_codes: tuple[str, ...],
        idempotency_key: str | None = None,
    ):
        if target.resource_version != 0:
            raise PermissionInvalidResourceError()
        expected_mode = default_permission_mode(
            target.resource_type,
            has_parent=target.parent_type is not None,
        )
        if expected_mode != "CUSTOM":
            raise InvalidPermissionModeError()
        catalog = await self._runtime_catalog()
        return await self._owner.project_created(
            OwnerProjectionContext(
                target=target,
                owner_grant=None,
                source_id=1,
                owner_user_id=None,
                system_owned=True,
                system_predicate=True,
                store_id=catalog.store_id,
                model_id=catalog.model_id,
                operator_id=actor.user_id,
                idempotency_key=idempotency_key
                or _idempotency_key(
                    "system-create",
                    target.tenant_id,
                    target.resource_type,
                    target.resource_id,
                ),
                system_action_codes=tuple(sorted(set(action_codes))),
                permission_mode="CUSTOM",
            )
        )

    async def project_delete(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        idempotency_key: str | None = None,
    ) -> ProjectionOutcome:
        catalog = await self._runtime_catalog()
        await self._require_current_target(target)
        plan = build_delete_plan(
            target,
            store_id=catalog.store_id,
            model_id=catalog.model_id,
            operator_id=actor.user_id,
            idempotency_key=idempotency_key
            or _idempotency_key(
                "delete",
                target.tenant_id,
                target.resource_type,
                target.resource_id,
                target.resource_version,
            ),
        )
        operation = await self._projection.prepare(plan)
        if str(operation.status) == ProjectionOperationStatus.PREPARED.value:
            try:
                await self._state.mark_projecting(
                    target=target,
                    expected_catalog_release_id=catalog.release_id,
                    operation_id=int(operation.id),
                )
            except Exception as exc:
                await self._projection.abandon_prepared(plan, exc)
                raise
        return await self._projection.execute(plan)

    async def project_parent_change(
        self,
        *,
        actor: PermissionActor,
        old_target: VerifiedPermissionTarget,
        target: VerifiedPermissionTarget,
        mode: str,
        idempotency_key: str | None = None,
    ) -> ProjectionOutcome:
        if (
            old_target.tenant_id != target.tenant_id
            or old_target.resource_type != target.resource_type
            or old_target.resource_id != target.resource_id
            or old_target.resource_version != target.resource_version
            or old_target.parent_type is None
            or old_target.parent_id is None
            or target.parent_type is None
            or target.parent_id is None
            or (
                old_target.parent_type,
                old_target.parent_id,
            )
            == (target.parent_type, target.parent_id)
        ):
            raise PermissionInvalidResourceError()
        catalog = await self._runtime_catalog()
        await self._require_current_target(old_target)
        plan = build_move_plan(
            target,
            old_parent=(
                old_target.parent_type,
                old_target.parent_id,
            ),
            new_parent=(target.parent_type, target.parent_id),
            mode=mode,
            store_id=catalog.store_id,
            model_id=catalog.model_id,
            operator_id=actor.user_id,
            idempotency_key=idempotency_key
            or _idempotency_key(
                "move",
                target.tenant_id,
                target.resource_type,
                target.resource_id,
                target.resource_version,
                target.parent_type,
                target.parent_id,
            ),
        )
        operation = await self._projection.prepare(plan)
        if str(operation.status) == ProjectionOperationStatus.PREPARED.value:
            try:
                await self._state.mark_projecting(
                    target=old_target,
                    parent_type=target.parent_type,
                    parent_id=target.parent_id,
                    expected_catalog_release_id=catalog.release_id,
                    operation_id=int(operation.id),
                )
            except Exception as exc:
                await self._projection.abandon_prepared(plan, exc)
                raise
        return await self._projection.execute(plan)

    async def project_copy(
        self,
        *,
        actor: PermissionActor,
        source: VerifiedPermissionTarget,
        target: VerifiedPermissionTarget,
        owner_user_id: int,
        mode: str,
    ):
        if (
            source.tenant_id != target.tenant_id
            or source.resource_type != target.resource_type
            or source.resource_id == target.resource_id
            or target.resource_version != 0
            or owner_user_id <= 0
        ):
            raise PermissionInvalidResourceError()
        source_mode = await self._require_current_target(source)
        copy_mode, copy_local = copy_permission_mode(mode)
        if source_mode.mode.upper() != copy_mode:
            raise PermissionVersionConflictError(msg="Source permission mode changed before copy")
        catalog = await self._runtime_catalog()
        models = tuple(item.snapshot for item in catalog.models)
        copy_grants: tuple[GrantSnapshot, ...] = ()
        copy_deltas = ()
        owner_model = require_owner_model(catalog)
        if copy_local:
            copy_grants, copy_deltas = await self._copy_custom_grants(
                source=source,
                target=target,
                models=models,
            )
            owner_grant = next(
                (grant for grant in copy_grants if grant.model.model_key == "owner"),
                None,
            )
            if owner_grant is None:
                owner_grant = self._empty_grant(
                    target=target,
                    model=owner_model,
                )
                copy_grants = (*copy_grants, owner_grant)
            provisional = self._sources.canonicalize_source(
                source_id=1,
                subject_type="user",
                subject_id=str(owner_user_id),
                source_type="CREATOR",
                source_ref=(f"{target.resource_type}:{target.resource_id}"),
                protected=True,
            )
            source_id = stable_assignee_id(
                grant_key=owner_grant.grant_id,
                source_fingerprint=provisional.source_fingerprint,
            )
        else:
            owner_grant, source_id = await self._state.owner_grant(
                target=target,
                owner_user_id=owner_user_id,
                source_service=self._sources,
                owner_model=owner_model,
            )
        return await self._owner.project_created(
            OwnerProjectionContext(
                target=target,
                owner_grant=owner_grant,
                source_id=source_id,
                owner_user_id=owner_user_id,
                system_owned=False,
                system_predicate=False,
                store_id=catalog.store_id,
                model_id=catalog.model_id,
                operator_id=actor.user_id,
                idempotency_key=_idempotency_key(
                    "copy",
                    source.tenant_id,
                    source.resource_type,
                    source.resource_id,
                    target.resource_id,
                ),
                permission_mode=copy_mode,
                operation_type="RESOURCE_COPY",
                copy_grants=copy_grants,
                copy_deltas=copy_deltas,
            )
        )

    async def _copy_custom_grants(
        self,
        *,
        source: VerifiedPermissionTarget,
        target: VerifiedPermissionTarget,
        models: tuple[GrantModelSnapshot, ...],
    ) -> tuple[
        tuple[GrantSnapshot, ...],
        tuple[ProjectionTupleDelta, ...],
    ]:
        source_grants = await self._state.load_grants(
            target=source,
            models=models,
        )
        copied: list[GrantSnapshot] = []
        deltas: list[ProjectionTupleDelta] = []
        for source_grant in source_grants:
            target_grant = self._empty_grant(
                target=target,
                model=source_grant.model,
            )
            for source_row in source_grant.sources:
                if not source_row.active or source_row.protected:
                    continue
                provisional = self._sources.canonicalize_source(
                    source_id=1,
                    subject_type=source_row.subject_type,
                    subject_id=source_row.subject_id,
                    userset_relation=source_row.userset_relation,
                    include_children=source_row.include_children,
                    source_type=source_row.source_type,
                    source_ref=source_row.source_ref,
                    protected=False,
                )
                copied_source = self._sources.canonicalize_source(
                    source_id=stable_assignee_id(
                        grant_key=target_grant.grant_id,
                        source_fingerprint=(provisional.source_fingerprint),
                    ),
                    subject_type=source_row.subject_type,
                    subject_id=source_row.subject_id,
                    userset_relation=source_row.userset_relation,
                    include_children=source_row.include_children,
                    source_type=source_row.source_type,
                    source_ref=source_row.source_ref,
                    protected=False,
                )
                mutation = self._sources.add_source(
                    target_grant,
                    copied_source,
                )
                target_grant = mutation.grant
                deltas.extend(mutation.deltas)
            if target_grant.active:
                copied.append(target_grant)
        return tuple(copied), tuple(deltas)

    @staticmethod
    def _empty_grant(
        *,
        target: VerifiedPermissionTarget,
        model: GrantModelSnapshot,
    ) -> GrantSnapshot:
        return GrantSnapshot(
            grant_id=stable_grant_key(
                tenant_id=target.tenant_id,
                resource_type=target.resource_type,
                resource_id=target.resource_id,
                model_key=model.model_key,
            ),
            tenant_id=target.tenant_id,
            resource_type=target.resource_type,
            resource_id=target.resource_id,
            model=model,
            active=False,
            sources=(),
            version=0,
        )

    async def build_grant_context(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> GrantMutationContext:
        catalog = await self._runtime_catalog()
        mode = await self._require_current_target(target)
        models = tuple(item.snapshot for item in catalog.models)
        grants = await self._state.load_grants(
            target=target,
            models=models,
        )
        system_authorized = self._system_authorized(actor, target)
        capabilities = () if system_authorized else await self._grant_capabilities(actor, target)
        return GrantMutationContext(
            target=target,
            current_catalog_release_id=catalog.release_id,
            store_id=catalog.store_id,
            model_id=catalog.model_id,
            operator_id=actor.user_id,
            mode=mode.mode,
            system_authorized=system_authorized,
            capabilities=capabilities,
            models=models,
            grants=grants,
        )

    async def grantable_models(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> tuple[GrantModelSnapshot, ...]:
        return self._grants.grantable_models(await self.build_grant_context(actor=actor, target=target))

    async def mutate_grants(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        changes: tuple[CanonicalGrantChange, ...],
        expected_resource_version: int,
        expected_catalog_release_id: int,
        idempotency_key: str,
    ):
        context = await self.build_grant_context(
            actor=actor,
            target=target,
        )
        return await self._grants.mutate(
            context,
            changes=changes,
            expected_resource_version=expected_resource_version,
            expected_catalog_release_id=expected_catalog_release_id,
            idempotency_key=idempotency_key,
        )

    async def sync_business_source_model(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        source,
        model_key: str | None,
        idempotency_key: str,
    ):
        """Project one verified business-owned membership source.

        The calling business adapter owns membership lookup and source
        canonicalization. This method only reconciles permission state and uses a
        system-authorized Grant mutation so a membership event is not constrained
        by the member/operator's own grant level.
        """

        if (
            source.protected
            or not source.active
            or source.source_type
            not in {
                "CHANNEL_MEMBERSHIP",
                "SPACE_MEMBERSHIP",
                "DEPARTMENT",
            }
        ):
            raise PermissionInvalidResourceError()
        context = replace(
            await self.build_grant_context(actor=actor, target=target),
            system_authorized=True,
            capabilities=(),
        )
        matches = tuple(
            (grant.model.model_key, row)
            for grant in context.grants
            for row in grant.sources
            if row.active and row.source_fingerprint == source.source_fingerprint
        )
        for _, existing in matches:
            if (
                existing.source_type != source.source_type
                or existing.source_ref != source.source_ref
                or existing.projected_subject != source.projected_subject
                or existing.userset_relation != source.userset_relation
                or existing.include_children != source.include_children
            ):
                raise PermissionVersionConflictError(msg="Business permission source fingerprint collision")

        changes: list[CanonicalGrantChange] = []
        if model_key is None:
            changes.extend(
                CanonicalGrantChange(
                    operation="REMOVE",
                    assignee_id=existing.source_id,
                    expected_assignee_version=existing.version,
                )
                for _, existing in matches
            )
        else:
            target_grant = next(
                (grant for grant in context.grants if grant.model.model_key == model_key),
                None,
            )
            if target_grant is None:
                raise PermissionInvalidResourceError()
            same_model = tuple(row for existing_model, row in matches if existing_model == model_key)
            other_models = tuple(row for existing_model, row in matches if existing_model != model_key)
            if same_model:
                changes.extend(
                    CanonicalGrantChange(
                        operation="REMOVE",
                        assignee_id=existing.source_id,
                        expected_assignee_version=existing.version,
                    )
                    for existing in other_models
                )
            elif other_models:
                moving, *duplicates = other_models
                changes.append(
                    CanonicalGrantChange(
                        operation="MOVE",
                        assignee_id=moving.source_id,
                        expected_assignee_version=moving.version,
                        target_model_key=model_key,
                    )
                )
                changes.extend(
                    CanonicalGrantChange(
                        operation="REMOVE",
                        assignee_id=existing.source_id,
                        expected_assignee_version=existing.version,
                    )
                    for existing in duplicates
                )
            else:
                stable_source = replace(
                    source,
                    source_id=stable_assignee_id(
                        grant_key=target_grant.grant_id,
                        source_fingerprint=source.source_fingerprint,
                    ),
                )
                changes.append(
                    CanonicalGrantChange(
                        operation="ADD",
                        model_key=model_key,
                        source=stable_source,
                    )
                )
        if not changes:
            return None
        return await self._grants.mutate(
            context,
            changes=tuple(changes),
            expected_resource_version=target.resource_version,
            expected_catalog_release_id=(context.current_catalog_release_id),
            idempotency_key=idempotency_key,
        )

    async def remove_ordinary_sources(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        idempotency_key: str,
    ):
        """Remove one bounded batch of non-protected local sources.

        Callers must keep resolving the current permission version and invoke
        this method until it returns ``None``.  A single Grant mutation is
        intentionally capped at 50 change items by the public contract.
        """

        context = replace(
            await self.build_grant_context(actor=actor, target=target),
            system_authorized=True,
            capabilities=(),
        )
        changes = tuple(
            CanonicalGrantChange(
                operation="REMOVE",
                assignee_id=source.source_id,
                expected_assignee_version=source.version,
            )
            for grant in context.grants
            for source in grant.sources
            if source.active and not source.protected
        )[:50]
        if not changes:
            return None
        return await self._grants.mutate(
            context,
            changes=changes,
            expected_resource_version=target.resource_version,
            expected_catalog_release_id=(context.current_catalog_release_id),
            idempotency_key=idempotency_key,
        )

    async def sync_public_reader(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        enabled: bool,
        idempotency_key: str,
    ):
        """Durably mirror one business-verified public-read predicate."""

        if target.resource_type != "knowledge_space":
            raise PermissionInvalidResourceError()
        catalog = await self._runtime_catalog()
        await self._require_current_target(target)
        tuple_key = {
            "user": "user:*",
            "relation": "public_reader",
            "object": f"{target.resource_type}:{target.resource_id}",
        }
        rows = await self._client.read_tuples(
            **tuple_key,
            consistency=HIGHER_CONSISTENCY,
        )
        present = any(
            row.get("user") == tuple_key["user"]
            and row.get("relation") == tuple_key["relation"]
            and row.get("object") == tuple_key["object"]
            for row in rows
        )
        if present is enabled:
            return None
        plan = ProjectionPlan(
            tenant_id=target.tenant_id,
            idempotency_key=idempotency_key,
            operation_type="RESOURCE_PUBLIC_READER_SYNC",
            scope_type="resource",
            scope_key=f"{target.resource_type}:{target.resource_id}",
            expected_version=target.resource_version,
            target_version=target.resource_version + 1,
            store_id=catalog.store_id,
            model_id=catalog.model_id,
            operator_id=actor.user_id,
            change_item_count=1,
            deltas=(
                ProjectionTupleDelta(
                    phase="COMMIT",
                    sequence=0,
                    action="WRITE" if enabled else "DELETE",
                    **tuple_key,
                ),
            ),
        )
        operation = await self._projection.prepare(plan)
        if str(operation.status) == ProjectionOperationStatus.PREPARED.value:
            try:
                await self._state.mark_projecting(
                    target=target,
                    expected_catalog_release_id=catalog.release_id,
                    operation_id=int(operation.id),
                )
            except Exception as exc:
                await self._projection.abandon_prepared(plan, exc)
                raise
        return await self._projection.execute(plan)

    async def create_mode_draft(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        target_mode: str,
    ) -> PermissionModeDraft:
        context = await self._mode_context(actor=actor, target=target)
        await self._require_manage_permission(actor, target)
        return await self._modes.create_draft(
            context,
            target_mode=target_mode,
        )

    async def apply_mode_draft(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        draft_id: str,
        request: Any,
    ):
        context = await self._mode_context(actor=actor, target=target)
        await self._require_manage_permission(actor, target)
        draft = await self._state.get_mode_draft(draft_id)
        if draft is None:
            raise PermissionPublishNotReadyError(msg="Permission mode draft is missing or expired")
        return await self._modes.apply(
            context,
            draft,
            expected_resource_version=request.expected_resource_version,
            expected_catalog_release_id=(request.expected_catalog_release_id),
            confirmed=request.confirmed,
            idempotency_key=request.idempotency_key,
        )

    async def explain_permissions(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        actor_projected_subjects: frozenset[str],
        include_roster: bool = True,
    ) -> PermissionExplanation:
        catalog = await self._runtime_catalog()
        mode = await self._require_current_target(target)
        models = tuple(item.snapshot for item in catalog.models)
        local = await self._state.load_grants(
            target=target,
            models=models,
        )
        inherited_grants = await self._state.inherited_grants(
            target=target,
            models=models,
        )
        can_manage = include_roster and self._system_authorized(actor, target)
        if include_roster and not can_manage:
            can_manage = await self.check_action(
                actor,
                target,
                "manage_permission",
            )
        inherited = None
        if target.parent_type and target.parent_id:
            inherited = InheritedGrantSet(
                resource_type=target.parent_type,
                resource_id=target.parent_id,
                grants=inherited_grants,
            )
        return await self._explain.explain(
            PermissionExplainContext(
                tenant_id=target.tenant_id,
                resource_type=target.resource_type,
                resource_id=target.resource_id,
                resource_version=target.resource_version,
                mode=mode.mode,
                parent_type=target.parent_type,
                parent_id=target.parent_id,
                local_grants=local,
                inherited=inherited,
                actor_projected_subjects=actor_projected_subjects,
                can_manage_roster=can_manage,
            )
        )

    async def list_permission_sources_page(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        after_id: int,
        limit: int,
    ):
        """Return one SQL-cursor roster page without materializing the roster."""

        await self._require_manage_permission(actor, target)
        catalog = await self._runtime_catalog()
        mode = await self._require_current_target(target)
        return await self._state.load_source_page(
            target=target,
            mode=mode.mode,
            models=tuple(item.snapshot for item in catalog.models),
            after_id=after_id,
            limit=limit,
        )

    async def _mode_context(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> ModeContext:
        catalog = await self._runtime_catalog()
        mode = await self._require_current_target(target)
        models = tuple(item.snapshot for item in catalog.models)
        local = await self._state.load_grants(
            target=target,
            models=models,
        )
        inherited = await self._state.inherited_grants(
            target=target,
            models=models,
        )
        return ModeContext(
            target=target,
            mode=mode.mode,
            current_catalog_release_id=catalog.release_id,
            store_id=catalog.store_id,
            model_id=catalog.model_id,
            operator_id=actor.user_id,
            local_grants=local,
            inherited_grants=inherited,
        )

    async def _grant_capabilities(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> tuple[GrantCapability, ...]:
        if not await self._decision.check_action(
            actor,
            target,
            "manage_permission",
        ):
            return ()
        consistency = await self._consistency(target)
        checks = [
            {
                "user": f"user:{actor.user_id}",
                "relation": f"can_grant_level_{level}",
                "object": f"{target.resource_type}:{target.resource_id}",
            }
            for level in range(1, 5)
        ]
        try:
            allowed = await self._client.batch_check(
                checks,
                consistency=consistency,
            )
        except Exception as exc:
            from bisheng.common.errcode.permission import (
                PermissionFGAUnavailableError,
            )

            raise PermissionFGAUnavailableError(exception=exc) from exc
        return tuple(
            GrantCapability(
                model=GrantModelSnapshot(
                    model_key=f"effective-grant-level-{level}",
                    active=True,
                    action_codes=("manage_permission",),
                    derived_level=level,
                    allow_same_level=True,
                ),
                source_key=f"openfga:can_grant_level_{level}",
            )
            for level, is_allowed in enumerate(allowed, start=1)
            if is_allowed
        )

    async def _require_manage_permission(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> None:
        if self._system_authorized(actor, target):
            return
        if not await self.check_action(
            actor,
            target,
            "manage_permission",
        ):
            from bisheng.common.errcode.permission import (
                PermissionDeniedError,
            )

            raise PermissionDeniedError()

    async def _runtime_catalog(self) -> RuntimeCatalogSnapshot:
        catalog = await self._state.current_catalog()
        if catalog.store_id != self._client.store_id or catalog.model_id != self._client.model_id:
            raise AuthorizationModelMismatchError(msg="CURRENT Catalog does not match the process OpenFGA pin")
        return catalog

    async def _require_current_target(
        self,
        target: VerifiedPermissionTarget,
    ):
        mode = await self._state.mode_for_target(target)
        if (
            mode.version != target.resource_version
            or mode.parent_type != target.parent_type
            or mode.parent_id != target.parent_id
            or mode.projection_state != "CURRENT"
        ):
            raise PermissionPublishNotReadyError(msg="Verified target does not match permission mirror")
        return mode

    async def _consistency(
        self,
        target: VerifiedPermissionTarget,
    ) -> str | None:
        try:
            return await self._marker.consistency_for(
                tenant_id=target.tenant_id,
                resource_type=target.resource_type,
                resource_id=target.resource_id,
            )
        except Exception:
            logger.exception(
                "Failed to read the F048 recent-change marker; using higher consistency",
            )
            return HIGHER_CONSISTENCY

    @staticmethod
    def _system_authorized(
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> bool:
        return actor.super_admin or (
            target.tenant_id == actor.current_tenant_id and target.tenant_id in actor.tenant_admin_tenant_ids
        )


async def build_f048_permission_runtime(
    client: FGAClient,
    *,
    external_scopes: dict[str, ExternalProjectionScopePort] | None = None,
) -> F048RuntimeComponents:
    """Compose SQL/Redis/OpenFGA adapters once for the current process."""

    sql_projection = await build_sql_projection_runtime(
        client,
        external_scopes=external_scopes,
    )
    projection = ProjectionService(
        repository=sql_projection.repository,
        marker=sql_projection.marker,
        scope_guard=sql_projection.scope_guard,
        fga=sql_projection.fga,
        finalizer=sql_projection.finalizer,
    )
    state = SqlPermissionControlState()
    decision = F048PermissionService(
        catalog=SqlCatalogDecisionState(
            expected_store_id=client.store_id,
            expected_model_id=client.model_id,
        ),
        scope_fence=SqlPermissionScopeFence(),
        marker=sql_projection.marker,
        fga=client,
        list_policy=DenyListObjectsPolicy(),
    )
    sources = GrantSourceService()
    owner = F048OwnerProjectionService(
        source_service=sources,
        projection=projection,
        state=SqlOwnerProjectionState(state),
    )
    grants = GrantService(
        source_service=sources,
        projection=projection,
        state=SqlGrantMutationState(state),
    )
    modes = ModeService(
        source_service=sources,
        projection=projection,
        state=SqlModeState(state),
    )
    facade = F048PermissionRuntime(
        client=client,
        state=state,
        marker=sql_projection.marker,
        decision=decision,
        projection=projection,
        sources=sources,
        owner=owner,
        grants=grants,
        modes=modes,
        explain=PermissionExplainService(),
    )
    await facade._runtime_catalog()
    return F048RuntimeComponents(
        facade=facade,
        state=state,
        projection=projection,
        marker=sql_projection.marker,
    )
