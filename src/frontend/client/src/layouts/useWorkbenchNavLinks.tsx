import { Filled, Outlined } from 'bisheng-icons';
import type { ReactNode } from 'react';
import { useMemo } from 'react';
import { matchPath, useLocation } from 'react-router-dom';
import { skillCenterPath, skillCenterPreviewEnabled } from '~/components/Skills/types';
import { useAuthContext, useLocalize, usePrefersMobileLayout, useWorkbenchMenuNames } from '~/hooks';
import { canOpenWorkbench, canShowPlatformAdminEntry } from '~/utils/platformAccess';
import { appsSectionLinkTarget, lastSectionPaths } from './appModuleNavPaths';

export type WorkbenchNavSection = 'home' | 'apps' | 'channel' | 'knowledge' | 'skills';

/** Desktop sidebar groups: 知识资讯 (content to read and ask about) / 智能拓展 (things that do work). */
export type WorkbenchHubId = 'knowledge' | 'ability';

export interface WorkbenchNavLink {
  section: WorkbenchNavSection;
  /** Hub the desktop sidebar folds this module into; 首页 stands alone. */
  hub?: WorkbenchHubId;
  /** Backend `web_menu` key that grants this module. */
  plugin: string;
  to: string;
  icon: ReactNode;
  /** Icon shown when active (the Filled variant). */
  activeIcon: ReactNode;
  label: string;
  isActive: boolean;
  closeDrawerOnNavigate: boolean;
}

type WorkbenchUser = {
  plugins?: string[];
  is_department_admin?: boolean;
  has_admin_console?: boolean;
  menu_approval_mode_workbench?: boolean;
  menu_approval_mode?: boolean;
};

/**
 * Workbench module entries (首页 / 知识空间 / 频道 / 应用 / 技能) with permission gating and
 * per-section last-path restoration. Shared by the desktop sidebar and the mobile rail
 * so the two never disagree about which modules a user can see.
 */
export function useWorkbenchNavLinks(): { links: WorkbenchNavLink[]; showAdminEntry: boolean } {
  const { pathname, search } = useLocation();
  const { user } = useAuthContext();
  const menuNames = useWorkbenchMenuNames();
  const localize = useLocalize();
  const skillCenterLabel = localize('com_skill_center_title');
  const isMobile = usePrefersMobileLayout();
  const workbenchUser = user as (typeof user & WorkbenchUser) | undefined;

  // On the menu-unavailable placeholder the URL carries the originating menu as
  // `?plugin=xxx`; use it to keep that section's entry highlighted.
  const menuUnavailablePlugin = pathname.startsWith('/menu-unavailable')
    ? new URLSearchParams(search).get('plugin') || ''
    : '';

  // Backend returns `web_menu` but we map it into front-end user as `plugins`.
  const plugins: string[] | null = Array.isArray(workbenchUser?.plugins)
    ? workbenchUser.plugins
    : null;
  const canOpenWorkbenchEntry =
    !Array.isArray(plugins) ||
    canOpenWorkbench({
      role: user?.role,
      plugins,
      is_department_admin: workbenchUser?.is_department_admin,
    });
  // Workbench approval scope gates the workspace tabs (falls back to the legacy
  // global flag for roles saved before the workbench/admin split).
  const menuApprovalMode = Boolean(
    workbenchUser?.menu_approval_mode_workbench ?? workbenchUser?.menu_approval_mode,
  );
  const pluginsKey = plugins ? plugins.join(',') : null;

  // Prefer the backend-computed effective area permission. This includes tenant
  // admins whose role still carries the compatible `backend` key rather than the
  // newer `admin` parent key. Older servers fall back to parent-menu semantics.
  const showAdminEntry = canShowPlatformAdminEntry({
    role: user?.role,
    plugins,
    is_department_admin: workbenchUser?.is_department_admin,
    has_admin_console: workbenchUser?.has_admin_console,
  });

  const links = useMemo<WorkbenchNavLink[]>(() => {
    if (!canOpenWorkbenchEntry) return [];
    const granted = pluginsKey === null ? null : pluginsKey.split(',');
    const hasPlugin = (id: string) => (granted ? granted.includes(id) : true);
    const canShow = (id: string) => hasPlugin(id) || menuApprovalMode;
    const target = (id: string, to: string) =>
      hasPlugin(id) || !menuApprovalMode ? to : `/menu-unavailable?plugin=${id}`;

    const all: WorkbenchNavLink[] = [
      {
        section: 'home',
        plugin: 'home',
        to: target('home', lastSectionPaths.home || '/c/new'),
        icon: <Outlined.Home />,
        activeIcon: <Filled.Home />,
        label: menuNames.home,
        isActive: /^\/(c|linsight)(\/|$)/.test(pathname) || menuUnavailablePlugin === 'home',
        closeDrawerOnNavigate: true,
      },
      {
        section: 'knowledge',
        hub: 'knowledge',
        plugin: 'knowledge_space',
        // List-page-first on every shell: the menu always opens the module home
        // (/knowledge), never the last-visited space.
        to: target('knowledge_space', '/knowledge'),
        icon: <Outlined.Book />,
        activeIcon: <Filled.Book />,
        label: menuNames.knowledge,
        isActive: pathname.startsWith('/knowledge') || menuUnavailablePlugin === 'knowledge_space',
        closeDrawerOnNavigate: true,
      },
      {
        section: 'channel',
        hub: 'knowledge',
        plugin: 'subscription',
        // Desktop opens the module home, like 知识空间; mobile has no channel home and
        // keeps restoring the last-visited channel.
        to: target('subscription', isMobile ? lastSectionPaths.channel || '/channel' : '/channel'),
        icon: <Outlined.Rss />,
        activeIcon: <Filled.Rss />,
        label: menuNames.channel,
        isActive: pathname.startsWith('/channel') || menuUnavailablePlugin === 'subscription',
        closeDrawerOnNavigate: true,
      },
      {
        section: 'apps',
        hub: 'ability',
        plugin: 'apps',
        to: target('apps', appsSectionLinkTarget()),
        icon: <Outlined.Application />,
        activeIcon: <Filled.Application />,
        label: menuNames.apps,
        isActive:
          matchPath('/app/:id/:fid/:type', pathname) !== null ||
          pathname.startsWith('/apps') ||
          menuUnavailablePlugin === 'apps',
        closeDrawerOnNavigate: true,
      },
      {
        // 技能 has no menu key of its own yet: it rides on 首页's grant, behind the
        // deployment's preview switch.
        section: 'skills',
        hub: 'ability',
        plugin: 'home',
        to: target('home', skillCenterPath),
        icon: <Outlined.Newspaper />,
        activeIcon: <Outlined.Newspaper />,
        label: skillCenterLabel,
        isActive: pathname.startsWith(skillCenterPath),
        closeDrawerOnNavigate: true,
      },
    ];
    return all.filter((link) => canShow(link.plugin) && (link.section !== 'skills' || skillCenterPreviewEnabled));
    // Menu names are read field-by-field: the hook returns a fresh object each render.
  }, [canOpenWorkbenchEntry, pathname, menuUnavailablePlugin, isMobile, menuApprovalMode, pluginsKey,
    menuNames.home, menuNames.knowledge, menuNames.channel, menuNames.apps, skillCenterLabel]);

  return { links, showAdminEntry };
}
