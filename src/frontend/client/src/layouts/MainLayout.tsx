import { DesktopShellBridge } from './DesktopShellBridge';
import { isDesktopEmbedded } from '~/components/Chat/desktopEmbedding';
import { getBysConfigApi } from '~/api/apps';
import { Outlined } from 'bisheng-icons';
import { X } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import KeepAlive from 'react-activation';
import { matchPath, Navigate, NavLink, useLocation, useOutlet } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { usePrefersMobileLayout, useScrollRevealRef } from '~/hooks';
import { bishengConfState } from '~/pages/appChat/store/atoms';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { useAuthContext, useLocalize, useWorkbenchMenuNames } from '~/hooks';
import { Button } from '~/components/ui/Button';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '~/components/ui/Dialog';
import store from '~/store';
import { useAgentToolPreferences } from '~/components/Chat/Input/AgentToolSelector';

const systemNoticeTodayKey = () => {
  const d = new Date();
  return `system_notice_shown_${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
};
import { cn } from '~/utils';
import { UserPopMenu } from './UserPopMenu';
import WorkbenchAccessGuard from './WorkbenchAccessGuard';
import { lastSectionPaths } from './appModuleNavPaths';
import { useWorkbenchNavLinks } from './useWorkbenchNavLinks';
import { WorkbenchSidebar } from './WorkbenchSidebar';

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
  const location = useLocation();
  // Re-navigating to the path we are already on is a no-op the user cannot see,
  // but react-router still mints a fresh location.key and every effect keyed on
  // it re-runs. The 首页 entry points at `lastSectionPaths.home`, which IS the
  // current `/c/<id>` while a chat is open — so an idle click used to churn chat
  // state for nothing. Swallow it here, the way Convo does for the conversation
  // list.
  const handleClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
    // Still fires on a same-path click: collapsing the H5 drawer is what the
    // user asked for, only the redundant navigation is dropped.
    onNavigate?.();
    if (to === location.pathname) {
      event.preventDefault();
    }
  };

  return (
    <NavLink
      to={to}
      onClick={handleClick}
      className={cn(
        'flex cursor-pointer rounded-lg transition-colors hover:bg-fill-2',
        showLabel
          ? 'mx-2 h-[44px] items-center justify-start gap-2 px-2 py-2'
          : 'w-14 flex-col items-center justify-center gap-0.5 py-2',
      )}
    >
      {React.cloneElement((active && activeIcon ? activeIcon : icon) as React.ReactElement, {
        className: cn(showLabel ? 'size-4' : 'size-5', active ? 'text-blue-500' : 'text-text-3'),
      })}
      {showLabel ? (
        <span className={cn('text-[14px] leading-[20px]', active ? 'text-blue-500' : 'text-text-1')}>
          {label}
        </span>
      ) : (
        <span
          className={cn(
            'max-w-full break-words text-center text-caption-sm',
            active ? 'font-medium text-blue-500' : 'text-text-3',
          )}
        >
          {label}
        </span>
      )}
    </NavLink>
  );
}

/** Mobile-only icon rail / apps drawer. Desktop renders WorkbenchSidebar instead. */
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
  const localize = useLocalize();
  const { links } = useWorkbenchNavLinks();
  const isMobile = usePrefersMobileLayout();
  // Use includes() to tolerate possible basename prefix (e.g. "/xxx/apps")
  const isAppSection = pathname.includes('/apps') || pathname.includes('/app/');
  /** 仅当作为 240px 应用中心抽屉(overlay=true)被挂载时,才把侧边栏展宽为带文字标签。
   *  移动端「系统菜单整页右滑」露出模式保持 w-16 窄栏(纯图标)。 */
  const showExpandedHubSidebar = isMobile && isAppSection && overlay;

  return (
    <div
      className={cn(
        showExpandedHubSidebar ? (overlay ? 'w-full' : 'w-[38vw]') : 'w-16',
        'dsh-system-sidebar h-[100dvh] flex flex-col justify-between py-4 px-2 shrink-0 bg-[rgb(227, 227, 227)]',
        // Rail: let the content column shrink to its 44px width instead of stretching the track.
        // Expanded drawer keeps the stretched full-width layout.
        showExpandedHubSidebar ? undefined : 'items-center',
        // Mobile chat 路由的 sidebar 显隐由 MainLayout 顶层条件渲染管理(systemMenuRevealing),
        // 这里不再硬加 hidden,否则 systemMenu 露出时 sidebar 也被隐掉。
      )}
    >
      <div className={cn('flex flex-col', showExpandedHubSidebar ? 'gap-4 items-stretch' : 'gap-10 items-center')}>
        <div className={cn('relative shrink-0', showExpandedHubSidebar ? 'flex items-center justify-between p-2' : 'size-11 flex items-center justify-center')}>
          {showExpandedHubSidebar ? (
            <>
              {bsConfig?.sidebarIcon?.image ? (
                <img
                  src={__APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image}
                  className="size-8 shrink-0 object-contain"
                  alt={localize('com_nav_home')}
                />
              ) : (
                <div className="size-8 shrink-0 rounded-md bg-fill-2" aria-hidden />
              )}
              {onCloseMobileApps ? (
                <button
                  type="button"
                  onClick={onCloseMobileApps}
                  aria-label={localize('com_nav_close_sidebar')}
                  className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-text-2 hover:bg-fill-1"
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
              activeIcon={link.activeIcon}
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

      <div className="flex flex-col items-center">
        {/* 用户菜单：应用中心抽屉模式展示整行（含右箭头） */}
        <UserPopMenu variant={showExpandedHubSidebar ? 'drawer' : 'rail'} />
      </div>
    </div>
  );
}

export default function MainLayout() {
  const { pathname, search } = useLocation();
  const outlet = useOutlet();
  useAgentToolPreferences();
  const { user, logout, isUserLoading } = useAuthContext();
  const localize = useLocalize();
  const menuNames = useWorkbenchMenuNames();
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
  const isSettingsRoute = /^\/settings(\/|$)/.test(pathname);
  const isKnowledgeSettingsRoute = Boolean(
    matchPath({ path: '/knowledge/create', end: true }, pathForMatch) ||
    matchPath({ path: '/knowledge/space/:spaceId/settings', end: true }, pathForMatch),
  );
  /** These full-height surfaces keep the white shell fixed and delegate scrolling to their page content. */
  const innerScrollShell =
    /^\/(c|linsight)(\/|$)/.test(pathname) ||
    isChannelRoute ||
    isKnowledgeSettingsRoute ||
    isAppChatRoute ||
    isSettingsRoute ||
    (isAppsArea && !isAppsExploreRoute);
  const isKnowledgeRoute = /^\/knowledge(\/|$)/.test(pathname);
  const showPlatformNavigation = !isDesktopEmbedded();
  const isChatHomeRoute = /^\/(c|linsight)(\/|$)/.test(pathname);
  const isMenuUnavailableRoute = pathname.startsWith('/menu-unavailable');
  const isSkillsRoute = /^\/skills(\/|$)/.test(pathname);
  const isSquareRoute = /^\/square(\/|$)/.test(pathname);
  const isCapabilitiesRoute = /^\/capabilities(\/|$)/.test(pathname);
  /** Pages that read their view from the query string: a page react-activation froze keeps
   *  its old router context, so they are mounted fresh instead of cached. */
  const isQueryDrivenRoute = isSkillsRoute || isSquareRoute || isCapabilitiesRoute;
  // Knowledge, channel pages and app conversations use the active router context,
  // including the selected list tab and the current detail route.
  const isLiveRoute = isQueryDrivenRoute || isKnowledgeRoute || isChannelRoute || isAppChatRoute;
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [systemMenuOpen, setSystemMenuOpen] = useRecoilState(store.mobileSystemMenuOpenState);
  // 移动端：所有主功能页(应用会话 / apps / channel / knowledge / 主站会话 / 无权限占位页)都隐藏
  // MainLayout 左栏,点页面内菜单按钮触发系统主菜单整页右滑露出。
  const shouldHideSidebarOnMobileAppsArea = isMobile && (isAppChatRoute || isAppsArea || isChannelRoute || isKnowledgeRoute || isChatHomeRoute || isMenuUnavailableRoute || isSettingsRoute || isQueryDrivenRoute);
  /** H5: 系统主菜单露出 — 子页面顶栏菜单触发,内容向右滑出 w-16,点击页面其它位置或导航即关闭 */
  const systemMenuRevealing = showPlatformNavigation && systemMenuOpen && isMobile && shouldHideSidebarOnMobileAppsArea;

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

  // Themed startup spinner while the user query is in flight — identical to the
  // platform app's LoadingIcon (same size/centering) so the platform→client
  // hand-off shows no size/position jump, instead of a blank flash.
  if (isUserLoading) {
    return (
      <div className="dsh-chat-startup flex h-full w-full items-center justify-center">
        <LoadingIcon className="w-48 text-primary" />
      </div>
    );
  }

  // Don't render any page content until the user is authenticated.
  // This prevents the flash of empty-state pages for unauthenticated visitors.
  if (!user) {
    return null;
  }

  // Legacy dialog deep links now land on the settings page. External notification cards
  // still point at `/?open-notifications=1&message-id=X` (backend _payload.py), and older
  // flows used `?open-settings=<section>` — both redirect instead of opening dialogs.
  if (!isSettingsRoute) {
    const legacyParams = new URLSearchParams(search);
    if (legacyParams.get('open-notifications') === '1') {
      return <Navigate to="/settings/notifications" replace />;
    }
    const legacySettingsSection = legacyParams.get('open-settings');
    if (legacySettingsSection) {
      return <Navigate to={`/settings/${legacySettingsSection === 'general' ? 'general' : 'account'}`} replace />;
    }
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
    if (pathname.startsWith('/menu-unavailable')) return 'menu_unavailable_tab';
    if (/^\/linsight(\/|$)/.test(pathname)) return 'linsight_tab';
    // Media playback lives under /c but is a page of its own, so it needs a key
    // of its own: sharing the chat key means opening a video replaces the cached
    // chat tree under that key, and coming back rebuilds the chat from scratch —
    // losing the attachments the user had staged but not yet sent.
    if (pathname.startsWith('/c/media-playback')) return 'media_playback_tab';
    if (/^\/c(\/|$)/.test(pathname)) return 'chat_tab';
    if (/^\/(apps|app)(\/|$)/.test(pathname)) return 'apps_tab';
    if (/^\/channel(\/|$)/.test(pathname)) return 'channel_tab';
    if (pathname.startsWith('/knowledge')) return 'knowledge_tab';
    if (isSettingsRoute) return 'settings_tab';
    return 'other';
  })();

  return (
    <div
      className={cn(
        'relative flex w-screen',
        (isChatHomeRoute || !showPlatformNavigation) && 'dsh-web-chat',
        // Desktop is a flat white page split by the sidebar's hairline (Figma 13139:111431);
        // mobile keeps the gray backdrop its sliding panels are drawn against.
        isMobile ? 'min-h-[100dvh] overflow-x-clip bg-fill-1' : 'h-[100dvh] overflow-hidden bg-white',
      )}
    >
      <DesktopShellBridge />
      <WorkbenchAccessGuard />
      {showPlatformNavigation && (shouldHideSidebarOnMobileAppsArea ? (
        systemMenuRevealing ? (
          <div className="absolute inset-y-0 left-0 z-30">
            <Sidebar
              mobileSidebarOpen={mobileSidebarOpen}
              onCloseMobileApps={() => setMobileSidebarOpen(false)}
            />
          </div>
        ) : null
      ) : isMobile ? (
        <Sidebar
          mobileSidebarOpen={mobileSidebarOpen}
          onCloseMobileApps={() => setMobileSidebarOpen(false)}
        />
      ) : (
        // On 设置 the page's own nav takes this slot (same width and chrome); its back
        // button brings the workbench sidebar back.
        <WorkbenchSidebar hidden={isSettingsRoute} />
      ))}
      {showPlatformNavigation && isMobile && isAppsArea && !isAppChatRoute && mobileSidebarOpen ? (
        <div
          className="fixed inset-0 z-[55] flex"
          role="dialog"
          aria-modal="true"
          aria-label={menuNames.apps}
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
          isMobile ? 'min-h-[100dvh]' : 'h-[100dvh]',
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
        {isMenuUnavailableRoute || isLiveRoute ? (
          // Route-driven pages consume the current router context directly.
          <div
            className={cn(
              'flex flex-col bg-white',
              isMobile && 'shadow-[0px_0px_20px_0px_#07225808]',
              // Match the main panel: when the left system menu is revealed, round
              // the exposed left edge and clip content to it (parity with KeepAlive branch).
              systemMenuRevealing && 'rounded-l-3xl',
              // Live route shells use page-owned scrolling, like the cached module homes.
              isLiveRoute
                ? 'h-[100dvh] min-h-0 overflow-hidden overscroll-y-none'
                : isMobile
                  ? 'h-auto min-h-[100dvh] overflow-visible'
                  : 'scrollbar-os h-[100dvh] overflow-y-auto overscroll-y-none',
              systemMenuRevealing && 'overflow-hidden',
            )}
          >
            {/* 移动端顶栏:无权限占位页本身没有汉堡入口,这里补一个,与会话/知识页一致,
                避免收起侧栏后用户无法唤出系统菜单。 */}
            {shouldHideSidebarOnMobileAppsArea && !isChannelRoute && !isAppChatRoute ? (
              <div className="sticky top-0 z-[50] w-full shrink-0 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
                <div className="relative flex h-11 min-h-11 w-full flex-row items-center justify-between px-4">
                  <button
                    type="button"
                    aria-label={localize('com_nav_open_sidebar')}
                    onClick={() => setSystemMenuOpen(true)}
                    className="inline-flex size-5 shrink-0 items-center justify-center text-text-1"
                  >
                    <Outlined.SidebarMenu className="size-5" />
                  </button>
                  {isQueryDrivenRoute ? (
                    <span className="pointer-events-none absolute left-1/2 -translate-x-1/2 truncate text-[16px] font-medium leading-6 text-text-1">
                      {localize(isSquareRoute ? 'com_workbench_sidebar.square' : isCapabilitiesRoute ? 'com_capability_center.title' : 'com_skill_center_title')}
                    </span>
                  ) : null}
                  <div className="min-w-0 flex-1" aria-hidden />
                </div>
              </div>
            ) : null}
            {isLiveRoute ? <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{outlet}</div> : outlet}
          </div>
        ) : (
        <KeepAlive
          name={cacheKey}
          id={cacheKey}
          saveScroll={true}
          // React 18 chat consumers stay live so cached navigation and streaming
          // state advance together when returning from a module.
          autoFreeze={cacheKey !== 'chat_tab'}
        >
          <div
            ref={!isMobile && !innerScrollShell ? outletScrollRevealRef : undefined}
            // Anchor + handle for panels that must cover the conversation while
            // leaving the rail alone — media playback is the one today. They
            // portal in here and lay themselves out against this box, so they
            // follow the panel's own geometry instead of guessing at the rail's
            // width.
            data-workbench-panel
            className={cn(
              'relative bg-white',
              isMobile && 'shadow-[0px_0px_20px_0px_#07225808]',
              // When the left system menu is revealed, the panel slides right and
              // exposes its left edge — round the left corners to 24px.
              systemMenuRevealing && 'rounded-l-3xl',
              isMobile
                ? innerScrollShell
                  ? 'flex h-[100dvh] min-h-0 w-full flex-col overflow-hidden'
                  : 'h-auto min-h-[100dvh] overflow-visible'
                : innerScrollShell
                  ? 'flex h-[100dvh] min-h-0 flex-col overflow-hidden overscroll-y-none'
                  : 'scrollbar-os h-[100dvh] overflow-y-auto overscroll-y-none',
              // While the system menu is revealed, clip content to the rounded corners so the
              // exposed left edge shows the radius (e.g. knowledge uses overflow-visible otherwise).
              systemMenuRevealing && 'overflow-hidden',
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
                <div className="relative flex h-11 min-h-11 w-full flex-row items-center justify-between px-4">
                  <button
                    type="button"
                    aria-label={localize('com_nav_open_sidebar')}
                    onClick={() => setSystemMenuOpen(true)}
                    className="inline-flex size-5 shrink-0 items-center justify-center text-text-1"
                  >
                    <Outlined.SidebarMenu className="size-5" />
                  </button>
                  {/* Centered title — same style as the chat / knowledge / subscription headers. */}
                  <span className="pointer-events-none absolute left-1/2 -translate-x-1/2 truncate text-[16px] font-medium leading-6 text-text-1">
                    {menuNames.apps}
                  </span>
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
        )}
      </main>
      <Dialog
        open={!!systemNotice}
        onOpenChange={(open) => {
          if (!open) closeSystemNotice();
        }}
      >
        <DialogContent className="sm:max-w-md w-[calc(100%-40px)] rounded-2xl mx-auto top-[50%] -translate-y-[50%]">
          <DialogHeader>
            <DialogTitle className="text-center text-lg font-medium">{localize('com_system_notice.title')}</DialogTitle>
          </DialogHeader>
          <div className="py-6 px-2">
            <div className="text-sm text-gray-700 leading-relaxed text-center whitespace-pre-wrap">
              {systemNotice}
            </div>
          </div>
          <DialogFooter className="sm:justify-center flex-row justify-center pb-2">
            <Button onClick={closeSystemNotice} className="w-[120px] rounded-full">
              {localize('com_auth.got_it')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
