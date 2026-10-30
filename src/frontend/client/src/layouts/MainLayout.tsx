import { DesktopShellBridge } from "./DesktopShellBridge";
import { isDesktopEmbedded } from "~/components/Chat/desktopEmbedding";
import { getBysConfigApi } from "~/api/apps";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState } from "react";
import KeepAlive from "react-activation";
import { matchPath, Navigate, useLocation, useOutlet } from "react-router-dom";
import { useRecoilState } from "recoil";
import { usePrefersMobileLayout, useScrollRevealRef } from "~/hooks";
import { bishengConfState } from "~/pages/appChat/store/atoms";
import { useAuthContext, useLocalize, useWorkbenchMenuNames } from "~/hooks";
import { Button } from "~/components/ui/Button";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui/Dialog";
import store from "~/store";
import { useAgentToolPreferences } from "~/components/Chat/Input/AgentToolSelector";

const systemNoticeTodayKey = () => {
  const d = new Date();
  return `system_notice_shown_${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
};
import { cn } from "~/utils";
import WorkbenchAccessGuard from "./WorkbenchAccessGuard";
import { lastSectionPaths } from "./appModuleNavPaths";
import { WorkbenchSidebar } from "./WorkbenchSidebar";

export default function MainLayout() {
  const { pathname, search } = useLocation();
  const outlet = useOutlet();
  useAgentToolPreferences();
  const { user, logout, isUserLoading } = useAuthContext();
  const localize = useLocalize();
  const menuNames = useWorkbenchMenuNames();
  const isMobile = usePrefersMobileLayout();
  const outletScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
  const isAppsArea = pathname.includes("/apps");
  /** 探索广场：横幅内已有返回，隐藏主布局左上角汉堡，避免重复一行 */
  let pathForMatch = (pathname.split("?")[0] || "").replace(/\/+$/, "") || "/";
  const appBase =
    typeof __APP_ENV__ !== "undefined" ? String(__APP_ENV__.BASE_URL || "").replace(/\/$/, "") : "";
  if (appBase && (pathForMatch === appBase || pathForMatch.startsWith(`${appBase}/`))) {
    pathForMatch = pathForMatch.slice(appBase.length) || "/";
  }
  const isAppsExploreRoute = Boolean(matchPath({ path: "/apps/explore", end: true }, pathForMatch));
  const isAppChatRoute = /^\/app(\/|$)/.test(pathname);
  const isChannelRoute = /^\/channel(\/|$)/.test(pathname);
  const isSettingsRoute = /^\/settings(\/|$)/.test(pathname);
  const isKnowledgeSettingsRoute = Boolean(
    matchPath({ path: "/knowledge/create", end: true }, pathForMatch) ||
    matchPath({ path: "/knowledge/space/:spaceId/settings", end: true }, pathForMatch),
  );
  /** These full-height surfaces keep the white shell fixed and delegate scrolling to their page content. */
  const innerScrollShell =
    /^\/(c|linsight)(\/|$)/.test(pathname) ||
    isChannelRoute ||
    isKnowledgeSettingsRoute ||
    isAppChatRoute ||
    isSettingsRoute ||
    (isAppsArea && !isAppsExploreRoute);
  const showPlatformNavigation = !isDesktopEmbedded();
  const isChatHomeRoute = /^\/(c|linsight)(\/|$)/.test(pathname);
  const isMenuUnavailableRoute = pathname.startsWith("/menu-unavailable");
  const isSkillsRoute = /^\/skills(\/|$)/.test(pathname);
  const isSquareRoute = /^\/square(\/|$)/.test(pathname);
  const isCapabilitiesRoute = /^\/capabilities(\/|$)/.test(pathname);
  /** Pages that read their view from the query string: a page react-activation froze keeps
   *  its old router context, so they are mounted fresh instead of cached. */
  const isQueryDrivenRoute = isSkillsRoute || isSquareRoute || isCapabilitiesRoute;
  // Channel pages and app conversations use the active router context, including
  // the current conversation and its entry surface when returning from discovery.
  const isLiveRoute = isQueryDrivenRoute || isChannelRoute || isAppChatRoute;
  const [systemMenuOpen, setSystemMenuOpen] = useRecoilState(store.mobileSystemMenuOpenState);
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const menuTriggerRef = useRef<HTMLElement | null>(null);
  const openSidebarLabel = localize('com_nav_open_sidebar');
  const shouldHideSidebarOnMobileAppsArea = isMobile && showPlatformNavigation;
  const systemMenuRevealing = shouldHideSidebarOnMobileAppsArea && systemMenuOpen;

  useEffect(() => {
    const root = layoutRef.current;
    if (!root || !isMobile) return;
    // KeepAlive renders cached pages outside this React event ancestry, but their
    // DOM remains inside the layout. Capture before Radix moves keyboard focus.
    const handleMenuTrigger = (event: Event) => {
      const target = event.target instanceof Element ? event.target.closest('button') : null;
      if (target?.getAttribute('aria-label') === openSidebarLabel) menuTriggerRef.current = target;
    };
    root.addEventListener('click', handleMenuTrigger, true);
    return () => root.removeEventListener('click', handleMenuTrigger, true);
  }, [isMobile, isUserLoading, user, pathname, search, openSidebarLabel]);

  useEffect(() => {
    setSystemMenuOpen(false);
    // The router owns dismissal after navigation, including query-driven pages.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, search]);

  useEffect(() => {
    if (!isMobile || !showPlatformNavigation) {
      menuTriggerRef.current = null;
      setSystemMenuOpen(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile, showPlatformNavigation]);

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
  const remoteNotice = (config as { system_notification?: string } | undefined)?.system_notification ?? "";
  const [noticeDismissed, setNoticeDismissed] = useState(false);
  const hideNotice =
    noticeDismissed || (typeof window !== "undefined" && !!sessionStorage.getItem(systemNoticeTodayKey()));
  const systemNotice = !hideNotice && remoteNotice ? remoteNotice : "";
  const closeSystemNotice = () => {
    try {
      sessionStorage.setItem(systemNoticeTodayKey(), "true");
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
    if (legacyParams.get("open-notifications") === "1") {
      return <Navigate to="/settings/notifications" replace />;
    }
    const legacySettingsSection = legacyParams.get("open-settings");
    if (legacySettingsSection) {
      return (
        <Navigate to={`/settings/${legacySettingsSection === "general" ? "general" : "account"}`} replace />
      );
    }
  }

  // Track last visited path per sidebar section.
  // Runs synchronously before Sidebar renders in the same cycle.
  if (/^\/(c|linsight)(\/|$)/.test(pathname) && pathname !== "/c/skills") lastSectionPaths.home = pathname;
  else if (/^\/(apps|app)(\/|$)/.test(pathname)) {
    // 应用广场是应用中心的子页；从其它模块再点「应用」时应回到应用中心，而非恢复广场路由
    lastSectionPaths.apps = pathname.startsWith("/apps/explore") ? "/apps" : pathname;
  } else if (/^\/channel(\/|$)/.test(pathname)) lastSectionPaths.channel = pathname;
  else if (pathname.startsWith("/knowledge")) lastSectionPaths.knowledge = pathname;

  // Each sidebar tab gets its own KeepAlive cache key so switching
  // between tabs triggers cache/restore instead of re-rendering.
  const cacheKey = (() => {
    if (pathname.startsWith("/menu-unavailable")) return "menu_unavailable_tab";
    if (/^\/linsight(\/|$)/.test(pathname)) return "linsight_tab";
    // Media playback lives under /c but is a page of its own, so it needs a key
    // of its own: sharing the chat key means opening a video replaces the cached
    // chat tree under that key, and coming back rebuilds the chat from scratch —
    // losing the attachments the user had staged but not yet sent.
    if (pathname.startsWith("/c/media-playback")) return "media_playback_tab";
    if (/^\/c(\/|$)/.test(pathname)) return "chat_tab";
    if (/^\/(apps|app)(\/|$)/.test(pathname)) return "apps_tab";
    if (/^\/channel(\/|$)/.test(pathname)) return "channel_tab";
    if (pathname.startsWith("/knowledge")) return "knowledge_tab";
    if (isSettingsRoute) return "settings_tab";
    return "other";
  })();

  return (
    <div
      ref={layoutRef}
      className={cn(
        "relative isolate flex w-screen",
        isMobile && "workbench-mobile-shell",
        (isChatHomeRoute || !showPlatformNavigation) && "dsh-web-chat",
        // Match the sidebar surface behind the mobile panel's exposed rounded corners.
        // Desktop remains a flat white page split by the sidebar's hairline (Figma 13139:111431).
        isMobile ? "min-h-[100dvh] overflow-x-clip bg-white" : "h-[100dvh] overflow-hidden bg-white",
      )}
    >
      <DesktopShellBridge />
      <WorkbenchAccessGuard />
      {showPlatformNavigation && (
        <WorkbenchSidebar
          hidden={!isMobile && isSettingsRoute}
          mobile={isMobile}
          open={systemMenuRevealing}
          onOpenChange={setSystemMenuOpen}
          triggerRef={menuTriggerRef}
        />
      )}
      <main
        className={cn(
          "relative min-w-0 flex-1",
          isMobile && "z-10 w-full bg-white shadow-[0px_0px_20px_0px_#07225808]",
          isMobile ? "min-h-[100dvh]" : "h-[100dvh]",
          shouldHideSidebarOnMobileAppsArea && "transition-transform duration-300 ease-out motion-reduce:transition-none",
          systemMenuRevealing && "translate-x-[240px] rounded-l-3xl overflow-hidden",
        )}
      >
        {isMenuUnavailableRoute || isLiveRoute ? (
          // Route-driven pages consume the current router context directly.
          <div
            className={cn(
              "flex flex-col bg-white",
              // Live route shells use page-owned scrolling, like the cached module homes.
              isLiveRoute
                ? "h-[100dvh] min-h-0 overflow-hidden overscroll-y-none"
                : isMobile
                  ? "h-auto min-h-[100dvh] overflow-visible"
                  : "scrollbar-os h-[100dvh] overflow-y-auto overscroll-y-none",
              systemMenuRevealing && "overflow-hidden",
            )}
          >
            {/* 移动端顶栏:无权限占位页本身没有汉堡入口,这里补一个,与会话/知识页一致,
                避免收起侧栏后用户无法唤出系统菜单。 */}
            {shouldHideSidebarOnMobileAppsArea && !isChannelRoute && !isAppChatRoute ? (
              <div className="sticky top-0 z-[50] w-full shrink-0 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
                <div className="relative flex h-11 min-h-11 w-full flex-row items-center justify-between px-4">
                  <button
                    type="button"
                    aria-label={localize("com_nav_open_sidebar")}
                    onClick={() => setSystemMenuOpen(true)}
                    className="workbench-menu-trigger relative inline-flex size-5 shrink-0 items-center justify-center text-text-1"
                  >
                    <Outlined.SidebarMenu className="size-5" />
                  </button>
                  {isQueryDrivenRoute ? (
                    <span className="pointer-events-none absolute left-1/2 -translate-x-1/2 truncate text-[16px] font-medium leading-6 text-text-1">
                      {localize(
                        isSquareRoute
                          ? "com_workbench_sidebar.square"
                          : isCapabilitiesRoute
                            ? "com_capability_center.title"
                            : "com_skill_center_title",
                      )}
                    </span>
                  ) : null}
                  <div className="min-w-0 flex-1" aria-hidden />
                </div>
              </div>
            ) : null}
            {isLiveRoute ? (
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{outlet}</div>
            ) : (
              outlet
            )}
          </div>
        ) : (
          <KeepAlive
            name={cacheKey}
            id={cacheKey}
            saveScroll={true}
            // React 18 chat consumers stay live so cached navigation and streaming
            // state advance together when returning from a module.
            autoFreeze={cacheKey !== "chat_tab"}
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
                "relative bg-white",
                isMobile
                  ? innerScrollShell
                    ? "flex h-[100dvh] min-h-0 w-full flex-col overflow-hidden"
                    : "h-auto min-h-[100dvh] overflow-visible"
                  : innerScrollShell
                    ? "flex h-[100dvh] min-h-0 flex-col overflow-hidden overscroll-y-none"
                    : "scrollbar-os h-[100dvh] overflow-y-auto overscroll-y-none",
                // While the system menu is revealed, clip content to the rounded corners so the
                // exposed left edge shows the radius (e.g. knowledge uses overflow-visible otherwise).
                systemMenuRevealing && "overflow-hidden",
              )}
            >
              {/* 移动端应用中心顶栏：与频道页一致 — 菜单按钮触发系统主菜单(整页右滑) */}
              {shouldHideSidebarOnMobileAppsArea && isAppsArea && !isAppChatRoute && !isAppsExploreRoute ? (
                <div className="sticky top-0 z-[50] w-full shrink-0 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
                  <div className="relative flex h-11 min-h-11 w-full flex-row items-center justify-between px-4">
                    <button
                      type="button"
                      aria-label={localize("com_nav_open_sidebar")}
                      onClick={() => setSystemMenuOpen(true)}
                      className="workbench-menu-trigger relative inline-flex size-5 shrink-0 items-center justify-center text-text-1"
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
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{outlet}</div>
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
            <DialogTitle className="text-center text-lg font-medium">
              {localize("com_system_notice.title")}
            </DialogTitle>
          </DialogHeader>
          <div className="py-6 px-2">
            <div className="text-sm text-gray-700 leading-relaxed text-center whitespace-pre-wrap">
              {systemNotice}
            </div>
          </div>
          <DialogFooter className="sm:justify-center flex-row justify-center pb-2">
            <Button onClick={closeSystemNotice} className="w-[120px] rounded-full">
              {localize("com_auth.got_it")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
