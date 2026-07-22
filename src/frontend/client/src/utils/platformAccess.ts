const PLATFORM_ENTRY_KEYS = ['admin', 'backend'];
const WORKBENCH_ENTRY_KEYS = ['workstation', 'frontend'];

type PlatformAccessUserLike = {
  role?: string | null;
  plugins?: string[] | null;
  is_department_admin?: boolean | null;
  has_admin_console?: boolean | null;
};

// Keep this check centralized so CI retriggers do not split Client entry-point gating.
export function canOpenPlatformAdminPanel(user?: PlatformAccessUserLike | null): boolean {
  if (!user) return false;
  if (user.role === 'admin') return true;
  if (user.is_department_admin) return true;
  if (!Array.isArray(user.plugins)) return false;
  return PLATFORM_ENTRY_KEYS.some((key) => user.plugins?.includes(key));
}

// The backend-computed area flag is authoritative for current servers. When it
// is unavailable, keep the role-dialog parent-menu semantics used by legacy
// servers instead of treating the deprecated `backend` alias as an entry grant.
export function canShowPlatformAdminEntry(user?: PlatformAccessUserLike | null): boolean {
  if (!user) return false;
  if (typeof user.has_admin_console === 'boolean') return user.has_admin_console;
  if (user.role === 'admin') return true;
  if (user.is_department_admin) return true;
  return Boolean(user.plugins?.includes('admin'));
}

export function canOpenWorkbench(user?: PlatformAccessUserLike | null): boolean {
  if (!user) return false;
  if (user.role === 'admin') return true;
  if (!Array.isArray(user.plugins)) return false;
  return WORKBENCH_ENTRY_KEYS.some((key) => user.plugins?.includes(key));
}
