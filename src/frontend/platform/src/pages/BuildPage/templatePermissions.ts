import type { User } from '@/types/api/user';

export function canManageAppTemplates(user?: Partial<User> | null): boolean {
    return Boolean(user && (user.is_global_super || user.role === 'admin' || user.is_child_admin));
}
