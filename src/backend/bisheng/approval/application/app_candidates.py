"""App-only dual exclusion and an independently proven single-administrator exception."""

from dataclasses import dataclass

from bisheng.approval.domain.repositories.app_candidate_repository import AppCandidateRepository
from bisheng.permission.application import PermissionObject, get_permission_relation_api


@dataclass(frozen=True, slots=True)
class QualifiedAppCandidates:
    user_ids: tuple[int, ...]
    self_approval: bool = False


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


async def qualify_app_candidates(tenant_id, owner_user_id, self_review_user_id, candidates):
    if (
        type(tenant_id) is not int
        or tenant_id <= 0
        or type(owner_user_id) is not int
        or owner_user_id <= 0
        or type(self_review_user_id) is not int
        or self_review_user_id <= 0
    ):
        return QualifiedAppCandidates(())
    values = tuple(dict.fromkeys(int(uid) for uid in candidates if str(uid).isdigit() and int(uid) > 0))
    admins = await administrator_ids(tenant_id)
    global_ids = admins if tenant_id == 1 else await administrator_ids(1)
    active = set(await AppCandidateRepository.eligible_ids(tenant_id, (*values, *admins), global_ids=global_ids))
    eligible = tuple(uid for uid in values if uid in active)
    excluded = {owner_user_id, self_review_user_id}
    result = tuple(uid for uid in eligible if uid not in excluded)
    actual_admins = set(admins).intersection(active)
    if not result and len(actual_admins) == 1 and set(eligible) == actual_admins:
        return QualifiedAppCandidates(tuple(actual_admins), True)
    return QualifiedAppCandidates(result)
