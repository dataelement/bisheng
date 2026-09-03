"""Route a personal grant to approval instead of applying it outright.

F033: granting a person access to a knowledge space or a channel is not the
grantor's decision alone. A grant aimed at somebody who does not already hold
an explicit permission on the resource becomes an invitation that goes to the
approval centre; only once it is approved does the worker write the grant
(see ``resource_grant_executors``).

Adjusting somebody who already holds a permission stays direct — the approval
was given when they were first let in, and re-approving every level change
would make routine maintenance unusable.

The gate deliberately sits at the single F048 mutation entry point rather than
in each business service: any caller that can grant must pass through it, so
the approval requirement cannot be bypassed by reaching a different endpoint.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor

#: Resources whose personal grants are gated. A channel is always gated; a
#: knowledge space only for people who are not on it yet.
GATED_RESOURCE_TYPES = frozenset({"knowledge_space", "channel"})
_ALWAYS_GATED = frozenset({"channel"})


@dataclass(frozen=True, slots=True)
class PendingInvite:
    """One change the gate diverted to approval."""

    subject_id: str
    model_key: str
    outcome: str
    request_id: int
    approval_instance_id: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": {"type": "user", "id": self.subject_id},
            "model_key": self.model_key,
            # ``invite_created`` for a new request, ``invite_existing`` when one
            # was already pending for this person — the caller shows a different
            # message for each.
            "outcome": self.outcome,
            "request_id": self.request_id,
            "approval_instance_id": self.approval_instance_id,
        }


def role_snapshot_of(model: GrantModelSnapshot) -> dict[str, Any]:
    """The permission model as recorded on the invite.

    Captured at invite time and re-checked at execution: if the model's actions
    changed while the request sat in approval, what the approver agreed to is
    no longer what would be granted, and the invite must be raised again.
    """
    return {
        "id": model.model_key,
        "model_key": model.model_key,
        "action_codes": sorted(model.action_codes),
        "derived_level": model.derived_level,
        "allow_same_level": bool(model.allow_same_level),
    }


class PersonalGrantInviteGate:
    """Split ADD changes into what may be applied and what needs approval."""

    def __init__(self, *, invite_service_factory=None) -> None:
        self._invite_service_factory = invite_service_factory

    def _invite_service(self):
        if self._invite_service_factory is not None:
            return self._invite_service_factory()
        from bisheng.permission.domain.services.resource_user_invite_application_service import (
            build_runtime_resource_user_invite_application_service,
        )

        return build_runtime_resource_user_invite_application_service()

    @asynccontextmanager
    async def scenario_guard(self, *, tenant_id: int):
        """Hold the invite scenario open for the duration of one mutation.

        The guard row-locks the scenario, so an operator disabling confirmation
        halfway through cannot leave the caller having raised some invites and
        applied the rest directly. It raises ``ApprovalScenarioDisabledError``
        when confirmation is already off, which is the caller's cue to degrade.
        A service without a guard (older fakes in tests) is treated as enabled.
        """
        guard_factory = getattr(self._invite_service(), "scenario_guard", None)
        if guard_factory is None:
            yield
            return
        async with guard_factory(tenant_id=int(tenant_id)):
            yield

    @staticmethod
    def _already_granted_user_ids(grants: tuple[GrantSnapshot, ...]) -> set[str]:
        granted: set[str] = set()
        for grant in grants:
            if not grant.active:
                continue
            for source in grant.sources:
                if source.active and source.subject_type == "user":
                    granted.add(str(source.subject_id))
        return granted

    def select(
        self,
        *,
        target: VerifiedPermissionTarget,
        actor: PermissionActor,
        changes,
        grants: tuple[GrantSnapshot, ...],
    ) -> tuple[list, list]:
        """Return ``(direct, gated)`` from the requested changes."""
        if target.resource_type not in GATED_RESOURCE_TYPES:
            return list(changes), []
        always = target.resource_type in _ALWAYS_GATED
        granted = self._already_granted_user_ids(grants)
        direct: list = []
        gated: list = []
        for change in changes:
            subject = getattr(change, "subject", None)
            is_new_person = (
                getattr(change, "op", None) is not None
                and change.op.value == "ADD"
                and subject is not None
                and subject.type == "user"
                and (always or str(subject.id) not in granted)
            )
            if not is_new_person:
                direct.append(change)
                continue
            if str(subject.id) == str(actor.user_id):
                raise PermissionDeniedError(msg="不能修改自己的权限")
            gated.append(change)
        return direct, gated

    async def raise_invites(
        self,
        *,
        target: VerifiedPermissionTarget,
        actor: PermissionActor,
        changes,
        models: tuple[GrantModelSnapshot, ...],
    ) -> list[PendingInvite]:
        if not changes:
            return []
        by_key = {model.model_key: model for model in models}
        resource_name, inviter_name, applicant_department_id = await self._invite_context(
            target=target,
            inviter_user_id=int(actor.user_id),
        )
        service = self._invite_service()
        pending: list[PendingInvite] = []
        for change in changes:
            model = by_key.get(change.model_key)
            if model is None or not model.active:
                raise PermissionDeniedError(msg="授权角色不存在")
            target_user_id = int(change.subject.id)
            result = await service.request_invite(
                tenant_id=int(target.tenant_id),
                resource_type=target.resource_type,
                resource_id=str(target.resource_id),
                resource_name=resource_name,
                inviter_user_id=int(actor.user_id),
                inviter_user_name=inviter_name,
                target_user_id=target_user_id,
                target_user_name=await self._user_name(target_user_id),
                relation=change.model_key,
                model_id=change.model_key,
                role_snapshot=role_snapshot_of(model),
                include_children=bool(getattr(change.subject, "include_children", False)),
                applicant_department_id=applicant_department_id,
            )
            pending.append(
                PendingInvite(
                    subject_id=str(target_user_id),
                    model_key=change.model_key,
                    outcome=str(result.get("outcome") or "invite_created"),
                    request_id=int(result["request_id"]),
                    approval_instance_id=result.get("approval_instance_id"),
                )
            )
        return pending

    async def _invite_context(
        self,
        *,
        target: VerifiedPermissionTarget,
        inviter_user_id: int,
    ) -> tuple[str, str, int | None]:
        from bisheng.database.models.department import UserDepartmentDao

        resource_name = await self._resource_name(target)
        primary_department = await UserDepartmentDao.aget_user_primary_department(inviter_user_id)
        return (
            resource_name,
            await self._user_name(inviter_user_id),
            getattr(primary_department, "department_id", None),
        )

    @staticmethod
    async def _resource_name(target: VerifiedPermissionTarget) -> str:
        if target.resource_type == "knowledge_space":
            from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

            space = await KnowledgeDao.aquery_by_id(int(target.resource_id))
            return getattr(space, "name", None) or str(target.resource_id)
        if target.resource_type == "channel":
            from bisheng.channel.domain.models.channel import Channel
            from bisheng.core.database import get_async_db_session

            async with get_async_db_session() as session:
                channel = await session.get(Channel, target.resource_id)
            return getattr(channel, "name", None) or str(target.resource_id)
        return str(target.resource_id)

    @staticmethod
    async def _user_name(user_id: int) -> str:
        from bisheng.user.domain.models.user import UserDao

        user = await UserDao.aget_user(int(user_id))
        return getattr(user, "user_name", None) or str(user_id)


def pending_invites_payload(pending: list[PendingInvite]) -> list[Mapping[str, Any]]:
    return [item.as_dict() for item in pending]


__all__ = [
    "GATED_RESOURCE_TYPES",
    "PendingInvite",
    "PersonalGrantInviteGate",
    "pending_invites_payload",
    "role_snapshot_of",
]
