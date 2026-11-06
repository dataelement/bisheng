"""Capture the authenticated APP principal without manufacturing a person."""

from dataclasses import asdict, is_dataclass

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_is_management_api,
    get_visible_tenant_ids,
    is_management_all_tenants,
    is_tenant_filter_bypassed,
)
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.core.logger import trace_id_var
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.permission.application.identity import PermissionActor, get_current_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_contracts import (
    ReadIdentityFacts,
    canonical_payload_json,
    payload_digest,
)


class AppSourceReadIdentity:
    async def acapture(self, identity):
        actor = get_current_permission_actor()
        tenant_id = _resolve_tenant_id()
        if (
            not isinstance(identity, OpenApiPrincipal)
            or get_current_open_api_principal() is not identity
            or identity.actor_kind != "hosted_app"
            or identity.mode != "S"
            or identity.tenant_id != tenant_id
            or identity.credential_id <= 0
            or identity.actor_id <= 0
            or not identity.subject_ref
            or is_tenant_filter_bypassed()
            or get_current_public_api_principal() is not None
            or not isinstance(actor, PermissionActor)
            or actor.current_tenant_id != tenant_id
            or (actor.subject_type, actor.subject_id, actor.tenant_id)
            != (identity.authorization_subject_type, identity.authorization_subject_id, identity.tenant_id)
        ):
            raise ResourceReferenceInvalidError(reason="app_reference_identity_invalid")
        visible = get_visible_tenant_ids()
        payload = {
            "principal": identity.model_dump(mode="json"),
            "actor": {
                "subject_type": actor.subject_type,
                "subject_id": actor.subject_id,
                "tenant_id": actor.tenant_id,
                "current_tenant_id": actor.current_tenant_id,
                "super_admin": actor.super_admin,
                "tenant_admin_ids": sorted(actor.tenant_admin_tenant_ids),
                "data_scope": actor.data_scope,
            },
            "tenant_id": tenant_id,
            "visible": sorted(visible) if visible is not None else None,
            "management": get_is_management_api(),
            "management_scope": get_admin_scope_tenant_id(),
            "all_tenants": is_management_all_tenants(),
            "trace": trace_id_var.get(),
        }
        return ReadIdentityFacts(tenant_id, payload_digest(canonical_payload_json(payload)))


class AppManagementSourceReadIdentity:
    def __init__(self, authorization_context=None):
        self.authorization_context = authorization_context

    async def acapture(self, identity):
        context = self.authorization_context
        serialized = asdict(context) if is_dataclass(context) else context
        if isinstance(identity, UserPayload):
            original = await AuthenticatedSourceReadIdentity().acapture(identity)
            return ReadIdentityFacts(
                original.request_tenant_id,
                (original.fingerprint, canonical_payload_json({"authorization_context": serialized})),
            )
        actor = get_current_permission_actor()
        tenant_id = _resolve_tenant_id()
        reference = context.get("credential_ref", {}) if isinstance(context, dict) else {}
        if (
            not isinstance(identity, OpenApiPrincipal)
            or get_current_open_api_principal() is not identity
            or identity.actor_kind not in {"service_account", "natural_person"}
            or identity.mode != "S"
            or not identity.has_scope("app:manage")
            or identity.tenant_id != tenant_id
            or is_tenant_filter_bypassed()
            or get_current_public_api_principal() is not None
            or not isinstance(actor, PermissionActor)
            or actor.current_tenant_id != tenant_id
            or (actor.subject_type, actor.subject_id, actor.tenant_id)
            != (identity.authorization_subject_type, identity.authorization_subject_id, identity.tenant_id)
            or not isinstance(context, dict)
            or context.get("schema") != 1
            or context.get("origin_kind") != "user_request"
            or context.get("mode") != identity.mode
            or reference != {"kind": "api_credential", "credential_id": identity.credential_id, "tenant_id": tenant_id}
            or context.get("actor")
            != {"subject_type": actor.subject_type, "subject_id": actor.subject_id, "tenant_id": actor.tenant_id}
        ):
            raise ResourceReferenceInvalidError(reason="app_management_identity_invalid")
        visible = get_visible_tenant_ids()
        facts = {
            "principal": identity.model_dump(mode="json"),
            "authorization_context": serialized,
            "actor": {
                "subject_type": actor.subject_type,
                "subject_id": actor.subject_id,
                "tenant_id": actor.tenant_id,
                "current_tenant_id": actor.current_tenant_id,
                "super_admin": actor.super_admin,
                "tenant_admin_ids": sorted(actor.tenant_admin_tenant_ids),
                "data_scope": actor.data_scope,
            },
            "tenant_id": tenant_id,
            "visible": sorted(visible) if visible is not None else None,
            "management": get_is_management_api(),
            "management_scope": get_admin_scope_tenant_id(),
            "all_tenants": is_management_all_tenants(),
            "trace": trace_id_var.get(),
        }
        return ReadIdentityFacts(tenant_id, payload_digest(canonical_payload_json(facts)))
