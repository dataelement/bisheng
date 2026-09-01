"""Apply an approved resource-user invite as an ordinary F048 Grant.

The approval flow (F033) confirms *that* a user may be granted access; turning
that decision into permission state is the resource owner's job, and this is
the owner adapter Permission calls back into.

COFCO's original executors sat on ``ResourceAuthorizationService`` and its
binding-mutation transaction, both of which F048 removed. The replacement goes
through the same ADD-only server-side path a freshly created resource uses
(:class:`InitialGrantApplication`), so an approved invite lands as a normal
Grant with a canonical source and takes part in the same projection and
read-after-write guarantees as any other grant.

``execute`` and ``verify`` are separate on purpose: the Celery task runs them
in sequence and only marks the request applied when the authoritative read
back confirms the grant, so a partial write is retried rather than reported as
success.
"""

from __future__ import annotations

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.domain.ports.resource_grant_executor import (
    ResourceGrantCommand,
    ResourceGrantVerificationResult,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor


class F048ResourceGrantExecutor:
    """Resource-owner adapter for confirmed user grants on one resource type."""

    def __init__(self, resource_type: str) -> None:
        self.resource_type = resource_type

    async def execute(self, command: ResourceGrantCommand) -> None:
        self._validate(command)
        actor, target, context = await self._context(command)
        if self._granted(context.grants, command):
            # The task retries after a partial failure; a grant that is already
            # present must not be re-added (it would consume a second source).
            return

        from bisheng.permission.application.access import get_f048_runtime
        from bisheng.permission.application.initial_grant import (
            InitialGrantAddition,
            InitialGrantApplication,
            InitialGrantRequest,
        )
        from bisheng.tenant.domain.services.f048_permission_subject import (
            TenantPermissionSubjectDirectory,
        )

        application = InitialGrantApplication(
            runtime=await get_f048_runtime(),
            subjects=TenantPermissionSubjectDirectory(),
        )
        await application.apply(
            actor=actor,
            target=target,
            request=InitialGrantRequest(
                # The request fingerprint is stable across retries of the same
                # approved invite, which is what makes the mutation idempotent.
                command_key=f"resource-user-invite:{command.request_fingerprint}",
                expected_catalog_release_id=context.current_catalog_release_id,
                additions=(
                    InitialGrantAddition(
                        model_key=self._model_key(command),
                        subject_type="user",
                        subject_id=str(command.target_user_id),
                        include_children=bool(command.include_children),
                    ),
                ),
            ),
        )

    async def verify(self, command: ResourceGrantCommand) -> ResourceGrantVerificationResult:
        self._validate(command)
        _actor, _target, context = await self._context(command)
        applied = self._granted(context.grants, command)
        return ResourceGrantVerificationResult(
            applied=applied,
            result_snapshot={
                "resource_type": command.resource_type,
                "resource_id": command.resource_id,
                "target_user_id": command.target_user_id,
                "model_key": self._model_key(command),
                "applied": applied,
            },
        )

    async def _context(self, command: ResourceGrantCommand):
        """Resolve the invite's resource and read its current grants.

        The inviter is the actor: an invite approved after the inviter lost
        ``manage_permission`` must fail loudly rather than grant on the
        authority of whoever happens to run the worker.
        """
        from bisheng.permission.application.access import (
            get_f048_resource_registry,
            get_f048_runtime,
        )

        actor = PermissionActor(
            user_id=int(command.inviter_user_id),
            current_tenant_id=int(command.tenant_id),
        )
        registry = await get_f048_resource_registry()
        target = await registry.resolve(
            resource_type=command.resource_type,
            resource_id=command.resource_id,
            actor=actor,
            action="manage_permission",
        )
        runtime = await get_f048_runtime()
        context = await runtime.build_grant_context(actor=actor, target=target)
        return actor, target, context

    @staticmethod
    def _model_key(command: ResourceGrantCommand) -> str:
        """The permission model the invite grants; ``relation`` is the fallback
        for commands minted before the model id was carried."""
        return str(command.model_id or command.relation)

    def _granted(self, grants, command: ResourceGrantCommand) -> bool:
        model_key = self._model_key(command)
        subject_id = str(command.target_user_id)
        for grant in grants:
            if grant.model.model_key != model_key or not grant.active:
                continue
            for source in grant.sources:
                if source.active and source.subject_type == "user" and source.subject_id == subject_id:
                    return True
        return False

    def _validate(self, command: ResourceGrantCommand) -> None:
        if command.resource_type != self.resource_type:
            raise PermissionInvalidResourceError()


__all__ = ["F048ResourceGrantExecutor"]
