import { useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { ChevronLeft, Menu } from 'lucide-react';
import type { ContextType } from '~/common';
import { Banner } from '~/components/Banners';
import NavToggle from '~/components/Nav/NavToggle';
import { useAuthContext, useMediaQuery } from '~/hooks';
import { SideNav } from '~/pages/appChat/SideNav';
import { sidebarVisibleState } from '~/pages/appChat/store/appSidebarAtoms';
import { cn } from '~/utils';

export default function AppRoot() {
    const [bannerHeight, setBannerHeight] = useState(0);
    const [navVisible, setNavVisible] = useState(() => {
        const savedNavVisible = localStorage.getItem('navVisible');
        return savedNavVisible !== null ? JSON.parse(savedNavVisible) : true;
    });
    const [isHovering, setIsHovering] = useState(false);

    const navigate = useNavigate();
    const { isAuthenticated } = useAuthContext();
    const [sidebarVisible, setSidebarVisible] = useRecoilState(sidebarVisibleState);
    const isTabletOrMobile = useMediaQuery('(max-width: 768px)');
    const sidebarWidth = isTabletOrMobile ? 240 : 280;

    if (!isAuthenticated) {
        return null;
    }

    const toggleSidebar = () => setSidebarVisible((prev) => !prev);

    return (
        <div>
            {/* Page header banner */}
            <Banner onHeightChange={setBannerHeight} />
            <div className="flex bg-[#fbfbfb]" style={{ height: `calc(100dvh - ${bannerHeight}px)` }}>
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
                            <div className="h-full w-[240px] border-r border-[#ececec] bg-white shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
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
                            'absolute top-[20px] left-[12px] z-[40] flex items-center gap-[8px] transition-all duration-300',
                            sidebarVisible ? 'opacity-0 pointer-events-none' : 'opacity-100 top-3'
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
                            onClick={() => navigate('/apps')}
                            className="flex shrink-0 items-center justify-center size-[32px] rounded-[8px] bg-white border border-[#ebecf0] hover:bg-gray-50 transition-colors shadow-sm"
                        >
                            <ChevronLeft size={16} className="text-[#212121]" />
                        </button>
                    </div>

                    {/* Chat panel (routed) */}
                    <div className="relative flex h-full max-w-full min-w-0 flex-1 flex-col overflow-hidden p-2">
                        <div className="min-h-0 min-w-0 flex-1 overflow-hidden rounded-[8px] bg-white">
                            <Outlet context={{ navVisible, setNavVisible } satisfies ContextType} />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
