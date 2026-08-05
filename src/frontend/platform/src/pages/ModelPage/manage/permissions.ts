import type { User } from "@/types/api/user";

// Mirrors the backend's ``get_tenant_admin_user`` decision: global super admin
// or the active tenant's Child Admin. The legacy ``web_menu['model']`` path is
// kept ONLY as a single-tenant fallback where role-based menu access is still
// authoritative; in multi-tenant deployments model management is admin-only, so
// a regular user who merely holds the (read-only) ``model`` menu must NOT see
// system-model-settings / add-model / availability toggles (the backend would
// 403 them anyway via ``get_tenant_admin_user``).
export function canManageModelSettings(
    user?: Partial<User> | null,
    multiTenantEnabled?: boolean,
): boolean {
    if (!user) return false;
    if (user.role === "admin" || Boolean(user.is_global_super) || Boolean(user.is_child_admin)) {
        return true;
    }
    if (multiTenantEnabled) return false;
    return Boolean(user.web_menu?.includes("model"));
}

// Workbench config is intentionally stricter than model settings:
// only global super admins and the active tenant's Child Admin may access it.
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
