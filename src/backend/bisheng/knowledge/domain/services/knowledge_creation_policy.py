"""Web-only creation qualification; copy and open APIs retain their contracts."""

from copy import deepcopy
from dataclasses import dataclass

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeCreationScopeChangedError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.database.models.role_access import WebMenuResource
from bisheng.permission.application import is_tenant_admin
from bisheng.user.application.runtime_identity import resolve_web_creation_identity


@dataclass(frozen=True, slots=True)
class KnowledgeCreationContext:
    user_id: int
    tenant_id: int
    credential_reference: dict


class KnowledgeCreationPolicy:
    @classmethod
    async def prepare(cls, login_user, *, expected_tenant_id: int | None = None):
        tenant_id = login_user.tenant_id
        if expected_tenant_id is not None and expected_tenant_id != tenant_id:
            raise KnowledgeCreationScopeChangedError()
        context = KnowledgeCreationContext(
            user_id=login_user.user_id,
            tenant_id=tenant_id,
            credential_reference=deepcopy(login_user._runtime_credential_reference),
        )
        await cls.revalidate(context)
        return context

    @staticmethod
    async def revalidate(context):
        try:
            person = await resolve_web_creation_identity(context.credential_reference)
        except PermissionDeniedError as exc:
            if exc.kwargs.get("reason") == "web_creation_tenant_changed":
                raise KnowledgeCreationScopeChangedError() from exc
            raise
        if person.user_id != context.user_id or person.tenant_id != context.tenant_id:
            raise KnowledgeCreationScopeChangedError()
        if not person.is_global_super and not await is_tenant_admin(person.user_id, person.tenant_id):
            await UserPayload.assert_effective_web_menu_contains(person.user_id, WebMenuResource.CREATE_KNOWLEDGE.value)
        return person
