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
    const appOriginStorageKey = (conversationId: string) => `app-chat-origin:${conversationId}`;
    const appFlowOriginKey = (flowId: string) => `app-flow-origin:${flowId}`;
    /**
     * H5 顶栏左侧：应用中心 / 探索 / 首页推荐 进入会话时都应显示「返回」并走 handleGoBack，
     * 否则会落在默认的抽屉按钮，用户以为在退出应用会话，实际只开了侧栏；返回逻辑也与 PC 侧栏不一致。
     */
    const preferMobileAppBackButton = useMemo(() => {
        if (!isTabletOrMobile || !isAppConversationRoute) return false;
        const searchParams = new URLSearchParams(location.search);
        const from = searchParams.get('from');
        const entry = searchParams.get('entry');
        if (from === 'center' || from === 'explore') return true;
        if (from === 'home-recommended' && entry === 'home') return true;
        const pathSegments = location.pathname.split('/').filter(Boolean);
        const appSegmentIndex = pathSegments.indexOf('app');
        const conversationId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 1] : '';
        if (!conversationId) return false;
        try {
            const persistedOrigin = sessionStorage.getItem(appOriginStorageKey(conversationId));
            if (
                persistedOrigin === 'center' ||
                persistedOrigin === 'explore' ||
                persistedOrigin === 'home'
            ) {
                return true;
            }
            if (sessionStorage.getItem(`app-chat-entry:${conversationId}`) === 'home') {
                return true;
            }
            const flowId = pathSegments[appSegmentIndex + 2];
            if (flowId) {
                const fo = sessionStorage.getItem(appFlowOriginKey(flowId));
                if (fo === 'center' || fo === 'explore' || fo === 'home') return true;
            }
        } catch {
            return false;
        }
        return false;
    }, [isTabletOrMobile, isAppConversationRoute, location.pathname, location.search]);

    const toggleSidebar = () => setSidebarVisible((prev) => !prev);
    const handleGoBack = () => {
        let fromHomeEntry = false;
        const pathSegments = location.pathname.split('/').filter(Boolean);
        const appSegmentIndex = pathSegments.indexOf('app');
        const conversationId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 1] : '';
        if (conversationId) {
            try {
                fromHomeEntry = sessionStorage.getItem(`app-chat-entry:${conversationId}`) === 'home';
            } catch {
                // ignore storage failures
            }
        }
        const searchParams = new URLSearchParams(location.search);
        const from = searchParams.get('from');
        const entry = searchParams.get('entry');
        let persistedOrigin: 'center' | 'explore' | 'home' | null = null;
        if (conversationId) {
            try {
                const origin = sessionStorage.getItem(appOriginStorageKey(conversationId));
                if (origin === 'center' || origin === 'explore' || origin === 'home') {
                    persistedOrigin = origin;
                }
            } catch {
                // ignore storage failures
            }
        }
        const flowId =
            appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 2] ?? '' : '';
        let persistedFlowOrigin: string | null = null;
        if (flowId) {
            try {
                persistedFlowOrigin = sessionStorage.getItem(appFlowOriginKey(flowId));
            } catch {
                // ignore storage failures
            }
        }
        // App center / 探索：URL、当前会话记录、或当前应用(flow)最近一次入口
        if (
            from === 'center' ||
            from === 'explore' ||
            persistedOrigin === 'center' ||
            persistedOrigin === 'explore' ||
            persistedFlowOrigin === 'center' ||
            persistedFlowOrigin === 'explore'
        ) {
            navigate('/apps');
            return;
        }
        if (
            fromHomeEntry ||
            (from === 'home-recommended' && entry === 'home') ||
            persistedOrigin === 'home' ||
            persistedFlowOrigin === 'home'
        ) {
            navigate('/c/new');
            return;
        }
        navigate('/apps');
    };
    const handleCreateNewAppChat = () => {
        const pathSegments = location.pathname.split('/').filter(Boolean);
        const appSegmentIndex = pathSegments.indexOf('app');
        const flowId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 2] : '';
        const flowType = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 3] : '';
        if (!flowId || !flowType) {
            navigate('/apps');
            return;
        }
        const chatId = generateUUID(32);
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
        const qs = location.search || '';
        navigate(`/app/${chatId}/${flowId}/${flowType}${qs}`);
    };

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

    useEffect(() => {
        const searchParams = new URLSearchParams(location.search);
        const from = searchParams.get('from');
        const entry = searchParams.get('entry');
        const pathSegments = location.pathname.split('/').filter(Boolean);
        const appSegmentIndex = pathSegments.indexOf('app');
        const conversationId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 1] : '';
        const flowId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 2] : '';
        if (!conversationId) return;
        let origin: 'center' | 'explore' | 'home' | null = null;
        if (from === 'center') origin = 'center';
        else if (from === 'explore') origin = 'explore';
        else if (from === 'home-recommended' && entry === 'home') origin = 'home';
        if (!origin) return;
        try {
            sessionStorage.setItem(appOriginStorageKey(conversationId), origin);
            if (flowId) {
                sessionStorage.setItem(appFlowOriginKey(flowId), origin);
            }
        } catch {
            // ignore storage failures
        }
    }, [location.pathname, location.search]);

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
                            'absolute top-4 left-4 z-[40] flex items-center gap-[8px] transition-all duration-300',
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
