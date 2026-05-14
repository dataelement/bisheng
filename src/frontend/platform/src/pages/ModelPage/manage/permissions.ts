import type { User } from "@/types/api/user";

// Mirrors the backend's ``get_tenant_admin_user`` decision: global super admin
// or the active tenant's Child Admin. The legacy ``web_menu['model']`` path is
// kept as a fallback for single-tenant deployments where role-based menu
// access is still authoritative.
export function canManageModelSettings(user?: Partial<User> | null): boolean {
    if (!user) return false;
    return user.role === "admin"
        || Boolean(user.is_child_admin)
        || Boolean(user.web_menu?.includes("model"));
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
