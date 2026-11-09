"""Bind a read capability to the original authenticated request identity.

This adapter captures identity facts; it does not grant resource access. The
registered SourceOwner still authorizes the exact real business configuration.
"""

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
from bisheng.permission.application.identity import PermissionActor, resolve_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.source_contracts import (
    ReadIdentityFacts,
    canonical_payload_json,
    payload_digest,
)


class AuthenticatedSourceReadIdentity:
    async def acapture(self, identity: object) -> ReadIdentityFacts:
        return await self._capture(identity, stable=False)

    async def astable_capture(self, identity: object) -> ReadIdentityFacts:
        """Pagination context excludes only trace and binds the management pin.

        This fingerprint is a stale-page check, never an authorization grant.
        Every continuation still captures and authorizes the current request.
        """
        return await self._capture(identity, stable=True)

    async def _capture(self, identity: object, *, stable: bool) -> ReadIdentityFacts:
        if not isinstance(identity, UserPayload) or is_tenant_filter_bypassed():
            raise ResourceReferenceInvalidError(reason="reference_read_identity_required")
        tenant_id = _resolve_tenant_id()
        if type(tenant_id) is not int or tenant_id <= 0:
            raise ResourceReferenceInvalidError(reason="reference_read_tenant_required")
        actor = await resolve_permission_actor(identity)
        if not isinstance(actor, PermissionActor):
            raise ResourceReferenceInvalidError(reason="reference_read_actor_required")
        principal = get_current_open_api_principal()
        public = get_current_public_api_principal()
        if principal is not None and public is not None:
            raise ResourceReferenceInvalidError(reason="reference_read_identity_context_mixed")
        visible = get_visible_tenant_ids()
        try:
            facts = {
                "identity": {
                    "user_id": identity.user_id,
                    "tenant_id": identity.tenant_id,
                    "super_admin": identity.is_global_super,
                    "roles": sorted(identity.user_role),
                    "token_version": identity.token_version,
                    "credential_reference": identity._runtime_credential_reference,
                },
                "actor": {
                    "subject_type": actor.subject_type,
                    "subject_id": actor.subject_id,
                    "tenant_id": actor.current_tenant_id,
                    "super_admin": actor.super_admin,
                    "tenant_admin_ids": sorted(actor.tenant_admin_tenant_ids),
                    "data_scope": actor.data_scope,
                },
                "open_api": principal.model_dump(mode="json") if principal is not None else None,
                "public_api": public.model_dump(mode="json") if public is not None else None,
                "request_tenant_id": tenant_id,
                "visible_tenant_ids": sorted(visible) if visible is not None else None,
                "management_all_tenants": is_management_all_tenants(),
                "trace_id": trace_id_var.get(),
            }
            if stable:
                facts.pop("trace_id")
                facts["management_api"] = get_is_management_api()
                # A same-tenant worker restoration sets an explicit pin where
                # the originating ordinary request used its concrete tenant.
                # Those represent the same scope; a different pin stays distinct.
                pin = get_admin_scope_tenant_id()
                facts["management_pin"] = tenant_id if pin is None else pin
            fingerprint = payload_digest(canonical_payload_json(facts))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ResourceReferenceInvalidError(reason="reference_read_identity_context_invalid") from exc
        return ReadIdentityFacts(tenant_id, fingerprint)
