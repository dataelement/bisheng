import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import type { ContextType } from '~/common';
import { Banner } from '~/components/Banners';
import { MobileNav } from '~/components/Nav';
import { useAuthContext } from '~/hooks';
import { SideNav } from '~/pages/appChat/SideNav';
import { sidebarVisibleState } from '~/pages/appChat/store/appSidebarAtoms';
import { cn } from '~/utils';


export default function AppRoot() {
    const [bannerHeight, setBannerHeight] = useState(0);
    const [navVisible, setNavVisible] = useState(() => {
        const savedNavVisible = localStorage.getItem('navVisible');
        return savedNavVisible !== null ? JSON.parse(savedNavVisible) : true;
    });

    const { isAuthenticated, logout } = useAuthContext();
    const sidebarVisible = useRecoilValue(sidebarVisibleState);

    if (!isAuthenticated) {
        return null;
    }


    return (
        <div>
            {/* Page header banner */}
            <Banner onHeightChange={setBannerHeight} />
            <div className="flex" style={{ height: `calc(100dvh - ${bannerHeight}px)` }}>
                <div className="relative z-0 flex h-full w-full overflow-hidden">
                    {/* Sidebar with CSS transition for smooth folding */}
                    <div
                        className={cn(
                            'transition-all duration-300 overflow-hidden flex-shrink-0',
                            sidebarVisible ? 'w-[280px]' : 'w-0',
                        )}
                    >
                        <SideNav />
                    </div>
                    {/* Chat panel (routed) */}
                    <div className="relative flex h-full max-w-full flex-1 flex-col overflow-hidden">
                        <MobileNav setNavVisible={setNavVisible} />
                        <Outlet context={{ navVisible, setNavVisible } satisfies ContextType} />
                    </div>
                </div>
            </div>
        </div>
    );
}

