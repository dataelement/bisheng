import { useEffect, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import { ChevronLeft } from 'lucide-react';
import { useUnactivate } from 'react-activation';
import type { ContextType } from '~/common';
import { Banner } from '~/components/Banners';
import { MobileNav } from '~/components/Nav';
import NavToggle from '~/components/Nav/NavToggle';
import { useAuthContext, useLocalize, useMediaQuery, usePrefersMobileLayout } from '~/hooks';
import { SideNav } from '~/pages/appChat/SideNav';
import {
    copyAppChatReturnTo,
    copyAppChatOrigin,
    normalizeAppChatReturn,
    readAppChatReturnTo,
    writeAppChatReturnTo,
} from '~/pages/appChat/appChatOrigin';
import { appConversationsState, sidebarVisibleState } from '~/pages/appChat/store/appSidebarAtoms';
import store from '~/store';
import { cn, generateUUID } from '~/utils';

export default function AppRoot() {
    const location = useLocation();
    const localize = useLocalize();
    const [bannerHeight, setBannerHeight] = useState(0);
    const [navVisible, setNavVisible] = useState(() => {
        const savedNavVisible = localStorage.getItem('navVisible');
        return savedNavVisible !== null ? JSON.parse(savedNavVisible) : true;
    });
    const [isHovering, setIsHovering] = useState(false);

    const navigate = useNavigate();
    const { isAuthenticated } = useAuthContext();
    const [, setAppConversations] = useRecoilState(appConversationsState);
    const [sidebarVisible, setSidebarVisible] = useRecoilState(sidebarVisibleState);
    const mobileNavHidden = useRecoilValue(store.chatMobileNavHiddenState);
    const isTabletOrMobile = usePrefersMobileLayout();
    /** 与 tailwind touch-mobile 一致：768–1023 仍用合并顶栏，避免仅 isTabletOrMobile 时出现 absolute 悬浮菜单 + 内层标题双行 */
    /** ≤1023：合并顶栏 + 禁止左上角 absolute 悬浮钮（与 tailwind touch-mobile 一致） */
    const isAppChatCompact = useMediaQuery('(max-width: 1023px)');
    const sidebarWidth = 240;
    const isAppConversationRoute = /^\/app\/[^/]+\/[^/]+\/[^/]+(?:\/|$)/.test(location.pathname);
    /** AppRoot 仅挂在 /app/*；含 `/app/:fid/:type` 入口，不能用仅三段的 isAppConversationRoute 控制顶栏 */
    const isAppSurface = location.pathname.includes('/app/');
    const scrollLockPrevRef = useRef<{ body: string; html: string } | null>(null);

    type AppSurfaceLocationState = { appSurfaceReturn?: string };

    const toggleSidebar = () => setSidebarVisible((prev) => !prev);
    const handleGoBack = () => {
        // Same browser-history-based back as SideNav. Avoids unreliable
        // URL-param routing when the chat URL doesn't reflect the user's
        // perceived navigation source.
        if (typeof window !== 'undefined' && window.history.length > 1) {
            navigate(-1);
            return;
        }
        navigate('/apps', { replace: true });
    };
    const handleCreateNewAppChat = () => {
        const pathSegments = location.pathname.split('/').filter(Boolean);
        const appSegmentIndex = pathSegments.indexOf('app');
        const flowId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 2] : '';
        const flowType = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 3] : '';
        const conversationId =
            appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 1] : '';
        if (!flowId || !flowType) {
            navigate('/apps');
            return;
        }
        const chatId = generateUUID(32);
        if (conversationId) copyAppChatOrigin(conversationId, chatId);
        if (conversationId) copyAppChatReturnTo(conversationId, chatId);
        const now = new Date().toISOString();
        setAppConversations((prev) => [
            {
                id: chatId,
                title: localize('com_ui_new_chat'),
                flowId,
                flowType: Number(flowType),
                updatedAt: now,
                createdAt: now,
            },
            ...prev,
        ]);
        setSidebarVisible(false);
        navigate(`/app/${chatId}/${flowId}/${flowType}`, { state: location.state });
    };

    // Back-fill sessionStorage from URL/state so back button only relies on conversation return target.
    useEffect(() => {
        if (!isAppConversationRoute) return;
        const pathSegments = location.pathname.split('/').filter(Boolean);
        const appSegmentIndex = pathSegments.indexOf('app');
        const conversationId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 1] : '';
        if (!conversationId) return;
        const normalizedReturnTo = normalizeAppChatReturn(new URLSearchParams(location.search).get('returnTo'))
            ?? normalizeAppChatReturn((location.state as AppSurfaceLocationState | null)?.appSurfaceReturn);
        if (normalizedReturnTo) writeAppChatReturnTo(conversationId, normalizedReturnTo);
    }, [isAppConversationRoute, location.pathname, location.search, location.state]);

    useEffect(() => {
        if (!isAuthenticated) {
            return;
        }
        const prevBodyOverflow = document.body.style.overflow;
        const prevHtmlOverflow = document.documentElement.style.overflow;
        scrollLockPrevRef.current = { body: prevBodyOverflow, html: prevHtmlOverflow };
        document.body.style.overflow = 'hidden';
        document.documentElement.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = prevBodyOverflow;
            document.documentElement.style.overflow = prevHtmlOverflow;
            scrollLockPrevRef.current = null;
        };
    }, [isAuthenticated]);

    // KeepAlive deactivation does not unmount this component; ensure global
    // scroll lock is released when leaving the app-chat surface.
    useUnactivate(() => {
        const prev = scrollLockPrevRef.current;
        if (!prev) return;
        document.body.style.overflow = prev.body;
        document.documentElement.style.overflow = prev.html;
        scrollLockPrevRef.current = null;
    });

    if (!isAuthenticated) {
        return null;
    }
    return (
        <div className="h-[100dvh] w-full overflow-hidden">
            {/* Page header banner */}
            <Banner onHeightChange={setBannerHeight} />
            <div
                className={cn(
                    "flex w-full overflow-hidden bg-[#F9F9F9]",
                    isAppConversationRoute
                        ? " touch-mobile:p-0 max-[768px]:p-0"
                        : " touch-mobile:p-0",
                )}
                style={{ height: `calc(100dvh - ${bannerHeight}px)` }}
            >
                <div
                    className={cn(
                        "relative z-0 flex h-full w-full overflow-hidden rounded-[12px] touch-mobile:rounded-none",
                        "bg-white p-0",
                    )}
                >

                    {/* Desktop/Tablet sidebar */}
                    {!isTabletOrMobile && (
                        <div
                            className={cn(
                                'transition-all duration-300 overflow-hidden flex-shrink-0',
                                sidebarVisible ? 'w-[240px]' : 'w-0',
                            )}
                        >
                            <SideNav />
                        </div>
                    )}

                    {/* Mobile overlay sidebar (covers content, does not push) */}
                    {isTabletOrMobile && sidebarVisible && (
                        <div className="fixed inset-0 z-[70] flex">
                            <div className="relative flex h-full w-[240px] max-w-[240px] shrink-0 flex-col overflow-hidden bg-white shadow-[4px_0_24px_rgba(0,0,0,0.06)] pt-[env(safe-area-inset-top,0px)]">
                                <SideNav />
                            </div>
                            <button
                                type="button"
                                className="min-w-0 flex-1 bg-[rgba(86,88,105,0.55)]"
                                aria-label="Close sidebar overlay"
                                onClick={toggleSidebar}
                            />
                        </div>
                    )}

                    {/* Floating toggle button - lives outside the clipped sidebar */}
                    {!isTabletOrMobile && !(isAppSurface && isAppChatCompact) && (
                        <NavToggle
                            navVisible={sidebarVisible}
                            onToggle={toggleSidebar}
                            isHovering={isHovering}
                            setIsHovering={setIsHovering}
                            className="absolute left-0 top-1/2 z-[50]"
                            translateX={sidebarWidth - 5}
                        />
                    )}

                    {/* 宽屏侧栏收起：仅保留返回（菜单已进 MobileNav）。勿用 flex+hidden 叠类名，避免 twMerge 后仍显示 absolute 钮叠在顶栏上 */}
                    {!sidebarVisible && !(isAppSurface && isAppChatCompact) && (
                        <div className="absolute left-3 top-3 z-[40] flex items-center gap-2 transition-all duration-300">
                            <button
                                type="button"
                                onClick={handleGoBack}
                                className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-[#ebecf0] bg-white text-[#212121] shadow-sm transition-colors hover:bg-gray-50"
                                aria-label={localize('com_ui_go_back')}
                            >
                                <ChevronLeft size={16} className="text-[#212121]" />
                            </button>
                        </div>
                    )}

                    {/* Chat panel (routed) */}
                    <div className="relative flex h-full max-w-full min-w-0 flex-1 flex-col overflow-hidden">
                        {isAppSurface && isAppChatCompact && !mobileNavHidden && (
                            <div className="shrink-0 overflow-hidden rounded-t-[12px] bg-white">
                                <MobileNav
                                    variant="chat"
                                    navVisible={sidebarVisible}
                                    setNavVisible={setSidebarVisible}
                                    persistNavVisibleInLocalStorage={false}
                                    navigateToNewChatPath={false}
                                    onNewChat={handleCreateNewAppChat}
                                    appSurfaceBackAction={handleGoBack}
                                />
                            </div>
                        )}
                        <div className="min-h-0 min-w-0 flex-1 overflow-hidden bg-white">
                            <Outlet context={{ navVisible, setNavVisible } satisfies ContextType} />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
