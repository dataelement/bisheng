"""SG 式 Token 主体与业务用户分离的昆联上下文。"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal
from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.public_endpoints.domain.context import reset_current_public_api_principal, set_current_public_api_principal


@dataclass(frozen=True)
class KunlianRequestUser:
    credential: object
    user: object
    external_tenant_id: str
    external_user_id: str
    user_account: str | None = None


async def _privileges(user):
    from bisheng.permission.application.relation_api import is_tenant_admin

    # The identity Owner has just read current roles and global-super relation.
    # Do not consult the middleware's positive super-admin cache here.
    is_super = bool(getattr(user, "is_global_super", False))
    return is_super, False if is_super else await is_tenant_admin(user.user_id, user.tenant_id)


async def revalidate_kunlian_subject(subject, *, credentials=None, identities=None, app=None):
    """Recheck a persisted worker identity; never accepts caller-supplied HTTP identity."""
    from bisheng.open_api.domain.services.kunlian_credential import KunlianCredentialService
    from bisheng.sso_sync.application.kunlian_identity import get_kunlian_identity_application

    credentials = credentials or KunlianCredentialService()
    await credentials.validate_reference(
        subject.credential_id,
        integration_id=subject.connection_id,
        connection_id=subject.identity_connection_id,
        external_tenant_id=subject.external_tenant_id,
        capability="invoke",
    )
    if identities is None:
        identities = await get_kunlian_identity_application(app or SimpleNamespace(state=SimpleNamespace()))
    user = await identities.resolve(
        connection_id=subject.identity_connection_id,
        external_tenant_id=subject.external_tenant_id,
        external_user_id=subject.external_user_id,
    )
    if (user.tenant_id, user.user_id) != (subject.tenant_id, subject.user_id) or getattr(
        user, "is_global_super", False
    ):
        raise KunlianAccessError("FORBIDDEN")
    return user


class KunlianAccessService:
    def __init__(self, credentials, identities, *, privilege_reader=None, account_resolver=None):
        self.credentials = credentials
        self.identities = identities
        self.account_resolver = account_resolver
        self.privilege_reader = privilege_reader or _privileges

    @asynccontextmanager
    async def use_user(self, authorization, user_account, *, capability):
        if (
            not isinstance(user_account, str)
            or not user_account.strip()
            or user_account != user_account.strip()
            or len(user_account) > 128
        ):
            raise KunlianAccessError("INVALID_INPUT")
        caller = await self.credentials.authenticate_caller(authorization, capability=capability)
        accounts = self.account_resolver
        if accounts is None:
            from bisheng.user.application.kunlian_account import get_kunlian_account_application

            accounts = await get_kunlian_account_application(SimpleNamespace(state=SimpleNamespace()))
        elif not hasattr(accounts, "resolve_account"):
            accounts = await accounts()
        facts = await accounts.resolve_account(connection_id=caller.connection_id, user_account=user_account)
        credential = await self.credentials.validate_reference(
            caller.credential_id,
            integration_id=caller.integration_id,
            connection_id=caller.connection_id,
            external_tenant_id=facts.external_tenant_id,
            capability=capability,
        )
        external_tenant_id, external_user_id = facts.external_tenant_id, facts.external_user_id
        identities = self.identities if hasattr(self.identities, "resolve") else await self.identities()
        user = await identities.resolve(
            connection_id=credential.connection_id,
            external_tenant_id=external_tenant_id,
            external_user_id=external_user_id,
        )
        if (user.user_id, user.tenant_id) != (facts.user_id, facts.tenant_id):
            raise KunlianAccessError("FORBIDDEN")
        if type(user.tenant_id) is not int or user.tenant_id <= 0:
            raise KunlianAccessError("FORBIDDEN")
        tenant_scope = tenant_execution_scope(user.tenant_id)
        tenant_scope.__enter__()
        principal_token = set_current_open_api_principal(None)
        public_token = set_current_public_api_principal(None)
        actor_token = set_current_permission_actor(None)
        try:
            is_super, is_admin = await self.privilege_reader(user)
            if is_super:
                raise KunlianAccessError("FORBIDDEN")
            set_current_permission_actor(
                PermissionActor(
                    subject_type="user",
                    subject_id=user.user_id,
                    tenant_id=user.tenant_id,
                    super_admin=False,
                    tenant_admin_tenant_ids=frozenset({user.tenant_id}) if is_admin else frozenset(),
                )
            )
            yield KunlianRequestUser(credential, user, external_tenant_id, external_user_id, user_account)
        finally:
            reset_current_permission_actor(actor_token)
            reset_current_public_api_principal(public_token)
            reset_current_open_api_principal(principal_token)
            tenant_scope.__exit__(None, None, None)
