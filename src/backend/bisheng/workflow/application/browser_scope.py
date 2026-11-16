"""Bind authenticated workflow connections to one verified resource tenant."""

from contextlib import asynccontextmanager, nullcontext

from bisheng.admin.application.tenant_scope import resolve_management_scope
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import management_tenant_scope, tenant_execution_scope
from bisheng.database.models.flow import FlowType, assert_workflow_ready
from bisheng.workflow.domain.repositories.creation_repository import CreationRepository


@asynccontextmanager
async def browser_workflow_scope(identity, workflow_id: str, *, admitted=None):
    credential_tenant = getattr(identity, "_dsh_web_session_tenant_id", None)
    if admitted is not None:
        from bisheng.core.context.tenant import get_current_tenant_id

        if admitted.user_id != identity.user_id or admitted.tenant_id != get_current_tenant_id():
            raise UnAuthorizedError()
        actor = identity
        target = admitted.tenant_id
        view = (
            management_tenant_scope(target) if admitted.is_super and admitted.source != "credential" else nullcontext()
        )
    elif credential_tenant is not None:
        actor = identity
        target = credential_tenant
        view = nullcontext()
    else:
        actor = await UserPayload.init_login_user(
            user_id=identity.user_id,
            user_name=identity.user_name,
            tenant_id=identity.tenant_id,
            token_version=identity.token_version,
            require_current_super=True,
        )
        scope = await resolve_management_scope(actor.user_id, is_super=actor.is_global_super, for_write=True)
        target = scope.tenant_id
        view = management_tenant_scope(target)
    with tenant_execution_scope(target), view:
        # F048 deliberately short-circuits super administrators. The business
        # must establish the concrete target before invoking that action gate.
        resource = await CreationRepository.load(target, workflow_id)
        if resource is None or resource.flow_type != FlowType.WORKFLOW.value:
            raise UnAuthorizedError()
        assert_workflow_ready(resource)
        yield actor
