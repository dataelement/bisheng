"""Dependency-inverted permission hook for shared authentication dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

TenantAdminChecker = Callable[[int, int], Awaitable[bool]]

_tenant_admin_checker: TenantAdminChecker | None = None


def configure_tenant_admin_checker(checker: TenantAdminChecker) -> None:
    global _tenant_admin_checker
    _tenant_admin_checker = checker


async def check_tenant_admin(user_id: int, tenant_id: int) -> bool:
    checker = _tenant_admin_checker
    if checker is None:
        return False
    return bool(await checker(user_id, tenant_id))
