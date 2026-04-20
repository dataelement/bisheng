from __future__ import annotations

from typing import List

from fastapi import Depends, HTTPException

from bisheng.user.domain.services.auth import AuthJwt, LoginUser


class UserPayload(LoginUser):
    """Auth-injected user identity used by FastAPI endpoints."""

    async def get_visible_tenants(self) -> List[int]:
        """Return the user's visible tenant ids in MVP 2-layer rule.

        Visible set = {leaf} ∪ {root}. Deduplicated when leaf == root.

        Primary path reads the ``visible_tenant_ids`` ContextVar injected by
        F012's ``CustomMiddleware`` — for Child users it holds ``{leaf, 1}``;
        for Root users ``{1}``; for global super admins without admin-scope
        it is ``None``. Returning ordered ``[leaf, root]`` preserves prior
        test expectations.

        Fallback: when the ContextVar is ``None`` (super admin, tests without
        middleware, or any legacy call site bypassing the HTTP layer), look
        up the active leaf via ``UserTenantDao``. Both paths end up with the
        same 2-element (or 1-element) list.
        """
        from bisheng.core.context.tenant import (
            DEFAULT_TENANT_ID,
            get_visible_tenant_ids,
        )

        visible = get_visible_tenant_ids()
        if visible is not None:
            if DEFAULT_TENANT_ID in visible and len(visible) > 1:
                others = sorted(visible - {DEFAULT_TENANT_ID})
                return [*others, DEFAULT_TENANT_ID]
            return sorted(visible)

        # Fallback: no ContextVar set. Local import keeps the module import-light
        # and avoids circular deps at load time (LoginUser is the parent class).
        from bisheng.database.models.tenant import UserTenantDao

        active = await UserTenantDao.aget_active_user_tenant(self.user_id)
        leaf_id = active.tenant_id if active else DEFAULT_TENANT_ID
        if leaf_id == DEFAULT_TENANT_ID:
            return [DEFAULT_TENANT_ID]
        return [leaf_id, DEFAULT_TENANT_ID]

    async def has_tenant_admin(self, tenant_id: int) -> bool:
        """True iff the user holds a direct ``tenant#admin`` tuple on the tenant.

        Non-inheriting (INV-T3, AD-01). Always False for the Root tenant —
        Root admins are granted via ``system:global#super_admin`` and there
        are no ``tenant:1#admin`` tuples by design.

        Returns False (fail-closed) when OpenFGA is unavailable.

        TODO(F012): can be cached via JWT-embedded admin tenants list once
        F012 ships token rotation on Tenant grant changes.
        """
        from bisheng.core.context.tenant import DEFAULT_TENANT_ID
        from bisheng.core.openfga.manager import aget_fga_client

        if tenant_id == DEFAULT_TENANT_ID:
            return False
        fga = await aget_fga_client()
        if fga is None:
            return False
        return await fga.check(
            user=f'user:{self.user_id}',
            relation='admin',
            object=f'tenant:{tenant_id}',
        )

    @classmethod
    async def get_tenant_admin_user(cls, auth_jwt: AuthJwt = Depends()) -> 'UserPayload':
        """Admit global super admin or the current tenant's Child Admin;
        reject with 403 + 19801 otherwise. Admin-scope override is
        honoured via ``get_current_tenant_id()``, so a super admin
        switched to Child 5 passes the super branch; an ordinary Child
        Admin for tenant 5 passes via ``has_tenant_admin(5)``.
        """
        from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
        from bisheng.core.context.tenant import (
            DEFAULT_TENANT_ID,
            get_current_tenant_id,
        )
        from bisheng.utils.http_middleware import _check_is_global_super

        user: 'UserPayload' = await cls.get_login_user(auth_jwt)
        if await _check_is_global_super(user.user_id):
            return user

        tid = get_current_tenant_id()
        if (tid is not None
                and tid != DEFAULT_TENANT_ID
                and await user.has_tenant_admin(tid)):
            return user

        raise HTTPException(
            status_code=403,
            detail={
                'status_code': LLMModelSharedReadonlyError.Code,
                'status_message': LLMModelSharedReadonlyError.Msg,
            },
        )
