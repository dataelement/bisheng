import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthContext } from '~/hooks';
import { getPlatformAdminPanelUrl } from '~/utils/platformAdminUrl';
import { canOpenPlatformAdminPanel, canOpenWorkbench } from '~/utils/platformAccess';

type WorkbenchAccessUser = {
  role?: string | null;
  plugins?: string[] | null;
  is_department_admin?: boolean | null;
  has_workbench?: boolean | null;
  has_admin_console?: boolean | null;
};

function hasWorkbenchAccess(user?: WorkbenchAccessUser | null) {
  if (!user) return true;
  if (typeof user.has_workbench === 'boolean') return user.has_workbench;
  if (!Array.isArray(user.plugins)) return true;
  return canOpenWorkbench({
    role: user.role,
    plugins: user.plugins,
    is_department_admin: user.is_department_admin,
  });
}

function hasAdminConsoleAccess(user?: WorkbenchAccessUser | null) {
  if (!user) return false;
  if (typeof user.has_admin_console === 'boolean') return user.has_admin_console;
  return canOpenPlatformAdminPanel({
    role: user.role,
    plugins: Array.isArray(user.plugins) ? user.plugins : null,
    is_department_admin: user.is_department_admin,
  });
}

export default function WorkbenchAccessGuard() {
  const navigate = useNavigate();
  const { user } = useAuthContext();

  useEffect(() => {
    const accessUser = user as WorkbenchAccessUser | null;
    if (!accessUser || hasWorkbenchAccess(accessUser)) return;

    if (hasAdminConsoleAccess(accessUser)) {
      window.location.replace(getPlatformAdminPanelUrl('error=90002'));
      return;
    }

    navigate('/404', { replace: true });
  }, [navigate, user]);

  return null;
}
