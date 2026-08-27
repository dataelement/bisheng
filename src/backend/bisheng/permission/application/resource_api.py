"""F048 resource HTTP application adapter."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionVersionConflictError,
)
from bisheng.permission.application.resource_authorization import (
    ResourceAuthorizationRegistry,
)
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import (
    GrantMutationRequest,
    PermissionModeApplyRequest,
    PermissionModeDraftRequest,
    VerifiedPermissionTarget,
)
from bisheng.permission.domain.services.grant_service import (
    CanonicalGrantChange,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantSourceRecord,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.permission.domain.services.permission_explain_service import (
    PermissionExplanation,
)


class PermissionSubjectDirectoryPort(Protocol):
    """Business-owned subject validation and optional display decoration."""

    async def actor_projected_subjects(
        self,
        actor: PermissionActor,
    ) -> frozenset[str]: ...

    async def canonical_source(
        self,
        *,
        tenant_id: int,
        source_id: int,
        subject_type: str,
        subject_id: str,
        userset_relation: str | None,
        include_children: bool,
        # v3.0.0 F049 / D7: subject kinds the business side refuses by default
        # (service accounts) may only be authored by a caller that says so
        # explicitly. Resource-side endpoints never pass it.
        allow_service_account_subject: bool = False,
    ) -> GrantSourceRecord: ...

    async def display_names(
        self,
        subjects: tuple[tuple[str, str], ...],
    ) -> dict[tuple[str, str], str]: ...

    async def resource_display_names(
        self,
        resources: tuple[tuple[str, str], ...],
    ) -> dict[tuple[str, str], str]: ...


def _split_resource_key(resource_key: str) -> tuple[str, str]:
    """Split "knowledge_space:3377" into its type and id."""

    resource_type, _, resource_id = resource_key.partition(":")
    return resource_type, resource_id


def _encode_cursor(payload: dict[str, object]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _decode_cursor(value: str) -> dict[str, object]:
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(f"{value}{padding}")
        payload = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise PermissionVersionConflictError(msg="Permission roster cursor is invalid") from exc
    if not isinstance(payload, dict):
        raise PermissionVersionConflictError(msg="Permission roster cursor is invalid")
    return payload


class GrantChangeListenerPort(Protocol):
    """Business-owned subscriber to a successful grant mutation.

    Implementations live in the module that owns the resource type, so this
    layer never learns a business audit namespace (``app.*`` and friends). A
    listener **must not raise**: it runs after the mutation has already been
    committed and projected, so an exception here would report a failure for
    work that succeeded.
    """

    async def on_grants_changed(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        request: GrantMutationRequest,
        result,
        roster_before: Mapping[int, tuple[str, str]],
        roster_complete: bool,
    ) -> None: ...


class GrantChangeListenerRegistry:
    """Explicit resource_type → listener registry, wired at the composition root.

    An instance rather than a module-level dict, and populated by the
    composition root rather than by an import side effect: otherwise whether the
    hook is installed depends on module import order, and the failure mode is a
    silently missing audit trail with no error anywhere.
    """

    def __init__(self) -> None:
        self._listeners: dict[str, GrantChangeListenerPort] = {}

    def register(self, resource_type: str, listener: GrantChangeListenerPort) -> None:
        normalized = resource_type.strip().lower()
        if not normalized:
            raise ValueError("resource_type must not be empty")
        if normalized in self._listeners:
            raise ValueError(f"grant change listener already registered: {normalized}")
        self._listeners[normalized] = listener

    def get(self, resource_type: str) -> GrantChangeListenerPort | None:
        return self._listeners.get(resource_type.strip().lower())

    def registered_types(self) -> frozenset[str]:
        return frozenset(self._listeners)


#: One page is enough to name the subjects a REMOVE addresses: protected rows
#: aside, a roster long enough to overflow this is already past what the dialog
#: renders. Beyond it the record says so (``roster_truncated``) rather than
#: paying for a full scan on every revocation.
_ROSTER_SNAPSHOT_PAGE_SIZE = 50


class F048ResourcePermissionApi:
    """Coordinate verified resources without loading business rows itself."""

    def __init__(
        self,
        *,
        resources: ResourceAuthorizationRegistry,
        runtime: F048PermissionRuntime,
        subjects: PermissionSubjectDirectoryPort,
        grant_listeners: GrantChangeListenerRegistry | None = None,
    ) -> None:
        self._resources = resources
        self._runtime = runtime
        self._subjects = subjects
        self._grant_listeners = grant_listeners or GrantChangeListenerRegistry()

    async def get_grantable_models(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
    ) -> list[dict]:
        target = await self._target(
            resource_type,
            resource_id,
            actor,
            "manage_permission",
        )
        await self._runtime.require_manage_permission(actor, target)
        models = await self._runtime.grantable_models(
            actor=actor,
            target=target,
        )
        names = {item.snapshot.model_key: item.name for item in (await self._runtime.current_catalog()).models}
        return [
            {
                "key": model.model_key,
                "name": names.get(model.model_key, model.model_key),
                "level": model.derived_level,
                "active": model.active,
            }
            for model in models
        ]

    async def get_context(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
    ) -> dict:
        target = await self._target(
            resource_type,
            resource_id,
            actor,
            "visible",
        )
        can_manage = await self._can_manage(actor, target)
        if not can_manage:
            # A manager -- the owner, a granted manager, or an admin via the
            # identity short-circuit in check_action -- may always load the
            # permission context to render the management dialog. Everyone
            # else must be able to SEE the resource, which keeps the
            # read-only view for viewers. Gating on visibility ALONE wrongly
            # excluded admins: `visible` is deliberately not expanded for
            # super / tenant admins (see check_visible), so an admin who did
            # not own the resource got 19000 opening its authorization dialog
            # -- the sibling list_grants already gates on manage_permission,
            # not visibility. (F048 hosted-app authorization via the UI.)
            await self._require_visible(actor, target)
        mode = await self._runtime.current_mode(target)
        catalog = await self._runtime.current_catalog()
        return {
            "mode": mode.mode,
            "parent_type": target.parent_type,
            "parent_id": target.parent_id,
            "resource_version": target.resource_version,
            "catalog_release_id": catalog.release_id,
            "projection_state": mode.projection_state,
            "can_manage_permission": can_manage,
        }

    async def list_grants(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        cursor: str | None,
        page_size: int,
    ) -> dict:
        target = await self._target(
            resource_type,
            resource_id,
            actor,
            "manage_permission",
        )
        catalog = await self._runtime.current_catalog()
        after_id = self._after_id(
            cursor,
            target=target,
            catalog_release_id=catalog.release_id,
        )
        selected, has_more = await self._runtime.list_permission_sources_page(
            actor=actor,
            target=target,
            after_id=after_id,
            limit=page_size,
        )
        names = await self._subjects.display_names(
            tuple(dict.fromkeys((row.subject_type, row.subject_id) for row in selected))
        )
        # The permission layer holds a resource's identity, never its label — the
        # roster used to render "knowledge_space:3377" at users. Resolved through
        # the business side, the same way subject names already are.
        parents = tuple(
            dict.fromkeys(_split_resource_key(row.inherited_from) for row in selected if row.inherited_from)
        )
        parent_names = await self._subjects.resource_display_names(parents) if parents else {}
        model_names = {item.snapshot.model_key: item.name for item in catalog.models}
        data = [
            {
                "assignee_id": str(row.source_id),
                "assignee_version": row.source_version,
                "subject": {
                    "type": row.subject_type,
                    "id": row.subject_id,
                    "name": names.get((row.subject_type, row.subject_id)),
                },
                "model": {
                    "key": row.model_key,
                    "name": model_names.get(
                        row.model_key,
                        row.model_key,
                    ),
                    "level": row.model_level,
                    "active": True,
                },
                "source": {
                    "type": row.source_type,
                    "include_children": row.include_children,
                    "userset_relation": row.userset_relation,
                },
                "scope": row.scope,
                "inherited_from": row.inherited_from,
                "inherited_from_name": (
                    parent_names.get(_split_resource_key(row.inherited_from)) if row.inherited_from else None
                ),
                "protected": row.protected,
                "editable": row.editable,
            }
            for row in selected
        ]
        next_cursor = None
        if has_more and selected:
            next_cursor = _encode_cursor(
                {
                    "after_id": selected[-1].source_id,
                    "catalog_release_id": catalog.release_id,
                    "resource_id": target.resource_id,
                    "resource_type": target.resource_type,
                    "resource_version": target.resource_version,
                    "tenant_id": target.tenant_id,
                }
            )
        return {
            "data": data,
            "page_size": page_size,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }

    async def get_my_permissions(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
    ) -> dict:
        target = await self._target(
            resource_type,
            resource_id,
            actor,
            "visible",
        )
        if await self._public_preset_tool(resource_type, resource_id):
            mode = await self._runtime.mode_for_target(target)
            projection_degraded = mode.projection_state != "CURRENT" or mode.version != target.resource_version
            actions = await self._runtime.effective_actions(resource_type) if actor.super_admin else ()
            return {
                "mode": mode.mode,
                "actions": list(actions),
                "sources": [],
                "roster_complete": False,
                "projection_state": mode.projection_state,
                "projection_degraded": projection_degraded,
            }
        await self._require_visible(actor, target)
        mode = await self._runtime.mode_for_target(target)
        projection_degraded = mode.projection_state != "CURRENT" or mode.version != target.resource_version
        if self._privileged(actor, target):
            # A super admin / tenant admin is authorized on identity and holds
            # no grant rows, so the grant-derived explanation would report an
            # empty action set — "visible but powerless", which is exactly what
            # made the client show them as having no permissions. Report the
            # full effective action set for the resource type instead.
            actions = await self._runtime.effective_actions(resource_type)
            return {
                "mode": mode.mode,
                "actions": list(actions),
                "sources": [],
                "roster_complete": False,
                "projection_state": mode.projection_state,
                "projection_degraded": projection_degraded,
            }
        if projection_degraded:
            effective_actions = await self._runtime.effective_actions(resource_type)
            allowed = await asyncio.gather(
                *(self._runtime.check_action(actor, target, action) for action in effective_actions)
            )
            return {
                "mode": mode.mode,
                "actions": [
                    action for action, is_allowed in zip(effective_actions, allowed, strict=True) if is_allowed
                ],
                "sources": [],
                "roster_complete": False,
                "projection_state": mode.projection_state,
                "projection_degraded": True,
            }
        explanation = await self._explanation(
            actor,
            target,
            include_roster=False,
        )
        return {
            "mode": explanation.mode,
            "actions": list(explanation.action_codes),
            "sources": [
                {
                    "type": row.source_type,
                    "include_children": row.include_children,
                }
                for row in explanation.sources
            ],
            "roster_complete": False,
            "projection_state": mode.projection_state,
            "projection_degraded": False,
        }

    async def mutate_grants(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        request: GrantMutationRequest,
        allow_service_account_subject: bool = False,
    ) -> dict:
        """Apply grant changes.

        ``allow_service_account_subject`` (v3.0.0 F049 / D6 W2) is forwarded to
        the subject directory. It stays False for every resource-side caller;
        only the service-account detail page opts in, which is what keeps that
        page the single authoring path (AC-16 / INV-29).
        """
        target = await self._target(
            resource_type,
            resource_id,
            actor,
            "manage_permission",
        )
        listener = self._grant_listeners.get(resource_type)
        roster_before, roster_complete = await self._roster_snapshot(
            actor=actor,
            target=target,
            request=request,
            listener=listener,
        )
        add_count = sum(change.op.value == "ADD" for change in request.changes)
        source_ids = iter(await self._runtime.allocate_source_ids(add_count))
        canonical: list[CanonicalGrantChange] = []
        for change in request.changes:
            source = None
            if change.subject is not None:
                source = await self._subjects.canonical_source(
                    tenant_id=target.tenant_id,
                    source_id=next(source_ids),
                    subject_type=change.subject.type,
                    subject_id=change.subject.id,
                    userset_relation=change.subject.userset_relation,
                    include_children=change.subject.include_children,
                    allow_service_account_subject=allow_service_account_subject,
                )
            canonical.append(
                CanonicalGrantChange(
                    operation=change.op.value,
                    model_key=change.model_key,
                    source=source,
                    assignee_id=change.assignee_row_id,
                    expected_assignee_version=(change.expected_assignee_version),
                    target_model_key=change.target_model_key,
                )
            )
        result = await self._runtime.mutate_grants(
            actor=actor,
            target=target,
            changes=tuple(canonical),
            expected_resource_version=request.expected_resource_version,
            expected_catalog_release_id=(request.expected_catalog_release_id),
            idempotency_key=request.idempotency_key,
        )
        items = [
            {
                "assignee_id": str(source.source_id),
                "assignee_version": source.version,
                "subject": {
                    "type": source.subject_type,
                    "id": source.subject_id,
                    "name": None,
                },
                "model": {
                    "key": grant.model.model_key,
                    "name": grant.model.model_key,
                    "level": grant.model.derived_level,
                    "active": grant.model.active,
                },
                "source": {
                    "type": source.source_type,
                    "include_children": source.include_children,
                },
                "scope": "LOCAL",
                "inherited_from": None,
                "protected": source.protected,
                "editable": not source.protected,
            }
            for grant in result.grants
            if grant.active and grant.model.active
            for source in grant.sources
            if source.active
        ]
        if listener is not None:
            await listener.on_grants_changed(
                actor=actor,
                target=target,
                request=request,
                result=result,
                roster_before=roster_before,
                roster_complete=roster_complete,
            )
        return {
            "resource_version": result.resource_version,
            "items": items,
        }

    async def _roster_snapshot(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        request: GrantMutationRequest,
        listener: GrantChangeListenerPort | None,
    ) -> tuple[dict[int, tuple[str, str]], bool]:
        """``{source_id: (subject_type, subject_id)}`` read **before** the mutation.

        There is no way to recover it afterwards. A REMOVE/MOVE request carries
        only ``assignee_id`` plus a version — never the subject — and the result
        cannot fill the gap either: ``remove_source`` drops the revoked source
        row outright instead of marking it inactive, so the returned grants
        contain no trace of who lost access. Without this snapshot the audit
        record would read ``removed: [{assignee_id: 8143}]``, which no
        investigator can use.

        Paid for only when something actually needs it: no listener, or a
        request that only adds, and this returns immediately. ADD carries its
        own subject.
        """
        if listener is None:
            return {}, True
        if not any(change.op.value in ("REMOVE", "MOVE") for change in request.changes):
            return {}, True
        selected, has_more = await self._runtime.list_permission_sources_page(
            actor=actor,
            target=target,
            after_id=0,
            limit=_ROSTER_SNAPSHOT_PAGE_SIZE,
        )
        return {row.source_id: (row.subject_type, row.subject_id) for row in selected}, not has_more

    async def create_mode_draft(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        request: PermissionModeDraftRequest,
    ) -> dict:
        target = await self._target(
            resource_type,
            resource_id,
            actor,
            "manage_permission",
        )
        catalog = await self._runtime.current_catalog()
        if (
            target.resource_version != request.expected_resource_version
            or catalog.release_id != request.expected_catalog_release_id
        ):
            raise PermissionVersionConflictError()
        draft = await self._runtime.create_mode_draft(
            actor=actor,
            target=target,
            target_mode=request.target_mode.value,
        )
        return {
            "draft_id": draft.draft_id,
            "target_mode": draft.target_mode,
            "impact_checksum": draft.impact_checksum,
            # Either direction disturbs people: CUSTOM copies the inherited members
            # down, INHERIT drops the local ones. Counting only the copies reported
            # zero for a switch that was about to remove grants.
            "affected_assignees": (len(draft.snapshot_sources) + len(draft.discarded_sources)),
            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        }

    async def apply_mode_draft(
        self,
        *,
        resource_type: str,
        resource_id: str,
        draft_id: str,
        actor: PermissionActor,
        request: PermissionModeApplyRequest,
    ) -> dict:
        target = await self._target(
            resource_type,
            resource_id,
            actor,
            "manage_permission",
        )
        result = await self._runtime.apply_mode_draft(
            actor=actor,
            target=target,
            draft_id=draft_id,
            request=request,
        )
        return {
            "applied": result.applied,
            "mode": result.mode,
            "resource_version": result.resource_version,
        }

    async def _target(
        self,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ):
        return await self._resources.resolve(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            action=action,
        )

    async def _public_preset_tool(self, resource_type: str, resource_id: str) -> bool:
        if resource_type.strip().lower() != "tool":
            return False
        port_for = getattr(self._resources, "port_for", None)
        if port_for is None:
            return False
        port = port_for(resource_type)
        load_permission_record = getattr(port, "load_permission_record", None)
        if load_permission_record is None:
            return False
        record = await load_permission_record(resource_id=resource_id)
        return bool(record and getattr(record, "preset", False) and getattr(record, "system_allowlisted", False))

    async def _explanation(
        self,
        actor,
        target,
        *,
        include_roster: bool,
    ) -> PermissionExplanation:
        projected = await self._subjects.actor_projected_subjects(actor)
        return await self._runtime.explain_permissions(
            actor=actor,
            target=target,
            actor_projected_subjects=projected,
            include_roster=include_roster,
        )

    @staticmethod
    def _privileged(actor: PermissionActor, target) -> bool:
        """A super admin (any tenant) or a tenant admin of the target's tenant.

        This mirrors the identity shortcut the action decision path already
        applies in ``check_action``. It is intentionally NOT applied by
        ``check_visible``, which only consults FGA ``visible`` tuples — so an
        admin who can plainly manage a resource (``check_action`` waves them
        through for ``manage_permission``) was still denied at the visibility
        gate of the permission-management endpoints.
        """
        if actor.super_admin:
            return True
        return target.tenant_id == actor.current_tenant_id and target.tenant_id in actor.tenant_admin_tenant_ids

    async def _require_visible(self, actor, target) -> None:
        if self._privileged(actor, target):
            return
        if not await self._runtime.check_action(
            actor,
            target,
            "visible",
        ):
            raise PermissionDeniedError()

    async def _can_manage(self, actor, target) -> bool:
        try:
            return await self._runtime.check_action(
                actor,
                target,
                "manage_permission",
            )
        except PermissionDeniedError:
            return False

    @staticmethod
    def _after_id(
        cursor: str | None,
        *,
        target,
        catalog_release_id: int,
    ) -> int:
        if cursor is None:
            return 0
        payload = _decode_cursor(cursor)
        expected = {
            "tenant_id": target.tenant_id,
            "resource_type": target.resource_type,
            "resource_id": target.resource_id,
            "resource_version": target.resource_version,
            "catalog_release_id": catalog_release_id,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise PermissionVersionConflictError(msg="Permission roster cursor snapshot changed")
        after_id = payload.get("after_id")
        if not isinstance(after_id, int) or after_id < 0:
            raise PermissionVersionConflictError(msg="Permission roster cursor is invalid")
        return after_id
