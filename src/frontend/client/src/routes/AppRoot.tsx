import { useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import { ChevronLeft } from 'lucide-react';
import type { ContextType } from '~/common';
import { Banner } from '~/components/Banners';
import { MobileNav } from '~/components/Nav';
import { useAuthContext, useLocalize } from '~/hooks';
import { SideNav } from '~/pages/appChat/SideNav';
import { sidebarVisibleState } from '~/pages/appChat/store/appSidebarAtoms';
import { cn } from '~/utils';
import { Tooltip, TooltipTrigger, TooltipContent } from '~/components/ui/Tooltip2';

/**
 * Toggle button to collapse/expand sidebar.
 * Uses two CSS-drawn bars that rotate to form a chevron shape.
 */
function SidebarToggle({ visible, onToggle }: { visible: boolean; onToggle: () => void }) {
    const localize = useLocalize();
    return (
        <Tooltip delayDuration={0}>
            <TooltipTrigger asChild>
                <div
                    onClick={onToggle}
                    className="absolute top-1/2 -translate-y-1/2 z-[50] w-[24px] h-[32px] rounded-[6px] flex flex-col items-center justify-center cursor-pointer hover:bg-gray-50 transition-all duration-300 ease-in-out group"
                    style={{ left: visible ? '278px' : '0px' }}
                >
                    <div className="relative w-[4px] h-[12px] flex flex-col items-center justify-center overflow-visible">
                        {/* Top bar */}
                        <div
                            className="absolute top-1/2 w-[2px] h-[6px] bg-[#a9aeb8] rounded-full origin-bottom transition-transform duration-300 ease-in-out group-hover:bg-[#212121]"
                            style={{ transform: visible ? 'translateY(-100%) rotate(15deg)' : 'translateY(-100%) rotate(-15deg)' }}
                        />
                        {/* Bottom bar */}
                        <div
                            className="absolute top-1/2 w-[2px] h-[6px] bg-[#a9aeb8] rounded-full origin-top transition-transform duration-300 ease-in-out group-hover:bg-[#212121]"
                            style={{ transform: visible ? 'rotate(-15deg)' : 'rotate(15deg)' }}
                        />
                    </div>
                </div>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={8}>
                {visible ? localize('com_nav_close_sidebar') : localize('com_nav_open_sidebar')}
            </TooltipContent>
        </Tooltip>
    );
}

export default function AppRoot() {
    const [bannerHeight, setBannerHeight] = useState(0);
    const [navVisible, setNavVisible] = useState(() => {
        const savedNavVisible = localStorage.getItem('navVisible');
        return savedNavVisible !== null ? JSON.parse(savedNavVisible) : true;
    });

    const navigate = useNavigate();
    const { isAuthenticated } = useAuthContext();
    const [sidebarVisible, setSidebarVisible] = useRecoilState(sidebarVisibleState);

    if (!isAuthenticated) {
        return null;
    }

    const toggleSidebar = () => setSidebarVisible((prev) => !prev);

    return (
        <div>
            {/* Page header banner */}
            <Banner onHeightChange={setBannerHeight} />
            <div className="flex" style={{ height: `calc(100dvh - ${bannerHeight}px)` }}>
                <div className="relative z-0 flex h-full w-full overflow-hidden">

                    {/* Sidebar panel - slides via width transition */}
                    <div
                        className={cn(
                            'transition-all duration-300 overflow-hidden flex-shrink-0',
                            sidebarVisible ? 'w-[280px]' : 'w-0',
                        )}
                    >
                        <SideNav />
                    </div>

                    {/* Floating toggle button - lives outside the clipped sidebar */}
                    <SidebarToggle visible={sidebarVisible} onToggle={toggleSidebar} />

                    {/* Floating back button - always visible when sidebar is collapsed */}
                    <div
                        className={cn(
                            'absolute top-[20px] left-[12px] z-[40] flex items-center gap-[8px] transition-all duration-300',
                            sidebarVisible ? 'opacity-0 pointer-events-none' : 'opacity-100 top-3'
                        )}
                    >
                        <button
                            onClick={() => navigate('/apps')}
                            className="flex shrink-0 items-center justify-center size-[32px] rounded-[8px] bg-white border border-[#ebecf0] hover:bg-gray-50 transition-colors shadow-sm"
                        >
                            <ChevronLeft size={16} className="text-[#212121]" />
                        </button>
                    </div>

                    {/* Chat panel (routed) */}
                    <div className="relative flex h-full max-w-full flex-1 flex-col overflow-hidden">
                        <MobileNav
                            variant="app"
                            navVisible={sidebarVisible}
                            setNavVisible={(action) =>
                                setSidebarVisible((prev) =>
                                    typeof action === 'function' ? action(prev) : action
                                )
                            }
                            persistNavVisibleInLocalStorage={false}
                            navigateToNewChatPath={false}
                        />
                        <Outlet context={{ navVisible, setNavVisible } satisfies ContextType} />
                    </div>
                </div>
            </div>
        </div>
    );
}
