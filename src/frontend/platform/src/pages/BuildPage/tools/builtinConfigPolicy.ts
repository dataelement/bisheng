import type { User } from '@/types/api/user';

export function canConfigureBuiltinTool(user: Partial<User> | null | undefined, tenantId: number): boolean {
    if (user?.is_global_super) return true;
    return Boolean(user?.is_child_admin)
        && Number.isInteger(tenantId)
        && tenantId > 0
        && tenantId === (user?.leaf_tenant_id ?? user?.tenant_id);
}
