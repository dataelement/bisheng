import type { ComponentType } from 'react';
import { useMemo } from 'react';
import { matchPath, NavLink, useLocation } from 'react-router-dom';
import BookOpenIcon from '~/components/ui/icon/BookOpen';
import GlobeIcon from '~/components/ui/icon/Globe';
import HomeIcon from '~/components/ui/icon/Home';
import LinkIcon from '~/components/ui/icon/Link';
import { useAuthContext, useLocalize } from '~/hooks';
import { lastSectionPaths } from '~/layouts/appModuleNavPaths';
import { cn } from '~/utils';
import { canOpenWorkbench } from '~/utils/platformAccess';

export type HubModuleSection = 'home' | 'apps' | 'channel' | 'knowledge';

export interface HubModuleLink {
  section: HubModuleSection;
  to: string;
  icon: ComponentType<{ className?: string }>;
  label: string;
  isActive: boolean;
  /** When true, callers may close the drawer after navigation. */
  closeDrawerOnNavigate?: boolean;
}

/** Shared row styles: matches MainLayout narrow SidebarItem (p-3, rounded-lg, #e6edfc). */
const hubNavItemClassName = (
  navActive: boolean,
  routeActive: boolean,
  equalWidth: boolean,
  squareItems: boolean,
) =>
  cn(
    'flex cursor-pointer items-center justify-center rounded-lg p-3 transition-colors fine-pointer:hover:bg-[#e6edfc] coarse-pointer:hover:bg-transparent',
    squareItems && 'h-11 w-11 p-0 shrink-0',
    equalWidth && !squareItems && 'min-w-0 flex-1',
    !equalWidth && 'shrink-0',
    (navActive || routeActive) && 'bg-[#e6edfc]',
  );

const hubIconClassName = (on: boolean) =>
  cn('size-5 shrink-0', on ? 'text-[#335CFF]' : 'text-[#818181]');

export function useHubModuleLinks(): HubModuleLink[] {
  const { pathname } = useLocation();
  const localize = useLocalize();
  const { user } = useAuthContext();
  const plugins: string[] | null = Array.isArray((user as { plugins?: unknown })?.plugins)
    ? (user as { plugins: string[] }).plugins
    : null;
  const canOpenWorkbenchEntry =
    !Array.isArray(plugins) ||
    canOpenWorkbench({
      role: user?.role,
      plugins,
      is_department_admin: (user as { is_department_admin?: boolean } | undefined)?.is_department_admin,
    });
  const menuApprovalMode = Boolean((user as { menu_approval_mode?: boolean })?.menu_approval_mode);
  const hasPlugin = (id: string) => (plugins ? plugins.includes(id) : true);
  const showWorkbenchItem = (id: string) => hasPlugin(id) || menuApprovalMode;
  const showSubscriptionTab = showWorkbenchItem('subscription');
  const showKnowledgeSpaceTab = showWorkbenchItem('knowledge_space');
  const showHomeTab = showWorkbenchItem('home');
  const showAppsTab = showWorkbenchItem('apps');

  return useMemo(
    () => {
      if (!canOpenWorkbenchEntry) return [];
      return [
        {
          section: 'home',
          to: hasPlugin('home') || !menuApprovalMode ? (lastSectionPaths.home || '/c/new') : '/menu-unavailable',
          icon: HomeIcon,
          label: localize('com_nav_home'),
          isActive: /^\/(c|linsight)(\/|$)/.test(pathname),
          closeDrawerOnNavigate: false,
        },
        {
          section: 'apps',
          to: '/apps',
          icon: GlobeIcon,
          label: localize('com_nav_app_center'),
          isActive:
            matchPath('/app/:id/:fid/:type', pathname) !== null || pathname.startsWith('/apps'),
          closeDrawerOnNavigate: false,
        },
        {
          section: 'channel',
          to: hasPlugin('subscription') || !menuApprovalMode ? (lastSectionPaths.channel || '/channel') : '/menu-unavailable',
          icon: LinkIcon,
          label: localize('com_ui_channel'),
          isActive: pathname.startsWith('/channel'),
          closeDrawerOnNavigate: true,
        },
        {
          section: 'knowledge',
          to: hasPlugin('knowledge_space') || !menuApprovalMode ? (lastSectionPaths.knowledge || '/knowledge') : '/menu-unavailable',
          icon: BookOpenIcon,
          label: localize('com_knowledge.knowledge_space'),
          isActive: pathname.startsWith('/knowledge'),
          closeDrawerOnNavigate: true,
        },
      ].filter((link) => {
        if (link.section === 'home') return showHomeTab;
        if (link.section === 'apps') return showAppsTab;
        if (link.section === 'channel') return showSubscriptionTab;
        if (link.section === 'knowledge') return showKnowledgeSpaceTab;
        return true;
      });
    },
    [canOpenWorkbenchEntry, localize, pathname, showKnowledgeSpaceTab, showSubscriptionTab, showHomeTab, showAppsTab, menuApprovalMode, plugins],
  );
}

interface HubModuleNavTabsProps {
  /** Equal-width cells (e.g. app chat sidebar); default is compact centered icons like H5 drawers. */
  equalWidth?: boolean;
  /** Render fixed square tab buttons. */
  squareItems?: boolean;
  onLinkClick?: (link: HubModuleLink) => void;
  className?: string;
}

export function HubModuleNavTabs({
  equalWidth = false,
  squareItems = false,
  onLinkClick,
  className,
}: HubModuleNavTabsProps) {
  const links = useHubModuleLinks();

  return (
    <div
      className={cn(
        'flex shrink-0 gap-2 border-b border-[#e5e6eb] px-2 py-2 touch-mobile:border-b-0',
        equalWidth && 'w-full min-w-0',
        squareItems ? 'items-center justify-between' : equalWidth ? 'items-stretch' : 'items-center justify-center',
        className,
      )}
    >
      {links.map((link) => {
        const Icon = link.icon;
        return (
          <NavLink
            key={link.section}
            to={link.to}
            title={link.label}
            aria-label={link.label}
            onClick={() => onLinkClick?.(link)}
            className={({ isActive: navActive }) =>
              hubNavItemClassName(navActive, link.isActive, equalWidth, squareItems)
            }
          >
            {({ isActive: navActive }) => {
              const on = navActive || link.isActive;
              return <Icon className={hubIconClassName(on)} />;
            }}
          </NavLink>
        );
      })}
    </div>
  );
}
