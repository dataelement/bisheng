import Cookies from 'js-cookie';
import { getBysConfigApi } from '~/api/apps';
import BookOpenIcon from '~/components/ui/icon/BookOpen';
import GlobeIcon from '~/components/ui/icon/Globe';
import HomeIcon from '~/components/ui/icon/Home';
import LinkIcon from '~/components/ui/icon/Link';
import MonitorIcon from '~/components/ui/icon/Monitor';
import React, { useCallback, useEffect, useMemo } from 'react';
import KeepAlive from 'react-activation';
import { matchPath, NavLink, useLocation, useOutlet } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { bishengConfState } from '~/pages/appChat/store/atoms';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { useAuthContext, useLocalize, useScrollbarWhileScrolling } from '~/hooks';
import store from '~/store';
import { cn } from '~/utils';
import { UserPopMenu } from './UserPopMenu';

// Module-level storage for the last visited path per sidebar section.
// Updated synchronously during MainLayout's render so that Sidebar
// always reads the latest value in the same render cycle.
const lastSectionPaths: Record<string, string> = {};

interface SidebarItemProps {
  icon: React.ReactNode;
  to: string;
  active: boolean; // 改为手动传入 active 状态
}

function SidebarItem({ icon, to, active }: SidebarItemProps) {
  return (
    <NavLink
      to={to}
      className={cn(
        "flex items-center justify-center p-3 rounded-lg cursor-pointer transition-colors hover:bg-[#e6edfc]",
        active && "bg-[#e6edfc]"
      )}
    >
      {React.cloneElement(icon as React.ReactElement, {
        className: cn("size-5", active ? "text-[#335CFF]" : "text-[#818181]"),
      })}
    </NavLink>
  );
}

function Sidebar() {
  const { pathname } = useLocation();
  const { data: bsConfig } = useGetBsConfig();
  const { user, logout } = useAuthContext();
  const localize = useLocalize();
  const [langcode, setLangcode] = useRecoilState(store.lang);

  // Backend returns `web_menu` but we map it into front-end user as `plugins`.
  const plugins: string[] | null = Array.isArray((user as any)?.plugins)
    ? ((user as any)?.plugins as string[])
    : null;
  const showSubscriptionTab = plugins ? plugins.includes("subscription") : true;
  const showKnowledgeSpaceTab = plugins ? plugins.includes("knowledge_space") : true;

  // --- Sidebar link definitions with dynamic `to` for KeepAlive restoration ---
  const links = useMemo(() => [
    {
      section: 'home',
      to: lastSectionPaths.home || '/c/new',
      icon: <HomeIcon />,
      isActive: /^\/(c|linsight)(\/|$)/.test(pathname),
    },
    {
      section: 'apps',
      to: lastSectionPaths.apps || '/apps',
      icon: <GlobeIcon />,
      isActive: matchPath('/app/:id/:fid/:type', pathname) !== null || pathname.startsWith('/apps'),
    },
    {
      section: 'channel',
      to: lastSectionPaths.channel || '/channel',
      icon: <LinkIcon />,
      isActive: pathname.startsWith('/channel'),
    },
    {
      section: 'knowledge',
      to: lastSectionPaths.knowledge || '/knowledge',
      icon: <BookOpenIcon />,
      isActive: pathname.startsWith('/knowledge'),
    },
  ].filter((l) => {
    if (l.section === 'channel') return showSubscriptionTab;
    if (l.section === 'knowledge') return showKnowledgeSpaceTab;
    return true;
  }), [pathname, showSubscriptionTab, showKnowledgeSpaceTab]);

  const changeLang = useCallback((value: string) => {
    let userLang = value;
    if (value === 'auto') userLang = navigator.language || navigator.languages[0];
    setLangcode(userLang);
    Cookies.set('lang', userLang, { expires: 365 });
  }, [setLangcode]);

  const displayName = user?.name ?? user?.username ?? localize('com_nav_user');

  return (
    <div className="w-16 h-screen flex flex-col items-center justify-between py-4 px-2 shrink-0">
      <div className="flex flex-col gap-10 items-center">
        <div className="size-10 relative">
          <img src={__APP_ENV__.BASE_URL + bsConfig?.sidebarIcon.image} className="size-full" alt="logo" />
        </div>

        <div className="flex flex-col gap-4 items-center">
          {links.map(link => (
            <SidebarItem
              key={link.section}
              to={link.to}
              icon={link.icon}
              active={link.isActive}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-4 items-center">
        {user?.plugins?.includes('backend') && (
          <a href={__APP_ENV__.BISHENG_HOST} target='_blank' rel="noreferrer">
            <div title={localize('com_nav_admin_panel')} className="p-3 rounded-lg hover:bg-[#e6edfc] transition-colors">
              <MonitorIcon className="size-5 text-[#818181]" />
            </div>
          </a>
        )}
        <div className="w-full h-px bg-[#ececec]" />

        {/* 用户下拉菜单 */}
        <UserPopMenu />
      </div>
    </div>
  );
}

export default function MainLayout() {
  const { pathname } = useLocation();
  const outlet = useOutlet();
  const { user, logout, isUserLoading } = useAuthContext();
  const { onScroll: onOutletScroll, scrollingProps: outletScrollingProps } = useScrollbarWhileScrolling();

  // Auth guard: redirect to login when user query finishes without a valid user.
  // The 401 interceptor in request.ts already handles production redirect,
  // but this serves as a definitive guard for all environments.
  useEffect(() => {
    if (!isUserLoading && !user) {
      logout();
    }
  }, [isUserLoading, user, logout]);

  // Load env config once on mount — makes bishengConfState available to all pages
  const [, setConfig] = useRecoilState(bishengConfState);
  useEffect(() => {
    getBysConfigApi().then(res => {
      setConfig(res.data);
    });
  }, []);

  // Don't render any page content until the user is authenticated.
  // This prevents the flash of empty-state pages for unauthenticated visitors.
  if (!user) {
    return null;
  }

  // Track last visited path per sidebar section.
  // Runs synchronously before Sidebar renders in the same cycle.
  if (/^\/(c|linsight)(\/|$)/.test(pathname)) lastSectionPaths.home = pathname;
  else if (/^\/(apps|app)(\/|$)/.test(pathname)) lastSectionPaths.apps = pathname;
  else if (/^\/channel(\/|$)/.test(pathname)) lastSectionPaths.channel = pathname;
  else if (pathname.startsWith('/knowledge')) lastSectionPaths.knowledge = pathname;

  // Each sidebar tab gets its own KeepAlive cache key so switching
  // between tabs triggers cache/restore instead of re-rendering.
  const cacheKey = (() => {
    if (/^\/(c|linsight)(\/|$)/.test(pathname)) return 'chat_tab';
    if (/^\/(apps|app)(\/|$)/.test(pathname)) return 'apps_tab';
    if (/^\/channel(\/|$)/.test(pathname)) return 'channel_tab';
    if (pathname.startsWith('/knowledge')) return 'knowledge_tab';
    return 'other';
  })();

  return (
    <div className="flex bg-[#F9F9F9] overflow-hidden w-screen">
      <Sidebar />
      <main className="flex-1 h-screen relative p-2 pl-0 min-w-0">
        <KeepAlive
          name={cacheKey}
          id={cacheKey}
          saveScroll={true}
        >
          <div
            className="h-[calc(100vh-16px)] overflow-y-auto scroll-on-scroll rounded-xl bg-white shadow-xl"
            onScroll={onOutletScroll}
            {...outletScrollingProps}
          >
            {outlet}
          </div>
        </KeepAlive>
      </main>
    </div>
  );
}