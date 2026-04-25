import type { User } from "@/types/api/user";

export function canManageModelSettings(user?: Partial<User> | null): boolean {
    if (!user) return false;
    return user.role === "admin" || Boolean(user.web_menu?.includes("model"));
}

// Backend stamps ``is_global_super`` on the JWT-derived user payload.
// Falls back to ``role==='admin'`` for legacy sessions that predate F019.
export function isGlobalSuperUser(user?: Partial<User> | null): boolean {
    if (!user) return false;
    return Boolean(user.is_global_super) || user.role === "admin";
}
