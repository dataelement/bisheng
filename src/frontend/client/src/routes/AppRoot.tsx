import { useEffect, useState } from 'react';
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
    const isFromHomeRecommendedEntry = (() => {
        const searchParams = new URLSearchParams(location.search);
        const from = searchParams.get('from');
        const entry = searchParams.get('entry');
        if (from === 'center' || from === 'explore') return false;
        if (from === 'home-recommended' && entry === 'home') return true;
        const pathSegments = location.pathname.split('/').filter(Boolean);
        const appSegmentIndex = pathSegments.indexOf('app');
        const conversationId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 1] : '';
        if (!conversationId) return false;
        try {
            const persistedOrigin = sessionStorage.getItem(appOriginStorageKey(conversationId));
            if (persistedOrigin === 'center' || persistedOrigin === 'explore') return false;
            if (persistedOrigin === 'home') return true;
            return sessionStorage.getItem(`app-chat-entry:${conversationId}`) === 'home';
        } catch {
            return false;
        }
    })();

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
        // App center entries (home list / explore) should always return to app center.
        if (from === 'center' || from === 'explore' || persistedOrigin === 'center' || persistedOrigin === 'explore') {
            navigate('/apps');
            return;
        }
        if (fromHomeEntry || (from === 'home-recommended' && entry === 'home') || persistedOrigin === 'home') {
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
        navigate(`/app/${chatId}/${flowId}/${flowType}`);
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
        if (!conversationId) return;
        let origin: 'center' | 'explore' | 'home' | null = null;
        if (from === 'center') origin = 'center';
        else if (from === 'explore') origin = 'explore';
        else if (from === 'home-recommended' && entry === 'home') origin = 'home';
        if (!origin) return;
        try {
            sessionStorage.setItem(appOriginStorageKey(conversationId), origin);
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
                        ? "p-2 touch-mobile:p-0 max-[768px]:p-0"
                        : "p-4 touch-mobile:p-0",
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
                            <div className="relative flex h-full w-[280px] max-w-[280px] shrink-0 flex-col overflow-hidden border-r border-[#e5e6eb] bg-white shadow-[4px_0_24px_rgba(0,0,0,0.06)] pt-[env(safe-area-inset-top,0px)]">
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
                                preferBackButton={isFromHomeRecommendedEntry}
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
