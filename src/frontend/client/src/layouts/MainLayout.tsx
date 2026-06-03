import Cookies from 'js-cookie';
import { getBysConfigApi } from '~/api/apps';
import { Filled, Outlined } from 'bisheng-icons';
import { LayoutDashboard, X } from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import KeepAlive from 'react-activation';
import { matchPath, NavLink, useLocation, useOutlet } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { usePrefersMobileLayout, useScrollRevealRef } from '~/hooks';
import { bishengConfState } from '~/pages/appChat/store/atoms';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { useAuthContext, useLocalize } from '~/hooks';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import { Button } from '~/components/ui/Button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '~/components/ui/Dialog';
import store from '~/store';

const systemNoticeTodayKey = () => {
  const d = new Date();
  return `system_notice_shown_${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
};
import { cn } from '~/utils';
import { getPlatformAdminPanelUrl } from '~/utils/platformAdminUrl';
import { canOpenPlatformAdminPanel, canOpenWorkbench } from '~/utils/platformAccess';
import { UserPopMenu } from './UserPopMenu';
import WorkbenchAccessGuard from './WorkbenchAccessGuard';
import { appsSectionLinkTarget, lastSectionPaths } from './appModuleNavPaths';

interface SidebarItemProps {
  icon: React.ReactNode;
  /** Icon shown when active (e.g. the Filled variant); falls back to `icon` when omitted. */
  activeIcon?: React.ReactNode;
  to: string;
  active: boolean;
  label: string;
  showLabel?: boolean;
  /** H5 应用中心抽屉：切换首页 / 应用中心时收起面板 */
  onNavigate?: () => void;
}

function SidebarItem({ icon, activeIcon, to, active, label, showLabel = false, onNavigate }: SidebarItemProps) {
  return (
    <Tooltip delayDuration={0}>
      <TooltipTrigger asChild>
        <NavLink
          to={to}
          onClick={onNavigate}
          className={cn(
            'flex cursor-pointer rounded-lg transition-colors',
            showLabel
              ? 'mx-2 h-[44px] items-center justify-start gap-2 px-2 py-2 hover:bg-[#f2f3f5]'
              : 'items-center justify-center p-3 hover:bg-[#f2f3f5]',
          )}
        >
          {React.cloneElement((active && activeIcon ? activeIcon : icon) as React.ReactElement, {
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
  /** 仅当作为 240px 应用中心抽屉(overlay=true)被挂载时,才把侧边栏展宽为带文字标签。
   *  PC 默认和移动端「系统菜单整页右滑」露出模式都保持 w-16 窄栏(纯图标)。 */
  const showExpandedHubSidebar = isMobile && isAppSection && overlay;

  // Backend returns `web_menu` but we map it into front-end user as `plugins`.
  const plugins: string[] | null = Array.isArray((user as any)?.plugins)
    ? ((user as any)?.plugins as string[])
    : null;
  const canOpenPlatform = useMemo(
    () =>
      canOpenPlatformAdminPanel({
        role: user?.role,
        plugins,
        is_department_admin: (user as { is_department_admin?: boolean } | undefined)
          ?.is_department_admin,
      }),
    [plugins, user],
  );
  const canOpenWorkbenchEntry = useMemo(
    () =>
      !Array.isArray(plugins) ||
      canOpenWorkbench({
        role: user?.role,
        plugins,
        is_department_admin: (user as { is_department_admin?: boolean } | undefined)
          ?.is_department_admin,
      }),
    [plugins, user],
  );
  const menuApprovalMode = Boolean((user as { menu_approval_mode?: boolean })?.menu_approval_mode);
  const hasPlugin = (id: string) => (plugins ? plugins.includes(id) : true);
  const showWorkbenchItem = (id: string) => hasPlugin(id) || menuApprovalMode;
  const showSubscriptionTab = showWorkbenchItem('subscription');
  const showKnowledgeSpaceTab = showWorkbenchItem('knowledge_space');
  const showHomeTab = showWorkbenchItem('home');
  const showAppsTab = showWorkbenchItem('apps');

  const showAdminPanelShortcut =
    (user as { has_admin_console?: boolean } | null)?.has_admin_console
    ?? (
      user?.role === 'admin'
      || Boolean(plugins?.includes('backend') || plugins?.includes('admin'))
    );

  // 首钢门户专属入口：仅首钢部署（YAML 命名空间或 ConfigMap window 变量任一有值）+ 系统超管 + 桌面端才显示
  const portalAdminUrl =
    bsConfig?.shougang?.portal_admin_url
    ?? window.__SHOUGANG_PORTAL_ADMIN_URL__;
  const showShougangPortalTab =
    user?.role === 'admin' && !isMobile && Boolean(portalAdminUrl);

  // --- Sidebar link definitions with dynamic `to` for KeepAlive restoration ---
  const links = useMemo<Array<{
    section: 'home' | 'apps' | 'channel' | 'knowledge' | 'portal-admin';
    to: string;
    icon: React.ReactNode;
    label: string;
    isActive: boolean;
    closeDrawerOnNavigate?: boolean;
  }>>(() => {
    if (!canOpenWorkbenchEntry) return [];
    return [
      {
        section: 'home' as const,
        to: hasPlugin('home') || !menuApprovalMode ? (lastSectionPaths.home || '/c/new') : '/menu-unavailable',
        icon: <Outlined.Home />,
        activeIcon: <Filled.Home />,
        label: localize('com_nav_home'),
        isActive: /^\/(c|linsight)(\/|$)/.test(pathname),
        closeDrawerOnNavigate: true,
      },

      {
        section: 'knowledge' as const,
        // Mobile is list-page-first: the menu always opens the space list (/knowledge),
        // never the last-visited file page. Desktop keeps last-path restoration.
        to: hasPlugin('knowledge_space') || !menuApprovalMode
          ? (isMobile ? '/knowledge' : (lastSectionPaths.knowledge || '/knowledge'))
          : '/menu-unavailable',
        icon: <Outlined.Book />,
        activeIcon: <Filled.Book />,
        label: localize('com_knowledge.knowledge_space'),
        isActive: pathname.startsWith('/knowledge'),
        closeDrawerOnNavigate: true,
      },
      {
        section: 'channel' as const,
        to: hasPlugin('subscription') || !menuApprovalMode ? (lastSectionPaths.channel || '/channel') : '/menu-unavailable',
        icon: <Outlined.Rss />,
        activeIcon: <Filled.Rss />,
        label: localize('com_ui_channel'),
        isActive: pathname.startsWith('/channel'),
        closeDrawerOnNavigate: true,
      },
      {
        section: 'apps' as const,
        to: hasPlugin('apps') || !menuApprovalMode ? appsSectionLinkTarget() : '/menu-unavailable',
        icon: <Outlined.Application />,
        activeIcon: <Filled.Application />,
        label: localize('com_nav_app_center'),
        isActive: matchPath('/app/:id/:fid/:type', pathname) !== null || pathname.startsWith('/apps'),
        closeDrawerOnNavigate: true,
      },
      {
        section: 'portal-admin' as const,
        to: '/shougang-portal-admin',
        icon: <LayoutDashboard />,
        label: localize('com_nav_portal_admin'),
        isActive: pathname.startsWith('/shougang-portal-admin'),
        closeDrawerOnNavigate: true,
      },
    ].filter((l) => {
      if (l.section === 'home') return showHomeTab;
      if (l.section === 'apps') return showAppsTab;
      if (l.section === 'channel') return showSubscriptionTab;
      if (l.section === 'knowledge') return showKnowledgeSpaceTab;
      if (l.section === 'portal-admin') return showShougangPortalTab;
      return true;
    });
  }, [canOpenWorkbenchEntry, pathname, isMobile, showKnowledgeSpaceTab, showSubscriptionTab, showHomeTab, showAppsTab, showShougangPortalTab, menuApprovalMode, plugins, localize]);

  const changeLang = useCallback((value: string) => {
    let userLang = value;
    if (value === 'auto') userLang = navigator.language || navigator.languages[0];
    setLangcode(userLang);
    Cookies.set('lang', userLang, { expires: 365 });
  }, [setLangcode]);

  return (
    <div
      className={cn(
        showExpandedHubSidebar ? (overlay ? 'w-full' : 'w-[38vw]') : 'w-16',
        'h-[100dvh] flex flex-col justify-between py-2 pl-2 shrink-0 bg-[rgb(227, 227, 227)]',
        // Mobile chat 路由的 sidebar 显隐由 MainLayout 顶层条件渲染管理(systemMenuRevealing),
        // 这里不再硬加 hidden,否则 systemMenu 露出时 sidebar 也被隐掉。
      )}
    >
      <div className={cn('flex flex-col', showExpandedHubSidebar ? 'gap-4 items-stretch' : 'gap-10 items-center')}>
        <div className={cn('relative shrink-0', showExpandedHubSidebar ? 'flex items-center justify-between p-2' : 'size-10 flex items-center justify-center')}>
          {showExpandedHubSidebar ? (
            <>
              {bsConfig?.sidebarIcon?.image ? (
                <img
                  src={__APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image}
                  className="size-8 shrink-0 object-contain"
                  alt={localize('com_nav_home')}
                />
              ) : (
                <div className="size-8 shrink-0 rounded-md bg-[#F2F3F5]" aria-hidden />
              )}
              {onCloseMobileApps ? (
                <button
                  type="button"
                  onClick={onCloseMobileApps}
                  aria-label={localize('com_nav_close_sidebar')}
                  className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-[#4E5969] hover:bg-[#F7F8FA]"
                >
                  <X className="size-4" />
                </button>
              ) : null}
            </>
          ) : bsConfig?.sidebarIcon?.image ? (
            <img
              src={__APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image}
              className="size-full object-contain"
              alt=""
            />
          ) : null}
        </div>

        <div className={cn('flex flex-col', showExpandedHubSidebar ? 'gap-1 items-stretch' : 'gap-4 items-center')}>
          {links.map(link => (
            <SidebarItem
              key={link.section}
              to={link.to}
              icon={link.icon}
              activeIcon={(link as { activeIcon?: React.ReactNode }).activeIcon}
              label={link.label}
              active={link.isActive}
              showLabel={showExpandedHubSidebar}
              onNavigate={
                showExpandedHubSidebar && link.closeDrawerOnNavigate
                  ? onCloseMobileApps
                  : undefined
              }
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-4 items-center">
        {!isMobile && (canOpenPlatform || showAdminPanelShortcut) && (
          <a href={getPlatformAdminPanelUrl()} target="_blank" rel="noreferrer">
            <div
              title={localize('com_nav_admin_panel')}
              className="rounded-lg p-3 transition-colors hover:bg-[#f2f3f5]"
            >
              <Outlined.DeviceDesktopExchange className="size-5 text-[#818181]" />
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
  const outletScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
  const isAppSection = pathname.includes('/apps') || pathname.includes('/app/');
  const isAppsArea = pathname.includes('/apps');
  /** 探索广场：横幅内已有返回，隐藏主布局左上角汉堡，避免重复一行 */
  let pathForMatch = (pathname.split('?')[0] || '').replace(/\/+$/, '') || '/';
  const appBase =
    typeof __APP_ENV__ !== 'undefined' ? String(__APP_ENV__.BASE_URL || '').replace(/\/$/, '') : '';
  if (appBase && (pathForMatch === appBase || pathForMatch.startsWith(`${appBase}/`))) {
    pathForMatch = pathForMatch.slice(appBase.length) || '/';
  }
  const isAppsExploreRoute = Boolean(
    matchPath({ path: '/apps/explore', end: true }, pathForMatch),
  );
  const isAppChatRoute = /^\/app(\/|$)/.test(pathname);
  const isChannelRoute = /^\/channel(\/|$)/.test(pathname);
  /** 订阅 / 应用中心：白卡片不滚动，把高度交给页面内层（含移动端 ≤767 与桌面窄窗） */
  const innerScrollShell =
    isChannelRoute || (isAppsArea && !isAppChatRoute && !isAppsExploreRoute);
  const isKnowledgeRoute = /^\/knowledge(\/|$)/.test(pathname);
  const isChatHomeRoute = /^\/(c|linsight)(\/|$)/.test(pathname);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [systemMenuOpen, setSystemMenuOpen] = useRecoilState(store.mobileSystemMenuOpenState);
  // 移动端：所有主功能页(应用会话 / apps / channel / knowledge / 主站会话)都隐藏 MainLayout 左栏,
  // 点页面内菜单按钮触发系统主菜单整页右滑露出。
  const shouldHideSidebarOnMobileAppsArea = isMobile && (isAppChatRoute || isAppsArea || isChannelRoute || isKnowledgeRoute || isChatHomeRoute);
  /** H5: 系统主菜单露出 — 子页面顶栏菜单触发,内容向右滑出 w-16,点击页面其它位置或导航即关闭 */
  const systemMenuRevealing = systemMenuOpen && isMobile && shouldHideSidebarOnMobileAppsArea;

  // Route change auto-closes the revealed system menu (covers nav-link clicks).
  useEffect(() => {
    if (systemMenuOpen) setSystemMenuOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Leaving the mode where system-menu reveal is applicable also closes it.
  useEffect(() => {
    if (!isMobile || !shouldHideSidebarOnMobileAppsArea) {
      if (systemMenuOpen) setSystemMenuOpen(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile, shouldHideSidebarOnMobileAppsArea]);

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
  const [config, setConfig] = useRecoilState(bishengConfState);
  useEffect(() => {
    getBysConfigApi().then((res: any) => {
      setConfig(res.data);
    });
  }, []);

  // System notice popup — single instance above KeepAlive so dismissal is global.
  const remoteNotice = (config as { system_notification?: string } | undefined)?.system_notification ?? '';
  const [noticeDismissed, setNoticeDismissed] = useState(false);
  const hideNotice = noticeDismissed
    || (typeof window !== 'undefined' && !!sessionStorage.getItem(systemNoticeTodayKey()));
  const systemNotice = !hideNotice && remoteNotice ? remoteNotice : '';
  const closeSystemNotice = () => {
    try {
      sessionStorage.setItem(systemNoticeTodayKey(), 'true');
    } catch {
      // ignore storage failures
    }
    setNoticeDismissed(true);
  };

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
    <div
      className={cn(
        'relative flex w-screen bg-[#F8F8F8]',
        isMobile ? 'min-h-[100dvh] overflow-x-clip' : 'h-[100dvh] overflow-hidden',
      )}
    >
      <WorkbenchAccessGuard />
      {shouldHideSidebarOnMobileAppsArea ? (
        systemMenuRevealing ? (
          <div className="absolute inset-y-0 left-0 z-30">
            <Sidebar
              mobileSidebarOpen={mobileSidebarOpen}
              onCloseMobileApps={() => setMobileSidebarOpen(false)}
            />
          </div>
        ) : null
      ) : (
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
          <div className="flex h-full w-[240px] max-w-[240px] shrink-0 flex-col overflow-hidden bg-white shadow-[4px_0_24px_rgba(0,0,0,0.06)]">
            <Sidebar
              mobileSidebarOpen={mobileSidebarOpen}
              onCloseMobileApps={() => setMobileSidebarOpen(false)}
              overlay
            />
          </div>
          {/* 右侧蒙层：与首页侧边抽屉保持一致 */}
          <button
            type="button"
            className="min-w-0 flex-1 bg-[rgba(86,88,105,0.55)]"
            aria-label={localize('com_nav_close_sidebar')}
            onClick={() => setMobileSidebarOpen(false)}
          />
        </div>
      ) : null}
      <main
        className={cn(
          'relative min-w-0 flex-1',
          isMobile ? 'min-h-[100dvh]' : 'h-[100dvh] p-2',
          shouldHideSidebarOnMobileAppsArea && 'transition-transform duration-300 ease-out',
          systemMenuRevealing && 'translate-x-16',
        )}
      >
        {systemMenuRevealing ? (
          <button
            type="button"
            aria-label={localize('com_nav_close_sidebar')}
            onClick={() => setSystemMenuOpen(false)}
            className="absolute inset-0 z-[60] cursor-default bg-transparent"
          />
        ) : null}
        <KeepAlive
          name={cacheKey}
          id={cacheKey}
          saveScroll={true}
        >
          <div
            ref={!isMobile && !innerScrollShell ? outletScrollRevealRef : undefined}
            className={cn(
              'bg-white shadow-[0px_0px_20px_0px_#07225808]',
              (!isMobile || systemMenuRevealing) && 'rounded-xl',
              isMobile
                ? innerScrollShell
                  ? 'flex h-[100dvh] min-h-0 w-full flex-col overflow-hidden'
                  : 'h-auto min-h-[100dvh] overflow-visible'
                : innerScrollShell
                  ? 'flex h-[calc(100dvh-16px)] min-h-0 flex-col overflow-hidden overscroll-y-none'
                  : 'h-[calc(100dvh-16px)] overflow-y-auto overscroll-y-none',
            )}
          >
            {/* 移动端应用中心顶栏：与频道页一致 — 菜单按钮触发系统主菜单(整页右滑) */}
            {shouldHideSidebarOnMobileAppsArea &&
              isAppsArea &&
              !isAppChatRoute &&
              !isAppsExploreRoute ? (
              <div
                className="sticky top-0 z-[50] w-full shrink-0 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]"
              >
                <div className="flex h-11 min-h-11 w-full flex-row items-center justify-between px-4">
                  <button
                    type="button"
                    aria-label={localize('com_nav_open_sidebar')}
                    onClick={() => setSystemMenuOpen(true)}
                    className="inline-flex size-5 shrink-0 items-center justify-center text-[#212121]"
                  >
                    <Outlined.SidebarMenu className="size-5" />
                  </button>
                  <div className="min-w-0 flex-1" aria-hidden />
                </div>
              </div>
            ) : null}
            {innerScrollShell ? (
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                {outlet}
              </div>
            ) : (
              outlet
            )}
          </div>
        </KeepAlive>
      </main>
      <Dialog
        open={!!systemNotice}
        onOpenChange={(open) => {
          if (!open) closeSystemNotice();
        }}
      >
        <DialogContent className="sm:max-w-md w-[calc(100%-40px)] rounded-2xl mx-auto top-[50%] -translate-y-[50%]">
          <DialogHeader>
            <DialogTitle className="text-center text-lg font-medium">系统通知</DialogTitle>
          </DialogHeader>
          <div className="py-6 px-2">
            <div className="text-sm text-gray-700 leading-relaxed text-center whitespace-pre-wrap">
              {systemNotice}
            </div>
          </div>
          <DialogFooter className="sm:justify-center flex-row justify-center pb-2">
            <Button onClick={closeSystemNotice} className="w-[120px] rounded-full">
              我知道了
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
