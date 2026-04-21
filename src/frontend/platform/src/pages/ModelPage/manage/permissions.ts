import type { User } from "@/types/api/user";

export function canManageModelSettings(user?: Partial<User> | null): boolean {
    if (!user) return false;
    return user.role === "admin" || Boolean(user.web_menu?.includes("model"));
}
