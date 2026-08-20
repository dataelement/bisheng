import { useGetBsConfig } from '~/hooks/queries/data-provider';
import useLocalize from './useLocalize';

/** Workbench sidebar modules, keyed the same way as the sidebar link sections. */
export type WorkbenchMenuKey = 'home' | 'knowledge' | 'channel' | 'apps';

/**
 * Admin-configured names for the workbench sidebar entries (platform 构建 → 工作台,
 * one 菜单显示名称 per module). A blank/absent value keeps the localized default,
 * so deployments that never configure a name still follow the UI language.
 */
export function useWorkbenchMenuNames(): Record<WorkbenchMenuKey, string> {
  const localize = useLocalize();
  const { data: bsConfig } = useGetBsConfig();

  return {
    home: bsConfig?.homeMenuDisplayName?.trim() || localize('com_nav_home'),
    knowledge:
      bsConfig?.knowledge_space?.menu_display_name?.trim() ||
      localize('com_knowledge.knowledge_space'),
    channel: bsConfig?.subscription?.menu_display_name?.trim() || localize('com_ui_channel'),
    apps: bsConfig?.appCenterMenuDisplayName?.trim() || localize('com_nav_app_center'),
  };
}
