"""Bounded self-removal policy over canonical, local knowledge-space grants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bisheng.common.errcode.permission import PermissionDeniedError, PermissionPublishNotReadyError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import CanonicalGrantChange, GrantMutationContext
from bisheng.permission.domain.services.grant_source_service import is_visibility_only_model
from bisheng.permission.domain.services.permission_action_service import PermissionActor

_PERSONAL_SOURCE_TYPES = frozenset({"DIRECT", "SPACE_MEMBERSHIP", "SNAPSHOT_FROM_PARENT"})


@dataclass(frozen=True, slots=True)
class PersonalSpaceExitStatus:
    can_exit: bool
    reason: Literal["creator", "organization_grant", "no_personal_grant"] | None = None


@dataclass(frozen=True, slots=True)
class PersonalSpaceExitPlan:
    status: PersonalSpaceExitStatus
    changes: tuple[CanonicalGrantChange, ...] = ()
    execution_forbidden: bool = False


def require_personal_space_actor(actor: PermissionActor, target: VerifiedPermissionTarget) -> None:
    """Self-service never inherits administrator or service-account shortcuts."""

    if actor.subject_type != "user" or actor.tenant_id != target.tenant_id or target.resource_type != "knowledge_space":
        raise PermissionDeniedError()


def plan_personal_space_exit(
    *,
    actor: PermissionActor,
    context: GrantMutationContext,
    actor_projected_subjects: frozenset[str],
) -> PersonalSpaceExitPlan:
    """Choose only this user's removable sources; organization access is retained.

    The caller supplies freshly resolved directory usersets. Public-reader tuples
    are deliberately absent: being public does not create an organization grant.
    Disabled model choices retain the meaning of their existing active sources.
    """

    target = context.target
    require_personal_space_actor(actor, target)
    if context.mode != "CUSTOM":
        raise PermissionPublishNotReadyError(msg="Personal space exit requires a local CUSTOM permission scope")

    changes = []
    creator = organization = nonremovable = False
    for grant in context.grants:
        if (grant.tenant_id, grant.resource_type, grant.resource_id) != (
            target.tenant_id,
            target.resource_type,
            target.resource_id,
        ):
            raise PermissionPublishNotReadyError(msg="Personal space exit encountered a foreign grant scope")
        if not grant.active:
            continue
        for source in grant.sources:
            if not source.active:
                continue
            if source.subject_type != "user":
                if source.projected_subject in actor_projected_subjects:
                    organization = True
                continue
            if source.subject_id != str(actor.subject_id):
                continue
            if source.protected or source.source_type == "CREATOR":
                creator = True
                continue
            if (
                source.userset_relation is not None
                or source.projected_subject != actor.fga_subject
                or source.source_type not in _PERSONAL_SOURCE_TYPES
            ):
                nonremovable = True
                continue
            if grant.model.derived_level is None or (
                not grant.model.action_codes and not is_visibility_only_model(grant.model, target.resource_type)
            ):
                raise PermissionPublishNotReadyError(msg="Personal space exit cannot safely mutate the current model")
            changes.append(
                CanonicalGrantChange(
                    operation="REMOVE", assignee_id=source.source_id, expected_assignee_version=source.version
                )
            )

    if creator:
        return PersonalSpaceExitPlan(PersonalSpaceExitStatus(False, "creator"), execution_forbidden=True)
    if organization:
        return PersonalSpaceExitPlan(PersonalSpaceExitStatus(False, "organization_grant"), execution_forbidden=True)
    if nonremovable:
        return PersonalSpaceExitPlan(PersonalSpaceExitStatus(False, "no_personal_grant"), execution_forbidden=True)
    if len(changes) > 50:
        raise PermissionPublishNotReadyError(msg="Personal space exit exceeds the atomic 50-source mutation limit")
    if not changes:
        return PersonalSpaceExitPlan(PersonalSpaceExitStatus(False, "no_personal_grant"))
    return PersonalSpaceExitPlan(PersonalSpaceExitStatus(True), tuple(changes))
