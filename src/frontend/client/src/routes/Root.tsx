import { useEffect, useMemo, useState } from 'react';
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
import { Button } from '~/components/ui/Button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '~/components/ui/Dialog';
import { useAgentsMap, useAssistantsMap, useAuthContext, useFileMap, useSearch } from '~/hooks';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import { bishengConfState } from '~/pages/appChat/store/atoms';
import store from '~/store';

const todayKey = () => {
  const d = new Date();
  return `system_notice_shown_${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
};

export default function Root() {
  const [bannerHeight, setBannerHeight] = useState(0);
  const isSmallScreen = usePrefersMobileLayout();
  const [navVisible, setNavVisible] = useRecoilState(store.chatHistoryDrawerOpen);
  const { pathname } = useLocation();

  const [noticeDismissed, setNoticeDismissed] = useState(false);
  const [config] = useRecoilState(bishengConfState)
  const remoteNotice = (config as { system_notification?: string } | undefined)?.system_notification ?? '';

  // Show the configured notice once per calendar day.
  const systemNotice = useMemo(() => {
    if (!remoteNotice || noticeDismissed) return '';
    if (typeof window !== 'undefined' && sessionStorage.getItem(todayKey())) return '';
    return remoteNotice;
  }, [remoteNotice, noticeDismissed]);

  const closeSystemNotice = () => {
    sessionStorage.setItem(todayKey(), 'true');
    setNoticeDismissed(true);
  };
  const { isAuthenticated, logout } = useAuthContext();
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
              {/* 系统通知弹窗 */}
              <Dialog open={!!systemNotice} onOpenChange={closeSystemNotice}>
                <DialogContent className="sm:max-w-md w-[calc(100%-40px)] rounded-2xl mx-auto top-[50%] -translate-y-[50%]">
                  <DialogHeader>
                    <DialogTitle className="text-center text-lg font-medium">系统通知</DialogTitle>
                  </DialogHeader>
                  <div className="py-6 px-2">
                    <div className="text-sm text-gray-700 leading-relaxed text-center whitespace-pre-wrap">
                      {systemNotice}
                    </div>
                  </div>
                  <DialogFooter className="sm:justify-center flex-row justify-center pb-2">
                    <Button
                      onClick={closeSystemNotice}
                      className="w-[120px] rounded-full"
                    >
                      我知道了
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </AgentsMapContext.Provider>
          </AssistantsMapContext.Provider>
        </FileMapContext.Provider>
      </SearchContext.Provider>
    </SetConvoProvider>
  );
}
