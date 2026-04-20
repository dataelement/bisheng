import Cookies from 'js-cookie';
import { getBysConfigApi } from '~/api/apps';
import BookOpenIcon from '~/components/ui/icon/BookOpen';
import GlobeIcon from '~/components/ui/icon/Globe';
import HomeIcon from '~/components/ui/icon/Home';
import LinkIcon from '~/components/ui/icon/Link';
import MonitorIcon from '~/components/ui/icon/Monitor';
import { Menu, X } from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import KeepAlive from 'react-activation';
import { matchPath, NavLink, useLocation, useOutlet } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { usePrefersMobileLayout } from '~/hooks';
import { bishengConfState } from '~/pages/appChat/store/atoms';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { useAuthContext, useLocalize } from '~/hooks';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import store from '~/store';
import { cn } from '~/utils';
import { UserPopMenu } from './UserPopMenu';
import { appsSectionLinkTarget, lastSectionPaths } from './appModuleNavPaths';

interface SidebarItemProps {
  icon: React.ReactNode;
  to: string;
  active: boolean;
  label: string;
  showLabel?: boolean;
}

function SidebarItem({ icon, to, active, label, showLabel = false }: SidebarItemProps) {
  return (
    <Tooltip delayDuration={0}>
      <TooltipTrigger asChild>
        <NavLink
          to={to}
          className={cn(
            'flex cursor-pointer rounded-lg transition-colors',
            showLabel
              ? 'h-[44px] items-center justify-start gap-2 px-3 py-3 hover:bg-[#f2f3f5]'
              : 'items-center justify-center p-3 hover:bg-[#e6edfc]',
            active && "bg-[#e6edfc]"
          )}
        >
          {React.cloneElement(icon as React.ReactElement, {
            className: cn(showLabel ? 'size-4' : 'size-5', active ? "text-[#335CFF]" : "text-[#818181]"),
          })}
          {showLabel ? (
            <span className={cn('text-[14px] leading-[20px]', active ? 'text-[#335CFF]' : 'text-[#212121]')}>
              {label}
            </span>
          ) : null}
        </NavLink>
      </TooltipTrigger>
      {!showLabel ? (
        <TooltipContent side="right" sideOffset={8}>
          {label}
        </TooltipContent>
      ) : null}
    </Tooltip>
  );
}

function Sidebar({
  mobileSidebarOpen,
  onCloseMobileApps,
  overlay = false,
}: {
  mobileSidebarOpen: boolean;
  onCloseMobileApps?: () => void;
  /** 移动端应用中心抽屉：置于遮罩层内时用全宽撑满面板，避免与 flex 并排挤压主区域 */
  overlay?: boolean;
}) {
  const { pathname } = useLocation();
  const { data: bsConfig } = useGetBsConfig();
  const { user, logout } = useAuthContext();
  const localize = useLocalize();
  const [langcode, setLangcode] = useRecoilState(store.lang);
  const isMobile = usePrefersMobileLayout();
  const isChatSection = /^\/(c|linsight)(\/|$)/.test(pathname);
  // Use includes() to tolerate possible basename prefix (e.g. "/xxx/apps")
  const isAppSection = pathname.includes('/apps') || pathname.includes('/app/');
  /** 移动端仅在应用相关抽屉内展开主导航文案；订阅 /channel 走窄栏 w-16，避免与订阅内频道抽屉重复「菜单」 */
  const showExpandedHubSidebar = isMobile && isAppSection;

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
      label: localize('com_nav_home'),
      isActive: /^\/(c|linsight)(\/|$)/.test(pathname),
    },
    {
      section: 'apps',
      to: appsSectionLinkTarget(),
      icon: <GlobeIcon />,
      label: localize('com_nav_app_center'),
      isActive: matchPath('/app/:id/:fid/:type', pathname) !== null || pathname.startsWith('/apps'),
    },
    {
      section: 'channel',
      to: lastSectionPaths.channel || '/channel',
      icon: <LinkIcon />,
      label: localize('com_ui_channel'),
      isActive: pathname.startsWith('/channel'),
    },
    {
      section: 'knowledge',
      to: lastSectionPaths.knowledge || '/knowledge',
      icon: <BookOpenIcon />,
      label: localize('com_knowledge.knowledge_space'),
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

  return (
    <div
      className={cn(
        showExpandedHubSidebar ? (overlay ? 'w-full px-2' : 'w-[38vw] px-2') : 'w-16 px-2',
        'h-screen flex flex-col justify-between py-2 shrink-0 bg-white',
        !overlay && 'border-r border-[#ececec]',
        // 主站会话移动端：不展示左侧窄栏，入口在会话区顶栏与历史抽屉内
        // 应用会话 /app/* 仍显示左侧模块栏，与 PC 一致，便于切换首页 / 应用 / 频道 / 知识
        isChatSection && isMobile && 'hidden',
      )}
    >
      <div className={cn('flex flex-col', showExpandedHubSidebar ? 'gap-4 items-stretch' : 'gap-10 items-center')}>
        <div className={cn('relative shrink-0', showExpandedHubSidebar ? 'flex items-center justify-between p-2' : 'size-10 flex items-center justify-center')}>
          {bsConfig?.sidebarIcon?.image ? (
            <img
              src={__APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image}
              className={cn(showExpandedHubSidebar ? 'size-8 object-contain' : 'size-full object-contain')}
              alt=""
            />
          ) : null}
          {showExpandedHubSidebar && onCloseMobileApps ? (
            <button
              type="button"
              onClick={onCloseMobileApps}
              aria-label={localize('com_nav_close_sidebar')}
              className="inline-flex size-8 items-center justify-center rounded-md text-[#4E5969] hover:bg-[#F7F8FA]"
            >
              <X className="size-4" />
            </button>
          ) : null}
        </div>

        <div className={cn('flex flex-col', showExpandedHubSidebar ? 'gap-1 items-stretch' : 'gap-4 items-center')}>
          {links.map(link => (
            <SidebarItem
              key={link.section}
              to={link.to}
              icon={link.icon}
              label={link.label}
              active={link.isActive}
              showLabel={showExpandedHubSidebar}
            />
          ))}
        </div>
      </div>

        <div className={cn('flex flex-col gap-4', showExpandedHubSidebar ? 'items-stretch px-2' : 'items-center')}>
        {user?.plugins?.includes('backend') && (
          <a href={__APP_ENV__.BISHENG_HOST} target='_blank' rel="noreferrer">
            <div title={localize('com_nav_admin_panel')} className="p-3 rounded-lg hover:bg-[#e6edfc] transition-colors">
              <MonitorIcon className="size-5 text-[#818181]" />
            </div>
          </a>
        )}
        <div className="w-full h-px bg-[#ececec]" />

        {/* 用户菜单：应用中心抽屉模式展示整行（含右箭头） */}
        <UserPopMenu variant={showExpandedHubSidebar ? 'drawer' : 'rail'} />
      </div>
    </div>
  );
}

export default function MainLayout() {
  const { pathname } = useLocation();
  const outlet = useOutlet();
  const { user, logout, isUserLoading } = useAuthContext();
  const localize = useLocalize();
  const isMobile = usePrefersMobileLayout();
  const isAppSection = pathname.includes('/apps') || pathname.includes('/app/');
  const isAppsArea = pathname.includes('/apps');
  const isAppChatRoute = /^\/app(\/|$)/.test(pathname);
  const isChannelRoute = /^\/channel(\/|$)/.test(pathname);
  const isKnowledgeRoute = /^\/knowledge(\/|$)/.test(pathname);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  // 移动端：应用会话、/apps、/channel、/knowledge 都隐藏 MainLayout 左栏。
  // /apps 保留本布局内菜单按钮；/channel、/knowledge 使用各自页面的抽屉入口。
  const shouldHideSidebarOnMobileAppsArea = isMobile && (isAppChatRoute || isAppsArea || isChannelRoute || isKnowledgeRoute);

  useEffect(() => {
    if (!isMobile || !isAppSection) return;
    try {
      localStorage.setItem('mobileAppSidebarOpen', JSON.stringify(mobileSidebarOpen));
    } catch {
      // ignore
    }
  }, [isMobile, isAppSection, mobileSidebarOpen]);

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
    getBysConfigApi().then((res: any) => {
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
  else if (/^\/(apps|app)(\/|$)/.test(pathname)) {
    // 应用广场是应用中心的子页；从其它模块再点「应用」时应回到应用中心，而非恢复广场路由
    lastSectionPaths.apps = pathname.startsWith('/apps/explore') ? '/apps' : pathname;
  } else if (/^\/channel(\/|$)/.test(pathname)) lastSectionPaths.channel = pathname;
  else if (pathname.startsWith('/knowledge')) lastSectionPaths.knowledge = pathname;

  // Each sidebar tab gets its own KeepAlive cache key so switching
  // between tabs triggers cache/restore instead of re-rendering.
  const cacheKey = (() => {
    if (/^\/linsight(\/|$)/.test(pathname)) return 'linsight_tab';
    if (/^\/c(\/|$)/.test(pathname)) return 'chat_tab';
    if (/^\/(apps|app)(\/|$)/.test(pathname)) return 'apps_tab';
    if (/^\/channel(\/|$)/.test(pathname)) return 'channel_tab';
    if (pathname.startsWith('/knowledge')) return 'knowledge_tab';
    return 'other';
  })();

  return (
    <div className="relative flex bg-[#F9F9F9] overflow-hidden w-screen">
      {shouldHideSidebarOnMobileAppsArea ? null : (
        <Sidebar
          mobileSidebarOpen={mobileSidebarOpen}
          onCloseMobileApps={() => setMobileSidebarOpen(false)}
        />
      )}
      {isMobile && isAppsArea && !isAppChatRoute && mobileSidebarOpen ? (
        <div
          className="fixed inset-0 z-[55] flex"
          role="dialog"
          aria-modal="true"
          aria-label={localize('com_nav_app_center')}
        >
          <div className="flex h-full w-[240px] max-w-[240px] shrink-0 flex-col overflow-hidden border-r border-[#ececec] bg-white shadow-[4px_0_24px_rgba(0,0,0,0.06)]">
            <Sidebar
              mobileSidebarOpen={mobileSidebarOpen}
              onCloseMobileApps={() => setMobileSidebarOpen(false)}
              overlay
            />
          </div>
          {/* 透明热区：右侧保持底层白底主区域原样，仅接收点击关闭 */}
          <button
            type="button"
            className="min-w-0 flex-1 bg-transparent"
            aria-label={localize('com_nav_close_sidebar')}
            onClick={() => setMobileSidebarOpen(false)}
          />
        </div>
      ) : null}
      <main className="flex-1 h-screen relative p-2 pl-0 min-w-0">
        {shouldHideSidebarOnMobileAppsArea && isAppsArea && !isAppChatRoute && !mobileSidebarOpen ? (
          <button
            type="button"
            aria-label={localize('com_nav_open_sidebar')}
            onClick={() => setMobileSidebarOpen(true)}
            className="absolute left-2 top-2 z-[50] inline-flex size-8 items-center justify-center rounded-md text-[#212121] hover:bg-[#F7F8FA]"
          >
            <Menu className="size-4" />
          </button>
        ) : null}
        <KeepAlive
          name={cacheKey}
          id={cacheKey}
          saveScroll={true}
        >
          <div
            className={cn(
              'h-[calc(100vh-16px)] overflow-y-auto overscroll-y-none scrollbar-on-hover rounded-xl bg-white shadow-xl',
              shouldHideSidebarOnMobileAppsArea &&
                isAppsArea &&
                !isAppChatRoute &&
                !mobileSidebarOpen &&
                'pt-9',
            )}
          >
            {outlet}
          </div>
        </KeepAlive>
      </main>
    </div>
  );
}