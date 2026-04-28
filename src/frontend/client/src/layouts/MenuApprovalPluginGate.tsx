import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuthContext } from '~/hooks';

type MenuApprovalUser = {
  plugins?: unknown;
  menu_approval_mode?: boolean;
};

/**
 * With menu approval enabled, workbench sections without the corresponding WEB_MENU plugin
 * show the blank placeholder (/menu-unavailable), same as Sidebar NavLink targets.
 */
export default function MenuApprovalPluginGate({
  pluginId,
  children,
}: {
  pluginId: string;
  children: ReactNode;
}) {
  const { user } = useAuthContext();
  const u = user as MenuApprovalUser | null;
  const plugins = u?.plugins;
  const menuApprovalMode = Boolean(u?.menu_approval_mode);
  if (!Array.isArray(plugins)) {
    return <>{children}</>;
  }
  if (menuApprovalMode && !plugins.includes(pluginId)) {
    return <Navigate to="/menu-unavailable" replace />;
  }
  return <>{children}</>;
}
