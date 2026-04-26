const PLATFORM_ENTRY_KEYS = ['admin', 'backend'];
const WORKBENCH_ENTRY_KEYS = ['workstation', 'frontend'];

type PlatformAccessUserLike = {
  role?: string | null;
  plugins?: string[] | null;
  is_department_admin?: boolean | null;
};

// Keep this check centralized so CI retriggers do not split Client entry-point gating.
export function canOpenPlatformAdminPanel(user?: PlatformAccessUserLike | null): boolean {
  if (!user) return false;
  if (user.role === 'admin') return true;
  if (user.is_department_admin) return true;
  if (!Array.isArray(user.plugins)) return false;
  return PLATFORM_ENTRY_KEYS.some((key) => user.plugins?.includes(key));
}

export function canOpenWorkbench(user?: PlatformAccessUserLike | null): boolean {
  if (!user) return false;
  if (user.role === 'admin') return true;
  if (user.is_department_admin) return true;
  if (!Array.isArray(user.plugins)) return false;
  return WORKBENCH_ENTRY_KEYS.some((key) => user.plugins?.includes(key));
}
