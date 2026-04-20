import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import {
  AgentsMapContext,
  AssistantsMapContext,
  FileMapContext,
  SearchContext,
  SetConvoProvider,
} from '~/Providers';
import type { ContextType } from '~/common';
import { Banner } from '~/components/Banners';
import { MobileNav, Nav } from '~/components/Nav';
import { useAgentsMap, useAssistantsMap, useAuthContext, useFileMap, useSearch } from '~/hooks';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import store from '~/store';

export default function Root() {
  const [bannerHeight, setBannerHeight] = useState(0);
  const isSmallScreen = usePrefersMobileLayout();
  const [navVisible, setNavVisible] = useRecoilState(store.chatHistoryDrawerOpen);
  const { pathname } = useLocation();

  const { isAuthenticated, isUserLoading, logout } = useAuthContext();
  const assistantsMap = useAssistantsMap({ isAuthenticated });
  const agentsMap = useAgentsMap({ isAuthenticated });
  const fileMap = useFileMap({ isAuthenticated });
  const search = useSearch({ isAuthenticated });


  const showMobileNav = /^\/(c|linsight)(\/|$)/.test(pathname);

  // Force close nav on mobile regardless of localStorage
  useEffect(() => {
    if (isSmallScreen) {
      setNavVisible(false);
    }
  }, [isSmallScreen]);

  if (isUserLoading) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-white text-sm text-gray-500 dark:bg-gray-900 dark:text-gray-400">
        Loading…
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }


  return (
    <SetConvoProvider>
      <SearchContext.Provider value={search}>
        <FileMapContext.Provider value={fileMap}>
          <AssistantsMapContext.Provider value={assistantsMap}>
            <AgentsMapContext.Provider value={agentsMap}>
              {/* 页面头部黑色banner */}
              <Banner onHeightChange={setBannerHeight} />
              <div className="flex h-full">
                <div className="relative z-0 flex h-full w-full overflow-hidden">
                  {/* 会话列表 */}
                  <Nav navVisible={navVisible} setNavVisible={setNavVisible} />
                  {/* 会话消息面板区(路由) */}
                  <div className="relative flex h-full max-w-full flex-1 flex-col overflow-hidden">
                    {showMobileNav && isSmallScreen ? (
                      <MobileNav
                        variant="chat"
                        navVisible={navVisible}
                        setNavVisible={setNavVisible}
                        persistNavVisibleInLocalStorage={false}
                      />
                    ) : null}
                    <Outlet context={{ navVisible, setNavVisible } satisfies ContextType} />
                  </div>
                </div>
              </div>
            </AgentsMapContext.Provider>
          </AssistantsMapContext.Provider>
        </FileMapContext.Provider>
      </SearchContext.Provider>
    </SetConvoProvider>
  );
}
