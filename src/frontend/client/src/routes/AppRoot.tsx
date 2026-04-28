import { useEffect, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import { ChevronLeft, Menu } from 'lucide-react';
import type { ContextType } from '~/common';
import { Banner } from '~/components/Banners';
import { MobileNav } from '~/components/Nav';
import NavToggle from '~/components/Nav/NavToggle';
import { useAuthContext, useLocalize, usePrefersMobileLayout } from '~/hooks';
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
    const sidebarWidth = isTabletOrMobile ? 240 : 280;
    const isAppConversationRoute = /^\/app\/[^/]+\/[^/]+\/[^/]+(?:\/|$)/.test(location.pathname);

    type AppSurfaceLocationState = { appSurfaceReturn?: string };

    /**
     * H5 顶栏左侧：应用中心 / 探索 / 首页推荐 进入会话时都应显示「返回」并走 handleGoBack，
     * 否则会落在默认的抽屉按钮，用户以为在退出应用会话，实际只开了侧栏；返回逻辑也与 PC 侧栏不一致。
     */
    const preferMobileAppBackButton = useMemo(
        () => isTabletOrMobile && isAppConversationRoute,
        [isTabletOrMobile, isAppConversationRoute],
    );

    const toggleSidebar = () => setSidebarVisible((prev) => !prev);
    const handleGoBack = () => {
        const go = (to: string) => navigate(to, { replace: true });
        const defaultPath = '/apps';
        const pathSegments = location.pathname.split('/').filter(Boolean);
        const appSegmentIndex = pathSegments.indexOf('app');
        const conversationId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 1] : '';
        const searchParams = new URLSearchParams(location.search);
        const returnTo = searchParams.get('returnTo');
        const from = searchParams.get('from');
        const entry = searchParams.get('entry');
        const surfaceReturn = (location.state as AppSurfaceLocationState | null)?.appSurfaceReturn;

        const normalizedReturnTo = normalizeAppChatReturn(returnTo);
        if (normalizedReturnTo) {
            if (conversationId) writeAppChatReturnTo(conversationId, normalizedReturnTo);
            go(normalizedReturnTo);
            return;
        }

        // Fallback for legacy links where returnTo might be stripped later.
        const fromReturnTo =
            from === 'center'
                ? '/apps'
                : from === 'explore'
                    ? '/apps/explore'
                    : from === 'home-recommended' && entry === 'home'
                        ? '/c/new'
                        : null;
        if (fromReturnTo) {
            if (conversationId) writeAppChatReturnTo(conversationId, fromReturnTo);
            go(fromReturnTo);
            return;
        }

        const storedReturnTo = conversationId ? readAppChatReturnTo(conversationId) : null;
        if (storedReturnTo) {
            go(storedReturnTo);
            return;
        }

        const normalizedSurfaceReturn = normalizeAppChatReturn(surfaceReturn);
        if (normalizedSurfaceReturn) {
            if (conversationId) writeAppChatReturnTo(conversationId, normalizedSurfaceReturn);
            go(normalizedSurfaceReturn);
            return;
        }
        go(defaultPath);
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
        document.body.style.overflow = 'hidden';
        document.documentElement.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = prevBodyOverflow;
            document.documentElement.style.overflow = prevHtmlOverflow;
        };
    }, [isAuthenticated]);

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
                                sidebarVisible ? 'w-[280px]' : 'w-0',
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
                    {!isTabletOrMobile && (
                        <NavToggle
                            navVisible={sidebarVisible}
                            onToggle={toggleSidebar}
                            isHovering={isHovering}
                            setIsHovering={setIsHovering}
                            className="fixed top-1/2 z-[50]"
                            translateX={sidebarWidth - 5}
                        />
                    )}

                    {/* Floating actions - visible when sidebar is collapsed */}
                    <div
                        className={cn(
                            'absolute left-3 top-3 z-[40] flex items-center gap-[8px] transition-all duration-300',
                            sidebarVisible || (isTabletOrMobile && isAppConversationRoute)
                                ? 'opacity-0 pointer-events-none'
                                : 'opacity-100',
                        )}
                    >
                        {isTabletOrMobile && (
                            <button
                                onClick={toggleSidebar}
                                className="flex shrink-0 items-center justify-center size-[32px] rounded-[8px] bg-white border border-[#ebecf0] hover:bg-gray-50 transition-colors shadow-sm"
                                aria-label="Open sidebar"
                            >
                                <Menu size={16} className="text-[#212121]" />
                            </button>
                        )}
                        <button
                            onClick={handleGoBack}
                            className="flex shrink-0 items-center justify-center size-[32px] rounded-[8px] bg-white border border-[#ebecf0] hover:bg-gray-50 transition-colors shadow-sm"
                        >
                            <ChevronLeft size={16} className="text-[#212121]" />
                        </button>
                    </div>

                    {/* Chat panel (routed) */}
                    <div className="relative flex h-full max-w-full min-w-0 flex-1 flex-col overflow-hidden">
                        {isTabletOrMobile && isAppConversationRoute && !mobileNavHidden && (
                            <MobileNav
                                variant="chat"
                                navVisible={sidebarVisible}
                                setNavVisible={setSidebarVisible}
                                persistNavVisibleInLocalStorage={false}
                                navigateToNewChatPath={false}
                                onNewChat={handleCreateNewAppChat}
                                preferBackButton={preferMobileAppBackButton}
                                onBack={handleGoBack}
                            />
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
