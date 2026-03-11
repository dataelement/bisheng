import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import type { ContextType } from '~/common';
import { Banner } from '~/components/Banners';
import { MobileNav } from '~/components/Nav';
import { useAuthContext } from '~/hooks';
import { SideNav } from '~/pages/appChat/SideNav';


export default function AppRoot() {
    const [bannerHeight, setBannerHeight] = useState(0);
    const [navVisible, setNavVisible] = useState(() => {
        const savedNavVisible = localStorage.getItem('navVisible');
        return savedNavVisible !== null ? JSON.parse(savedNavVisible) : true;
    });

    const { isAuthenticated, logout } = useAuthContext();

    if (!isAuthenticated) {
        return null;
    }


    return (
        <div>
            {/* 页面头部黑色banner */}
            <Banner onHeightChange={setBannerHeight} />
            <div className="flex" style={{ height: `calc(100dvh - ${bannerHeight}px)` }}>
                <div className="relative z-0 flex h-full w-full overflow-hidden">
                    {/* 会话列表 */}
                    <SideNav />
                    {/* 会话消息面板区(路由) */}
                    <div className="relative flex h-full max-w-full flex-1 flex-col overflow-hidden">
                        <MobileNav setNavVisible={setNavVisible} />
                        <Outlet context={{ navVisible, setNavVisible } satisfies ContextType} />
                    </div>
                </div>
            </div>
        </div>
    );
}
