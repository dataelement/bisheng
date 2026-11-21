import type { User } from "@/types/api/user";

// Model management, system settings and FT service management are admin-only
// in both single-tenant and multi-tenant deployments.
export function canManageModelSettings(
    user?: Partial<User> | null,
): boolean {
    return canManageWorkbenchConfig(user);
}

export function canManageWorkbenchConfig(user?: Partial<User> | null): boolean {
    if (!user) return false;
    return Boolean(user.is_global_super)
        || user.role === "admin"
        || Boolean(user.is_child_admin);
}

// Backend stamps ``is_global_super`` on the JWT-derived user payload.
// Falls back to ``role==='admin'`` for legacy sessions that predate F019.
export function isGlobalSuperUser(user?: Partial<User> | null): boolean {
    if (!user) return false;
    return Boolean(user.is_global_super) || user.role === "admin";
}

const ROOT_TENANT_ID = 1;

interface ShareToggleContext {
    multiTenantEnabled?: boolean;
    user?: Partial<User> | null;
    // True on the "add model" screen, where no server row exists yet.
    isCreate: boolean;
    // Owning tenant of the server being edited (edit mode only).
    serverTenantId?: number | null;
    // Active F019 admin scope; null/undefined means the default Root view.
    scopeTenantId?: number | null;
}

// Whether the "share with child tenants" toggle should render.
//
// Sharing only ever fans out from Root: the tenant tree is locked to two
// layers (INV-T1, ``TenantTreeNestingForbiddenError``), so a child-owned
// server has no children to share with and the backend silently skips the
// fan-out. On create, the owning tenant is decided by the active admin
// scope — a super admin viewing a child tenant creates a child-owned row,
// where the toggle would be a dead switch.
export function canShareToChildren(ctx: ShareToggleContext): boolean {
    if (!ctx.multiTenantEnabled) return false;
    if (!isGlobalSuperUser(ctx.user)) return false;
    if (ctx.isCreate) {
        return ctx.scopeTenantId == null || ctx.scopeTenantId === ROOT_TENANT_ID;
    }
    return ctx.serverTenantId === ROOT_TENANT_ID;
}
