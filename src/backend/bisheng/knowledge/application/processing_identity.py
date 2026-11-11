"""Credential origins and authority ceilings for knowledge processing only."""

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_current_tenant_id,
    management_tenant_scope,
    tenant_execution_scope,
)
from bisheng.knowledge.domain.schemas.processing_actor_subject import processing_actor_subject
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.open_api.application.knowledge_processing_identity import (
    capture_knowledge_processing_reference,
    restore_knowledge_processing_reference,
)
from bisheng.open_api.application.runtime_authorization import without_open_api_identity
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
from bisheng.permission.application.identity import (
    PermissionActor,
    get_current_permission_actor,
    reset_current_permission_actor,
    resolve_permission_actor,
    set_current_permission_actor,
)
from bisheng.user.application.runtime_identity import resolve_web_runtime_identity

_ACTIONS = frozenset({"edit", "rename", "move", "upload_file", "delete", "download"})
_WEB_FIELDS = frozenset({"kind", "user_id", "tenant_id", "token_version", "expires_at"})
_ORIGIN_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "actor_user_id",
        "space_id",
        "required_action",
        "entry_kind",
        "actor",
        "credential_reference",
    }
)


@dataclass(frozen=True, slots=True)
class FrozenProcessingActor:
    actor_user_id: int
    tenant_id: int
    space_id: int
    required_action: str
    entry_kind: str
    payload_json: str

    @property
    def reference(self) -> dict:
        return json.loads(self.payload_json)


def _actor_facts(actor: PermissionActor) -> dict:
    if (
        not isinstance(actor, PermissionActor)
        or actor.subject_id <= 0
        or actor.tenant_id <= 0
        or actor.data_scope not in {DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL}
    ):
        raise PermissionDeniedError(reason="processing_actor_invalid")
    return {
        "subject_type": actor.subject_type,
        "subject_id": actor.subject_id,
        "tenant_id": actor.tenant_id,
        "super_admin": actor.super_admin,
        "tenant_admin_tenant_ids": sorted(actor.tenant_admin_tenant_ids),
        "data_scope": actor.data_scope,
    }


def _web_reference(reference, user=None) -> dict:
    try:
        if (
            not isinstance(reference, dict)
            or set(reference) != _WEB_FIELDS
            or reference["kind"] != "web_session"
            or any(type(reference[key]) is not int for key in ("user_id", "tenant_id", "token_version"))
            or reference["user_id"] <= 0
            or reference["tenant_id"] <= 0
            or reference["token_version"] < 0
        ):
            raise ValueError("invalid web origin")
        expires = datetime.fromisoformat(reference["expires_at"])
        expires = expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires.astimezone(UTC)
        if expires <= datetime.now(UTC):
            raise ValueError("expired web origin")
        if user is not None and (reference["user_id"], reference["tenant_id"], reference["token_version"]) != (
            user.user_id,
            user.tenant_id,
            user.token_version,
        ):
            raise ValueError("web identity changed")
        return deepcopy(reference)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise PermissionDeniedError(reason="processing_web_origin_invalid") from error


def _narrow_actor(current: PermissionActor, ceiling: dict) -> PermissionActor:
    try:
        actual = _actor_facts(current)
        if (
            set(ceiling) != set(actual)
            or any(type(ceiling[key]) is not int or ceiling[key] <= 0 for key in ("subject_id", "tenant_id"))
            or any(actual[key] != ceiling[key] for key in ("subject_type", "subject_id", "tenant_id"))
            or type(ceiling["super_admin"]) is not bool
            or not isinstance(ceiling["tenant_admin_tenant_ids"], list)
            or any(type(value) is not int or value <= 0 for value in ceiling["tenant_admin_tenant_ids"])
            or ceiling["data_scope"] not in {DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL}
        ):
            raise ValueError("processing identity changed")
        return replace(
            current,
            super_admin=current.super_admin and ceiling["super_admin"],
            tenant_admin_tenant_ids=current.tenant_admin_tenant_ids & frozenset(ceiling["tenant_admin_tenant_ids"]),
            data_scope=DATA_SCOPE_PERSONAL
            if DATA_SCOPE_PERSONAL in {current.data_scope, ceiling["data_scope"]}
            else DATA_SCOPE_ALL,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PermissionDeniedError(reason="processing_actor_changed") from error


async def capture_processing_actor(
    identity, *, space_id: int, required_action: str, entry_kind: str
) -> FrozenProcessingActor:
    tenant = get_current_tenant_id()
    if (
        type(tenant) is not int
        or tenant <= 0
        or type(space_id) is not int
        or space_id <= 0
        or required_action not in _ACTIONS
        or entry_kind not in {"web", "open_api"}
    ):
        raise PermissionDeniedError(reason="processing_origin_context_invalid")
    principal = get_current_open_api_principal()
    if entry_kind == "open_api":
        if principal is None or principal.tenant_id != tenant:
            raise PermissionDeniedError(reason="processing_api_origin_invalid")
        actor = get_current_permission_actor()
        if not isinstance(actor, PermissionActor) or (actor.subject_type, actor.subject_id, actor.tenant_id) != (
            principal.authorization_subject_type,
            principal.authorization_subject_id,
            principal.tenant_id,
        ):
            raise PermissionDeniedError(reason="processing_api_actor_invalid")
        credential = capture_knowledge_processing_reference(principal)
        audit_user_id = (
            identity.effective_user_id or identity.resource_owner_user_id
            if isinstance(identity, OpenApiPrincipal)
            else getattr(identity, "user_id", None)
        )
        if audit_user_id != (principal.effective_user_id or principal.resource_owner_user_id):
            raise PermissionDeniedError(reason="processing_api_audit_origin_invalid")
    else:
        if principal is not None or not isinstance(identity, UserPayload):
            raise PermissionDeniedError(reason="processing_web_origin_required")
        credential = _web_reference(identity._runtime_credential_reference, identity)
        actor = await resolve_permission_actor(identity)
        if (actor.subject_type, actor.subject_id, actor.tenant_id) != ("user", identity.user_id, identity.tenant_id):
            raise PermissionDeniedError(reason="processing_web_actor_invalid")
        if tenant != actor.tenant_id and not (actor.super_admin and get_admin_scope_tenant_id() == tenant):
            raise PermissionDeniedError(reason="processing_web_tenant_invalid")
        audit_user_id = identity.user_id
    if type(audit_user_id) is not int or audit_user_id <= 0:
        raise PermissionDeniedError(reason="processing_audit_origin_invalid")
    payload = {
        "schema_version": 1,
        "tenant_id": tenant,
        "actor_user_id": audit_user_id,
        "space_id": space_id,
        "required_action": required_action,
        "entry_kind": entry_kind,
        "actor": _actor_facts(actor),
        "credential_reference": credential,
    }
    if required_action == "move":
        try:
            processing_actor_subject(payload, tenant_id=tenant, actor_user_id=audit_user_id, source_space_id=space_id)
        except ValueError as error:
            raise PermissionDeniedError(reason="processing_actor_invalid") from error
    return FrozenProcessingActor(
        audit_user_id,
        tenant,
        space_id,
        required_action,
        entry_kind,
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
    )


@asynccontextmanager
async def restore_processing_actor(reference, *, tenant_id: int):
    try:
        if (
            not isinstance(reference, dict)
            or set(reference) != _ORIGIN_FIELDS
            or type(tenant_id) is not int
            or tenant_id <= 0
            or type(reference["tenant_id"]) is not int
            or reference["tenant_id"] != tenant_id
            or type(reference["schema_version"]) is not int
            or reference["schema_version"] != 1
            or type(reference["actor_user_id"]) is not int
            or reference["actor_user_id"] <= 0
            or type(reference["space_id"]) is not int
            or reference["space_id"] <= 0
            or reference["required_action"] not in _ACTIONS
            or reference["entry_kind"] not in {"web", "open_api"}
            or not isinstance(reference["actor"], dict)
        ):
            raise ValueError("invalid processing origin")
        if reference["required_action"] == "move":
            processing_actor_subject(
                reference,
                tenant_id=tenant_id,
                actor_user_id=reference["actor_user_id"],
                source_space_id=reference["space_id"],
            )
        reference = deepcopy(reference)
        credential = reference["credential_reference"]
    except (KeyError, TypeError, ValueError) as error:
        raise PermissionDeniedError(reason="processing_origin_invalid") from error
    with tenant_execution_scope(tenant_id):
        if reference["entry_kind"] == "open_api":
            async with restore_knowledge_processing_reference(credential, tenant_id=tenant_id) as original:
                if reference["actor_user_id"] != (original.effective_user_id or original.resource_owner_user_id):
                    raise PermissionDeniedError(reason="processing_api_audit_origin_invalid")
                actor = _narrow_actor(get_current_permission_actor(), reference["actor"])
                token = set_current_permission_actor(actor)
                try:
                    yield original
                finally:
                    reset_current_permission_actor(token)
        else:
            credential = _web_reference(credential)
            if reference["actor_user_id"] != credential["user_id"]:
                raise PermissionDeniedError(reason="processing_web_audit_origin_invalid")
            with without_open_api_identity():
                token = set_current_permission_actor(None)
                try:
                    original = await resolve_web_runtime_identity(credential)
                    _web_reference(credential, original)
                    original._runtime_credential_reference = deepcopy(credential)
                    actor = _narrow_actor(await resolve_permission_actor(original), reference["actor"])
                    if tenant_id != actor.tenant_id and not actor.super_admin:
                        raise PermissionDeniedError(reason="processing_web_tenant_invalid")
                    narrowed = set_current_permission_actor(actor)
                    try:
                        with management_tenant_scope(tenant_id):
                            yield original
                    finally:
                        reset_current_permission_actor(narrowed)
                finally:
                    reset_current_permission_actor(token)
