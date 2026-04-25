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
    const isFromHomeRecommendedEntry = (() => {
        const searchParams = new URLSearchParams(location.search);
        const from = searchParams.get('from');
        const entry = searchParams.get('entry');
        if (from === 'home-recommended' && entry === 'home') return true;
        const pathSegments = location.pathname.split('/').filter(Boolean);
        const appSegmentIndex = pathSegments.indexOf('app');
        const conversationId = appSegmentIndex >= 0 ? pathSegments[appSegmentIndex + 1] : '';
        if (!conversationId) return false;
        try {
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
        if (fromHomeEntry || (from === 'home-recommended' && entry === 'home')) {
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

    if (!isAuthenticated) {
        return null;
    }
    return (
        <div className="h-[100dvh] w-full overflow-hidden">
            {/* Page header banner */}
            <Banner onHeightChange={setBannerHeight} />
            <div className="flex w-full overflow-hidden bg-[#F9F9F9] p-4 touch-mobile:p-0" style={{ height: `calc(100dvh - ${bannerHeight}px)` }}>
                <div className="relative z-0 flex h-full w-full overflow-hidden">

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
                        <div className="absolute inset-0 z-[55] flex">
                            <div className="h-full w-[280px] border-r border-[#ececec] bg-white shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
                                <SideNav />
                            </div>
                            <button
                                type="button"
                                className="flex-1 bg-[rgba(86,88,105,0.55)]"
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
