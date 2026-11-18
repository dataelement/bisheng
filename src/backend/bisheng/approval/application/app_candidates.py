"""App-only dual exclusion and an independently proven single-administrator exception."""

from dataclasses import dataclass

from bisheng.approval.domain.repositories.app_candidate_repository import AppCandidateRepository
from bisheng.permission.application import PermissionObject, get_permission_relation_api


@dataclass(frozen=True, slots=True)
class QualifiedAppCandidates:
    user_ids: tuple[int, ...]
    self_approval: bool = False


@dataclass(frozen=True, slots=True)
class AppCandidatePolicy:
    tenant_id: int
    excluded_ids: frozenset[int]
    actual_admins: frozenset[int]
    global_ids: tuple[int, ...]
    configured_admins: tuple[int, ...]

    @property
    def exclusive_user_id(self) -> int | None:
        """A self-review exception is valid only when selected alone."""
        if len(self.actual_admins) == 1:
            candidate = next(iter(self.actual_admins))
            if candidate in self.excluded_ids:
                return candidate
        return None

    @property
    def search_excluded_ids(self) -> frozenset[int]:
        return self.excluded_ids - {self.exclusive_user_id}

    async def qualify(self, candidates) -> QualifiedAppCandidates:
        values = tuple(dict.fromkeys(int(uid) for uid in candidates if str(uid).isdigit() and int(uid) > 0))
        # Candidate and administrator liveness must come from the same SQL read,
        # so an administrator activated after policy construction blocks self-review.
        active = set(
            await AppCandidateRepository.eligible_ids(
                self.tenant_id, (*values, *self.configured_admins), global_ids=self.global_ids
            )
        )
        eligible = tuple(uid for uid in values if uid in active)
        actual_admins = set(self.configured_admins).intersection(active)
        result = tuple(uid for uid in eligible if uid not in self.excluded_ids)
        if not result and len(actual_admins) == 1 and set(eligible) == actual_admins:
            return QualifiedAppCandidates(tuple(actual_admins), True)
        return QualifiedAppCandidates(result)


async def administrator_ids(tenant_id):
    permissions = await get_permission_relation_api()
    values = await permissions.list_subject_ids(
        resource=PermissionObject("system", "global") if tenant_id == 1 else PermissionObject("tenant", str(tenant_id)),
        relation="super_admin" if tenant_id == 1 else "admin",
        subject_type="user",
    )
    result = {int(value) for value in values if str(value).isdigit() and int(value) > 0}
    if tenant_id == 1:
        result.update(await AppCandidateRepository.root_role_ids())
    return tuple(sorted(result))


async def app_candidate_policy(tenant_id, owner_user_id, self_review_user_id) -> AppCandidatePolicy | None:
    if (
        type(tenant_id) is not int
        or tenant_id <= 0
        or type(owner_user_id) is not int
        or owner_user_id <= 0
        or type(self_review_user_id) is not int
        or self_review_user_id <= 0
    ):
        return None
    admins = await administrator_ids(tenant_id)
    global_ids = admins if tenant_id == 1 else await administrator_ids(1)
    actual_admins = await AppCandidateRepository.eligible_ids(tenant_id, admins, global_ids=global_ids)
    return AppCandidatePolicy(
        tenant_id,
        frozenset({owner_user_id, self_review_user_id}),
        frozenset(actual_admins),
        tuple(global_ids),
        tuple(admins),
    )


async def qualify_app_candidates(tenant_id, owner_user_id, self_review_user_id, candidates):
    policy = await app_candidate_policy(tenant_id, owner_user_id, self_review_user_id)
    return await policy.qualify(candidates) if policy is not None else QualifiedAppCandidates(())
