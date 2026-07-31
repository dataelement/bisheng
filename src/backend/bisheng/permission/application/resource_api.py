"""F048 resource HTTP application adapter."""

from __future__ import annotations

import base64
import json
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
    ) -> GrantSourceRecord: ...

    async def display_names(
        self,
        subjects: tuple[tuple[str, str], ...],
    ) -> dict[tuple[str, str], str]: ...


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


class F048ResourcePermissionApi:
    """Coordinate verified resources without loading business rows itself."""

    def __init__(
        self,
        *,
        resources: ResourceAuthorizationRegistry,
        runtime: F048PermissionRuntime,
        subjects: PermissionSubjectDirectoryPort,
    ) -> None:
        self._resources = resources
        self._runtime = runtime
        self._subjects = subjects

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
        await self._require_visible(actor, target)
        mode = await self._runtime.current_mode(target)
        catalog = await self._runtime.current_catalog()
        can_manage = await self._can_manage(actor, target)
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
        model_names = {item.snapshot.model_key: item.name for item in catalog.models}
        data = [
            {
                "assignee_id": row.source_id,
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
                },
                "scope": row.scope,
                "inherited_from": row.inherited_from,
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
        await self._require_visible(actor, target)
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
        }

    async def mutate_grants(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        request: GrantMutationRequest,
    ) -> dict:
        target = await self._target(
            resource_type,
            resource_id,
            actor,
            "manage_permission",
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
                )
            canonical.append(
                CanonicalGrantChange(
                    operation=change.op.value,
                    model_key=change.model_key,
                    source=source,
                    assignee_id=change.assignee_id,
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
                "assignee_id": source.source_id,
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
        return {
            "resource_version": result.resource_version,
            "items": items,
        }

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
            "affected_assignees": len(draft.snapshot_sources),
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

    async def _require_visible(self, actor, target) -> None:
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
