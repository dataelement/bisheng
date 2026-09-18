import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import {
  AgentsMapContext,
  AssistantsMapContext,
  FileMapContext,
  SearchContext,
  SetConvoProvider,
} from '~/Providers';
import type { ContextType } from '~/common';
import { Banner } from '~/components/Banners';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { MobileNav, Nav } from '~/components/Nav';
import { useAgentsMap, useAssistantsMap, useAuthContext, useFileMap, useSearch } from '~/hooks';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import store from '~/store';

export default function Root() {
  const [, setBannerHeight] = useState(0);
  const isSmallScreen = usePrefersMobileLayout();
  const [navVisible, setNavVisible] = useRecoilState(store.chatHistoryDrawerOpen);
  const mobileNavHidden = useRecoilValue(store.chatMobileNavHiddenState);
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
    // Themed startup spinner — identical to the platform app's LoadingIcon
    // (same BrandTickSpinner, size and centering) so the platform→client
    // hand-off shows no size/position jump.
    return (
      <div className="flex h-full w-full items-center justify-center bg-white">
        <LoadingIcon className="w-48 text-primary" />
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
              {/*
                Fills the MainLayout panel (100dvh on both shells); the inner
                flex-1 min-h-0 overflow-hidden hands the height down to ChatView so
                the page never scrolls the input box out of the viewport.
              */}
              <div className="flex h-[100dvh] max-h-[100dvh] min-w-0 flex-col overflow-hidden">
                <Banner onHeightChange={setBannerHeight} />
                <div className="flex min-h-0 flex-1 overflow-hidden">
                  <div className="relative z-0 flex min-h-0 w-full flex-1 overflow-hidden">
                    {/* Desktop lists conversations in the workbench sidebar (MainLayout);
                        the chat-local nav is the mobile history drawer only. */}
                    {isSmallScreen ? <Nav navVisible={navVisible} setNavVisible={setNavVisible} /> : null}
                    <div className="relative flex min-h-0 max-w-full flex-1 flex-col overflow-hidden">
                      {showMobileNav && isSmallScreen && !mobileNavHidden ? (
                        // 勿用 fixed 贴视口：会盖住 MainLayout 白卡 rounded-xl 上沿与两侧灰底留白（与知识库 H5、StandaloneChat 一致）
                        <div className="shrink-0 overflow-hidden rounded-t-xl bg-white">
                          <MobileNav
                            variant="chat"
                            navVisible={navVisible}
                            setNavVisible={setNavVisible}
                            persistNavVisibleInLocalStorage={false}
                          />
                        </div>
                      ) : null}
                      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                        <Outlet context={{ navVisible, setNavVisible } satisfies ContextType} />
                      </div>
                    </div>
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
