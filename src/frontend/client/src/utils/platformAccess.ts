const PLATFORM_MENU_KEYS = [
  'admin',
  'backend',
  'knowledge',
  'build',
  'create_app',
  'model',
  'sys',
  'system_config',
  'log',
  'board',
  'mark_task',
];

type PlatformAccessUserLike = {
  role?: string | null;
  plugins?: string[] | null;
  is_department_admin?: boolean | null;
};

export function canOpenPlatformAdminPanel(user?: PlatformAccessUserLike | null): boolean {
  if (!user) return false;
  if (user.role === 'admin') return true;
  if (user.is_department_admin) return true;
  if (!Array.isArray(user.plugins)) return false;
  return PLATFORM_MENU_KEYS.some((key) => user.plugins?.includes(key));
}

