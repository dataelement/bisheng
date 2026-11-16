"""Formal Kunlian permission assembly using current F048 and durable receipts."""

from dataclasses import dataclass

from bisheng.open_api.domain.services.kunlian_credential import KunlianCredentialService
from bisheng.permission.application.identity import PermissionActor
from bisheng.workflow.application.kunlian_workflow_authorization import (
    AuthorizationError,
    AuthorizationSubject,
    WorkflowAuthorizationService,
)
from bisheng.workflow.domain.repositories.kunlian_grant_receipt import KunlianGrantReceiptRepository


@dataclass(frozen=True)
class KunlianAuthorizationSubject(AuthorizationSubject):
    identity_connection_id: str
    external_tenant_id: str
    external_user_id: str
    credential_id: int


async def _actor(user):
    from bisheng.permission.application.relation_api import is_tenant_admin

    if getattr(user, "is_global_super", False):
        raise AuthorizationError("NOT_FOUND")
    admin = await is_tenant_admin(user.user_id, user.tenant_id)
    return PermissionActor(
        subject_type="user",
        subject_id=user.user_id,
        tenant_id=user.tenant_id,
        super_admin=False,
        tenant_admin_tenant_ids=frozenset({user.tenant_id}) if admin else frozenset(),
    )


class KunlianPermissionApi(WorkflowAuthorizationService):
    def __init__(
        self, *, permissions, targets, decisions, identities, receipts=None, actor_reader=None, credentials=None
    ):
        self.identities = identities
        self.actor_reader = actor_reader or _actor
        self.credentials = credentials
        super().__init__(
            permissions=permissions,
            targets=targets,
            decisions=decisions,
            verify_subject=self._verify,
            resolve_member=self._member,
            receipts=receipts if receipts is not None else KunlianGrantReceiptRepository(),
            allowed_models=(),
        )

    async def subject(self, request_user):
        credential = request_user.credential
        user = await self.identities.resolve(
            connection_id=credential.connection_id,
            external_tenant_id=request_user.external_tenant_id,
            external_user_id=request_user.external_user_id,
        )
        if (user.tenant_id, user.user_id) != (request_user.user.tenant_id, request_user.user.user_id):
            raise AuthorizationError("NOT_FOUND")
        actor = await self.actor_reader(user)
        if actor.super_admin:
            raise AuthorizationError("NOT_FOUND")
        return KunlianAuthorizationSubject(
            credential.integration_id,
            user.tenant_id,
            user.user_id,
            actor,
            credential.connection_id,
            request_user.external_tenant_id,
            request_user.external_user_id,
            credential.credential_id,
        )

    async def _verify(self, subject, _workflow_id, action):
        if not isinstance(subject, KunlianAuthorizationSubject):
            return False
        if self.credentials is not None:
            await self.credentials.validate_reference(
                subject.credential_id,
                integration_id=subject.connection_id,
                connection_id=subject.identity_connection_id,
                external_tenant_id=subject.external_tenant_id,
                capability="grant" if action == "manage_permission" else "read",
            )
        user = await self.identities.resolve(
            connection_id=subject.identity_connection_id,
            external_tenant_id=subject.external_tenant_id,
            external_user_id=subject.external_user_id,
        )
        return (user.tenant_id, user.user_id) == (subject.tenant_id, subject.user_id) and not getattr(
            user, "is_global_super", False
        )

    async def _member(self, subject, external_user_id):
        user = await self.identities.resolve(
            connection_id=subject.identity_connection_id,
            external_tenant_id=subject.external_tenant_id,
            external_user_id=external_user_id,
        )
        if getattr(user, "is_global_super", False):
            return None
        return user.tenant_id, user.user_id

    async def _grantable(self, arguments):
        return [
            {"key": row["key"]} for row in await self.permissions.get_grantable_models(**arguments) if row["active"]
        ]

    async def _subject(self, subject):
        return subject if isinstance(subject, KunlianAuthorizationSubject) else await self.subject(subject)

    async def list_grants(self, subject, workflow_id, *, cursor=None, limit=50):
        return await super().list_grants(await self._subject(subject), workflow_id, cursor=cursor, limit=limit)

    async def my_permissions(self, subject, workflow_id):
        return await super().my_permissions(await self._subject(subject), workflow_id)

    async def change(self, subject, workflow_id, change, client_key):
        return await super().change(await self._subject(subject), workflow_id, change, client_key)


async def get_kunlian_permission_api(app):
    from bisheng.permission.application.access import (
        get_f048_resource_registry,
        get_f048_runtime,
        get_grant_subject_directory,
    )
    from bisheng.permission.application.resource_api import F048ResourcePermissionApi
    from bisheng.sso_sync.application.kunlian_identity import get_kunlian_identity_application

    runtime = await get_f048_runtime()
    targets = await get_f048_resource_registry()
    permissions = F048ResourcePermissionApi(
        resources=targets, runtime=runtime, subjects=await get_grant_subject_directory()
    )

    class Decisions:
        async def check(self, *, resource_type, resource_id, actor, action):
            target = await targets.resolve(
                resource_type=resource_type, resource_id=resource_id, actor=actor, action=action
            )
            return await runtime.check_action(actor, target, action)

    return KunlianPermissionApi(
        permissions=permissions,
        targets=targets,
        decisions=Decisions(),
        identities=await get_kunlian_identity_application(app),
        credentials=KunlianCredentialService(),
    )
