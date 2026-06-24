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
import { MobileNav, Nav } from '~/components/Nav';
import { useAgentsMap, useAssistantsMap, useAuthContext, useFileMap, useSearch } from '~/hooks';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import store from '~/store';
import { cn } from '~/utils';

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
              {/*
                与 MainLayout 白卡对齐，占满卡片高度；内层 flex-1 min-h-0 overflow-hidden
                把高度传给 ChatView，避免整页滚动把输入框卷出视口。
                桌面端 main 有 p-2 留白，卡片高度为 100dvh-16px；移动端 main 无内边距
                (min-h-[100dvh])，须占满 100dvh，否则底部会多出 16px 空白条。
              */}
              <div
                className={cn(
                  'flex flex-col overflow-hidden min-w-0',
                  isSmallScreen
                    ? 'h-[100dvh] max-h-[100dvh]'
                    : 'h-[calc(100dvh-16px)] max-h-[calc(100dvh-16px)]',
                )}
              >
                <Banner onHeightChange={setBannerHeight} />
                <div className="flex min-h-0 flex-1 overflow-hidden">
                  <div className="relative z-0 flex min-h-0 w-full flex-1 overflow-hidden">
                    <Nav navVisible={navVisible} setNavVisible={setNavVisible} />
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
