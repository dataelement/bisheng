"""Operational migration through existing versioned and audited policy services."""

import asyncio
from uuid import NAMESPACE_URL, uuid5

from bisheng.dsh.domain.schemas.admin import SubjectPolicyInput
from bisheng.dsh.domain.schemas.contracts import DshUserPolicyInput


def role_migration_plan(users):
    plan = []
    for user in users:
        role_limit = max(
            (source["monthly_token_limit"] for source in user["sources"] if source["subject_type"] == "ROLE"), default=0
        )
        if role_limit > 0:
            personal = user["direct_monthly_token_limit"] if user["direct_enabled"] else 0
            plan.append(
                {
                    "user_id": user["user_id"],
                    "before_limit": personal,
                    "target_limit": max(personal, role_limit),
                    "effective_limit": user["monthly_token_limit"],
                    "version": user["direct_version"],
                    "pending": user["direct_pending_operation_id"],
                }
            )
    return plan


async def migrate_role_policies(service, *, actor_id, tenant_id, model_id, apply=False):
    inventory = await service.model_subjects(actor_id, model_id, tenant_id=tenant_id)
    roles = [role for role in inventory["roles"] if role["enabled"] and role["monthly_token_limit"] > 0]

    async def read_users():
        users, cursor, seen = [], None, set()
        while True:
            page = await service.model_user_permissions(
                actor_id, model_id, tenant_id=tenant_id, cursor=cursor, limit=100
            )
            users.extend(page["items"])
            if not page["has_more"]:
                return users
            cursor = page["next_cursor"]
            if cursor in seen:
                raise RuntimeError("Repeated migration page cursor")
            seen.add(cursor)

    original = await read_users()
    plan = role_migration_plan(original) if roles else []
    report = {"tenant_id": tenant_id, "model_id": model_id, "roles": roles, "users": plan, "applied": False}
    if not apply or not roles:
        return report
    for item in plan:
        if item["before_limit"] >= item["target_limit"] and not item["pending"]:
            continue
        if item["pending"]:
            result = await service.operation(actor_id, item["pending"], tenant_id=tenant_id)
        else:
            operation_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"dsh-role-migration:{tenant_id}:{model_id}:{item['user_id']}:{item['version']}:{item['target_limit']}",
                )
            )
            result = await service.update_policy(
                actor_id,
                item["user_id"],
                DshUserPolicyInput(
                    operation_id=operation_id,
                    expected_version=item["version"],
                    enabled=True,
                    monthly_token_limit=item["target_limit"],
                ),
                model_id=model_id,
                tenant_id=tenant_id,
            )
        for _ in range(30):
            if result["status"] in ("SUCCEEDED", "FAILED"):
                break
            await asyncio.sleep(0.5)
            result = await service.operation(actor_id, result["operation_id"], tenant_id=tenant_id)
        if result["status"] != "SUCCEEDED":
            raise RuntimeError(f"Personal quota migration incomplete for user {item['user_id']}")
    confirmed = await read_users()
    by_id = {row["user_id"]: row for row in confirmed}
    for item in plan:
        saved = by_id.get(item["user_id"])
        if (
            not saved
            or saved["direct_pending_operation_id"]
            or not saved["direct_enabled"]
            or saved["direct_monthly_token_limit"] < item["target_limit"]
        ):
            raise RuntimeError(f"Personal quota verification failed for user {item['user_id']}")
    # Recheck role membership before retiring its future authorization source.
    if {item["user_id"] for item in role_migration_plan(confirmed)} != {item["user_id"] for item in plan}:
        raise RuntimeError("Role membership changed during migration; retry after organization changes settle")
    for role in roles:
        await service.update_subject_policy(
            actor_id,
            model_id,
            "ROLE",
            role["subject_id"],
            SubjectPolicyInput(
                expected_version=role["version"], enabled=False, monthly_token_limit=role["monthly_token_limit"]
            ),
            tenant_id=tenant_id,
        )
    final = await read_users()
    before_limits = {row["user_id"]: row["monthly_token_limit"] for row in original}
    after_limits = {row["user_id"]: row["monthly_token_limit"] for row in final}
    if before_limits != after_limits:
        raise RuntimeError("Effective quotas changed during migration; inspect concurrent organization edits")
    report.update(applied=True, verified_users=len(final), effective_limits=after_limits)
    return report
