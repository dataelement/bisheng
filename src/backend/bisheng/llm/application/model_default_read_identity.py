"""Private ambient identity for tenant defaults; it grants no resource action."""

from dataclasses import dataclass, field
from weakref import WeakKeyDictionary, ref

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.tenant import NoTenantContextError
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
from bisheng.permission.application.identity import PermissionActor, get_current_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.source_contracts import (
    ReadIdentityFacts,
    canonical_payload_json,
    payload_digest,
)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class ModelDefaultReadIdentity:
    login_user: UserPayload | None = field(repr=False)
    _nonce: object = field(default_factory=object, repr=False)


@dataclass(frozen=True, slots=True)
class _IssuedIdentity:
    original: object
    login_user: object
    nonce: object
    facts: ReadIdentityFacts
    open_principal: object
    public_principal: object


def _invalid():
    return ResourceReferenceInvalidError(reason="model_default_read_identity_required")


class ModelDefaultReadIdentityPort:
    def __init__(self):
        self._issued = WeakKeyDictionary()

    @staticmethod
    def _facts(login_user):
        try:
            tenant = _resolve_tenant_id()
        except NoTenantContextError as error:
            raise _invalid() from error
        if (
            type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or (login_user is not None and not isinstance(login_user, UserPayload))
        ):
            raise _invalid()
        principal, public = get_current_open_api_principal(), get_current_public_api_principal()
        if principal is not None and public is not None:
            raise _invalid()
        if any(value is not None and value.tenant_id != tenant for value in (principal, public)):
            raise _invalid()
        actor = get_current_permission_actor()
        if actor is not None and not isinstance(actor, PermissionActor):
            raise _invalid()
        visible = get_visible_tenant_ids()
        try:
            value = {
                "tenant": tenant,
                "visible": sorted(visible) if visible is not None else None,
                "management": get_is_management_api(),
                "management_pin": get_admin_scope_tenant_id(),
                "all_tenants": is_management_all_tenants(),
                "trace": trace_id_var.get(),
                "open_api": principal.model_dump(mode="json") if principal is not None else None,
                "public_api": public.model_dump(mode="json") if public is not None else None,
                "actor": None
                if actor is None
                else {
                    "subject_type": actor.subject_type,
                    "subject_id": actor.subject_id,
                    "tenant": actor.current_tenant_id,
                    "super": actor.super_admin,
                    "admins": sorted(actor.tenant_admin_tenant_ids),
                    "data_scope": actor.data_scope,
                },
                "user": None
                if login_user is None
                else {
                    "id": login_user.user_id,
                    "tenant": login_user.tenant_id,
                    "roles": sorted(login_user.user_role),
                    "super": login_user.is_global_super,
                    "token_version": login_user.token_version,
                    "credential_reference": login_user._runtime_credential_reference,
                },
            }
            facts = ReadIdentityFacts(tenant, payload_digest(canonical_payload_json(value)))
        except (TypeError, ValueError, AttributeError) as error:
            raise _invalid() from error
        return facts, principal, public

    def issue_identity(self, login_user: UserPayload | None = None):
        facts, principal, public = self._facts(login_user)
        identity = ModelDefaultReadIdentity(login_user)
        self._issued[identity] = _IssuedIdentity(ref(identity), login_user, identity._nonce, facts, principal, public)
        return identity

    def capture(self, identity):
        issued = self._issued.get(identity) if isinstance(identity, ModelDefaultReadIdentity) else None
        if (
            issued is None
            or issued.original() is not identity
            or issued.nonce is not identity._nonce
            or issued.login_user is not identity.login_user
        ):
            raise _invalid()
        facts, principal, public = self._facts(identity.login_user)
        if facts != issued.facts or principal is not issued.open_principal or public is not issued.public_principal:
            raise _invalid()
        return facts

    async def acapture(self, identity):
        return self.capture(identity)
