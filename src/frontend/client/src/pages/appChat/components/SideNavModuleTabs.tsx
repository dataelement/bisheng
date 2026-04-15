import { useMemo } from 'react';
import { matchPath, NavLink, useLocation } from 'react-router-dom';
import BookOpenIcon from '~/components/ui/icon/BookOpen';
import GlobeIcon from '~/components/ui/icon/Globe';
import HomeIcon from '~/components/ui/icon/Home';
import LinkIcon from '~/components/ui/icon/Link';
import { useAuthContext, useLocalize } from '~/hooks';
import { appsSectionLinkTarget, lastSectionPaths } from '~/layouts/appModuleNavPaths';
import { cn } from '~/utils';

export function SideNavModuleTabs() {
  const { pathname } = useLocation();
  const localize = useLocalize();
  const { user } = useAuthContext();
  const plugins: string[] | null = Array.isArray((user as { plugins?: unknown })?.plugins)
    ? (user as { plugins: string[] }).plugins
    : null;
  const showSubscriptionTab = plugins ? plugins.includes('subscription') : true;
  const showKnowledgeSpaceTab = plugins ? plugins.includes('knowledge_space') : true;

  const links = useMemo(
    () =>
      [
        {
          section: 'home',
          to: lastSectionPaths.home || '/c/new',
          icon: HomeIcon,
          label: localize('com_nav_home'),
          isActive: /^\/(c|linsight)(\/|$)/.test(pathname),
        },
        {
          section: 'apps',
          to: appsSectionLinkTarget(),
          icon: GlobeIcon,
          label: localize('com_nav_app_center'),
          isActive: matchPath('/app/:id/:fid/:type', pathname) !== null || pathname.startsWith('/apps'),
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

  return (
    <div className="flex shrink-0 items-stretch gap-1 border-b border-[#e5e6eb] pb-2">
      {links.map((link) => {
        const Icon = link.icon;
        return (
          <NavLink
            key={link.section}
            to={link.to}
            title={link.label}
            className={cn(
              'flex min-w-0 flex-1 flex-col items-center justify-center rounded-[6px] py-1.5 transition-colors hover:bg-[#f2f3f5]',
              link.isActive && 'bg-[#e6edfc]',
            )}
          >
            <Icon className={cn('size-5 shrink-0', link.isActive ? 'text-[#335CFF]' : 'text-[#818181]')} />
          </NavLink>
        );
      })}
    </div>
  );
}
