"""Current use recipients, only after approval's existing read qualification."""

import asyncio
from time import monotonic

from loguru import logger

from bisheng.app_publish.domain.repositories.preview_runtime_repository import PreviewRuntimeRepository
from bisheng.app_publish.domain.schemas.current_visibility import visibility_state
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError
from bisheng.common.errcode.permission import PermissionPublishNotReadyError, PermissionSubjectUnavailableError
from bisheng.core.context.tenant import management_tenant_scope, strict_tenant_filter, tenant_execution_scope
from bisheng.permission.application import is_tenant_admin
from bisheng.permission.application.access import (
    get_f048_resource_adapter,
    get_f048_runtime,
    get_grant_subject_directory,
)
from bisheng.permission.application.identity import PermissionActor
from bisheng.user.application.runtime_identity import read_current_person_facts

read_application = PreviewRuntimeRepository.read_application


async def _person_actor(person):
    """Resolve this exact person, never the current request's cached actor."""
    global_super = bool(getattr(person, "is_global_super", False))
    tenant_admin = not global_super and await is_tenant_admin(person.user_id, person.tenant_id)
    return PermissionActor(
        subject_type="user",
        subject_id=person.user_id,
        tenant_id=person.tenant_id,
        super_admin=global_super,
        tenant_admin_tenant_ids=frozenset({person.tenant_id}) if tenant_admin else frozenset(),
    )


class AppPublishCurrentVisibilityService:
    @classmethod
    async def read(cls, context, viewer):
        if (
            context.viewer_user_id != viewer.user_id
            or not context.app_id
            or (context.payload_app_id is not None and context.payload_app_id != context.app_id)
            or (
                viewer.tenant_id != context.tenant_id
                and not (context.management and getattr(viewer, "is_global_super", False))
            )
        ):
            raise ApprovalRequestPermissionDeniedError()
        start = monotonic()
        try:
            app = await asyncio.wait_for(read_application(context.app_id), timeout=5)
        except Exception:
            # Current decoration is noncritical; report the gap, preserve the frozen card.
            logger.exception("app_publish.current_visibility read failed instance={}", context.instance_id)
            return visibility_state("unavailable", reason="application_unavailable")
        if app is None:
            return visibility_state("deleted", reason="application_deleted")
        if app.id != context.app_id or app.tenant_id != context.tenant_id:
            raise ApprovalRequestPermissionDeniedError()
        if app.state == "deleted":
            return visibility_state("deleted", reason="application_deleted")
        scope = management_tenant_scope if context.management else tenant_execution_scope
        try:
            with scope(context.tenant_id), strict_tenant_filter():
                return await asyncio.wait_for(cls._assemble(app, viewer), timeout=max(0.001, 5 - (monotonic() - start)))
        except Exception:
            # Never turn an incomplete optional read into an owner-only assertion.
            logger.exception(
                "app_publish.current_visibility unavailable instance={} app={}", context.instance_id, app.id
            )
            return visibility_state("unavailable", reason="authorization_unavailable")

    @staticmethod
    async def _assemble(app, viewer):
        runtime = await get_f048_runtime()
        adapter = await get_f048_resource_adapter("app")
        target = await adapter.resolve_permission_target(
            resource_id=app.id, actor=await _person_actor(viewer), action="use"
        )
        sources = await runtime.read_effective_action_sources(target=target, action="use")
        directory = await get_grant_subject_directory()
        subjects = await directory.describe_active_sources(tenant_id=app.tenant_id, sources=sources)
        facts = (await read_current_person_facts([app.owner_user_id])).get(app.owner_user_id)
        if facts is None or facts["state"] == "ambiguous":
            raise PermissionSubjectUnavailableError(reason="owner_unresolved")
        eligible = False
        if facts["state"] == "active" and facts["tenant_id"] == app.tenant_id:
            if not facts["name"]:
                raise PermissionSubjectUnavailableError(reason="owner_name_unresolved")
            owner = await UserPayload.init_login_user(
                user_id=app.owner_user_id,
                user_name=facts["name"],
                tenant_id=facts["tenant_id"],
                token_version=facts["token_version"],
            )
            eligible = await runtime.check_action(await _person_actor(owner), target, "use")
        owner_id = str(app.owner_user_id)
        subjects = [row for row in subjects if not (row["type"] == "user" and row["id"] == owner_id)]
        owner_only = bool(eligible and not subjects)
        if eligible:
            subjects.insert(0, {"type": "user", "id": owner_id, "name": facts["name"]})
        # Names/identity checks can cross a concurrent Grant edit. Recheck via
        # the public permission port, not its private repository or state.
        if sources != await runtime.read_effective_action_sources(target=target, action="use"):
            raise PermissionPublishNotReadyError(reason="summary_scope_changed")
        return visibility_state(
            "available",
            owner_only=owner_only,
            owner={"id": owner_id, "name": facts["name"], "eligible": bool(eligible)},
            subjects=subjects,
        )
