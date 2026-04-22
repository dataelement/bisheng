import type { ComponentType } from 'react';
import { useMemo } from 'react';
import { matchPath, NavLink, useLocation } from 'react-router-dom';
import BookOpenIcon from '~/components/ui/icon/BookOpen';
import GlobeIcon from '~/components/ui/icon/Globe';
import HomeIcon from '~/components/ui/icon/Home';
import LinkIcon from '~/components/ui/icon/Link';
import { useAuthContext, useLocalize } from '~/hooks';
import { appsSectionLinkTarget, lastSectionPaths } from '~/layouts/appModuleNavPaths';
import { cn } from '~/utils';

export type HubModuleSection = 'home' | 'apps' | 'channel' | 'knowledge';

export interface HubModuleLink {
  section: HubModuleSection;
  to: string;
  icon: ComponentType<{ className?: string }>;
  label: string;
  isActive: boolean;
  /** When true, callers may close the drawer after navigation (e.g. home / apps from knowledge drawer). */
  closeDrawerOnNavigate?: boolean;
}

/** Shared row styles: matches MainLayout narrow SidebarItem (p-3, rounded-lg, #e6edfc). */
const hubNavItemClassName = (navActive: boolean, routeActive: boolean, equalWidth: boolean) =>
  cn(
    'flex cursor-pointer items-center justify-center rounded-lg p-3 transition-colors hover:bg-[#e6edfc]',
    equalWidth && 'min-w-0 flex-1',
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
  const showSubscriptionTab = plugins ? plugins.includes('subscription') : true;
  const showKnowledgeSpaceTab = plugins ? plugins.includes('knowledge_space') : true;

  return useMemo(
    () =>
      [
        {
          section: 'home',
          to: lastSectionPaths.home || '/c/new',
          icon: HomeIcon,
          label: localize('com_nav_home'),
          isActive: /^\/(c|linsight)(\/|$)/.test(pathname),
          closeDrawerOnNavigate: true,
        },
        {
          section: 'apps',
          to: appsSectionLinkTarget(),
          icon: GlobeIcon,
          label: localize('com_nav_app_center'),
          isActive:
            matchPath('/app/:id/:fid/:type', pathname) !== null || pathname.startsWith('/apps'),
          closeDrawerOnNavigate: true,
        },
        {
          section: 'channel',
          to: lastSectionPaths.channel || '/channel',
          icon: LinkIcon,
          label: localize('com_ui_channel'),
          isActive: pathname.startsWith('/channel'),
        },
        {
          section: 'knowledge',
          to: lastSectionPaths.knowledge || '/knowledge',
          icon: BookOpenIcon,
          label: localize('com_knowledge.knowledge_space'),
          isActive: pathname.startsWith('/knowledge'),
        },
      ].filter((link) => {
        if (link.section === 'channel') return showSubscriptionTab;
        if (link.section === 'knowledge') return showKnowledgeSpaceTab;
        return true;
      }),
    [localize, pathname, showKnowledgeSpaceTab, showSubscriptionTab],
  );
}

interface HubModuleNavTabsProps {
  /** Equal-width cells (e.g. app chat sidebar); default is compact centered icons like H5 drawers. */
  equalWidth?: boolean;
  onLinkClick?: (link: HubModuleLink) => void;
  className?: string;
}

export function HubModuleNavTabs({ equalWidth = false, onLinkClick, className }: HubModuleNavTabsProps) {
  const links = useHubModuleLinks();

  return (
    <div
      className={cn(
        'flex shrink-0 gap-2 border-b border-[#e5e6eb] px-2 py-2',
        equalWidth && 'w-full min-w-0',
        equalWidth ? 'items-stretch' : 'items-center justify-center',
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
              hubNavItemClassName(navActive, link.isActive, equalWidth)
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
