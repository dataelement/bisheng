const PLATFORM_ENTRY_KEYS = ['admin', 'backend'];
const WORKBENCH_ENTRY_KEYS = ['workstation', 'frontend'];

// Admin-area *content* menus (children), i.e. backend _WEB_MENU_ADMIN_ALL minus
// the parent entry keys. A user genuinely has admin access only when web_menu
// contains one of these — the bare `admin`/`backend` parent alone is not real
// access, so it must not keep the 管理后台 entry visible once the admin approval
// scope is off.
const ADMIN_CHILD_KEYS = [
  'build',
  'create_app',
  'knowledge',
  'create_knowledge',
  'model',
  'tool',
  'mcp',
  'channel',
  'evaluation',
  'dataset',
  'mark_task',
  'board',
  'create_dashboard',
];

/** True when web_menu (plugins) grants at least one real admin content menu. */
export function hasRealAdminMenu(plugins?: string[] | null): boolean {
  if (!Array.isArray(plugins)) return false;
  return ADMIN_CHILD_KEYS.some((key) => plugins.includes(key));
}

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
