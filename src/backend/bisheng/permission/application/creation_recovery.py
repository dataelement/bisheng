"""Narrow domain-internal recovery; no HTTP pending bypass or alternate idempotency key."""

from bisheng.permission.application.access import get_f048_runtime


async def resume_created_permission(*, actor, target, owner_user_id):
    return await (await get_f048_runtime()).resume_created(actor=actor, target=target, owner_user_id=owner_user_id)
