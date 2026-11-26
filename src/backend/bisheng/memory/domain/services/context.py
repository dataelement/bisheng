"""Build a MemoryContext for the logged-in user of a management API call."""

from __future__ import annotations

from bisheng.memory.domain.ports import SCENE_MANUAL, MemoryContext


def build_user_context(login_user, tenant_id: int | None = None, timezone: str | None = None) -> MemoryContext:
    """Current tenant + the caller themself; never another user (design decision 9)."""
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id

    tid = tenant_id if tenant_id is not None else get_current_tenant_id()
    if tid is None:
        tid = getattr(login_user, "tenant_id", None) or DEFAULT_TENANT_ID
    return MemoryContext(
        tenant_id=int(tid),
        user_id=int(login_user.user_id),
        timezone=timezone or "Asia/Shanghai",
        scene=SCENE_MANUAL,
    )
