import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { useAuthContext, useMediaQuery, usePrefersMobileLayout } from '~/hooks';
import { AuthContext } from '~/hooks/AuthContext';
import { MobileNav } from '~/components/Nav';
import NavToggle from '~/components/Nav/NavToggle';
import { sidebarVisibleState } from '~/pages/appChat/store/appSidebarAtoms';
import AppChat from '~/pages/appChat';
import { ChatEmptyState } from '~/pages/appChat/components/ChatEmptyState';
import { cn } from '~/utils';
import { StandaloneChatContext } from './StandaloneChatContext';
import type { StandaloneChatContextValue } from './StandaloneChatContext';
import { StandaloneSideNav } from './StandaloneSideNav';
import { useStandaloneSidebar } from './hooks/useStandaloneSidebar';

interface StandaloneChatPageProps {
  mode: 'guest' | 'auth';
  flowType: 'workflow' | 'assistant';
  hideSidebar?: boolean;
  forceNewChatOnLoad?: boolean;
  initialChatId?: string;
}

const FLOW_TYPE_MAP = {
  workflow: '10',
  assistant: '5',
};

// Minimal auth context for guest mode — provides "not authenticated" values
// without making any API calls or triggering 401 redirects.
const noop = () => { };
const guestAuthValue = {
  user: undefined,
  token: undefined,
  isAuthenticated: false,
  isUserLoading: false,
  error: undefined,
  login: noop as any,
  logout: noop,
  setError: noop as any,
  roles: {},
};

export default function StandaloneChatPage({
  mode,
  flowType,
  hideSidebar = false,
  forceNewChatOnLoad = false,
  initialChatId = '',
}: StandaloneChatPageProps) {
  const pageProps = { mode, flowType, hideSidebar, forceNewChatOnLoad, initialChatId };

  // Guest mode: wrap in a lightweight AuthContext that provides "not authenticated"
  // values so child components (ChatView, MessageUser) that call useAuthContext()
  // don't throw. This avoids using AuthContextProvider which makes API calls and
  // triggers 401 redirects in production.
  if (mode === 'guest') {
    return (
      <AuthContext.Provider value={guestAuthValue}>
        <StandaloneChatInner {...pageProps} />
      </AuthContext.Provider>
    );
  }

  // Auth mode: AuthContextProvider is already provided by the parent AuthLayout
  return <AuthStandaloneChatInner {...pageProps} />;
}

// Auth mode wrapper: redirect to login when user is not authenticated
function AuthStandaloneChatInner(props: StandaloneChatPageProps) {
  const { user, isUserLoading, logout } = useAuthContext();

  useEffect(() => {
    if (!isUserLoading && !user) {
      logout();
    }
  }, [isUserLoading, user, logout]);

  if (!user) return null;

  return <StandaloneChatInner {...props} />;
}

function StandaloneChatInner({
  mode,
  flowType,
  hideSidebar = false,
  forceNewChatOnLoad = false,
  initialChatId = '',
}: StandaloneChatPageProps) {
  const { flowId } = useParams<{ flowId: string }>();
  const [sidebarVisible, setSidebarVisible] = useRecoilState(sidebarVisibleState);
  const [isHovering, setIsHovering] = useState(false);
  const isTabletOrMobile = usePrefersMobileLayout();
  const isChatShellCompact = useMediaQuery('(max-width: 1023px)');
  const sidebarWidth = 240;

  const apiVersion = mode === 'guest' ? 'v2' : 'v1';
  const numericFlowType = FLOW_TYPE_MAP[flowType];
  const isGuestMode = mode === 'guest';

  const contextValue: StandaloneChatContextValue = {
    mode,
    flowType,
    flowId: flowId ?? '',
    apiVersion,
  };

  // Lifted to page level so both sidebar and chat panel share one instance
  // (single init, single draft registry, shared createNewChat for CTA).
  const sidebar = useStandaloneSidebar(contextValue, { forceNewChatOnLoad, initialChatId });
  const { activeChatId, historyLoaded, createNewChat } = sidebar;
  const showSidebarControls = !hideSidebar;

  const toggleSidebar = () => setSidebarVisible((prev) => !prev);

  if (!flowId) return null;

  // Guest: neutral gray page + one white rounded shell (ref. design: gray backdrop, white card)
  const guestOuterShell = isGuestMode
    ? 'flex min-h-0 min-w-0 flex-1 flex-row overflow-hidden rounded-2xl bg-white shadow-[0_4px_32px_rgba(0,0,0,0.08)]'
    : 'contents';

  return (
    <StandaloneChatContext.Provider value={contextValue}>
      <div
        className={cn('flex', isGuestMode ? 'bg-[#DCDDDF]' : 'bg-[#F9F9F9]')}
        style={{ height: '100dvh' }}
      >
        <div
          className={cn(
            'relative z-0 flex h-full w-full overflow-hidden p-2',
            isGuestMode ? 'bg-[#DCDDDF]' : 'bg-[#F4F5F7]',
          )}
        >
          {/* Mobile overlay sidebar (covers full area; stays outside the guest rounded shell) */}
          {isTabletOrMobile && showSidebarControls && sidebarVisible && (
            <div className="absolute inset-0 z-[70] flex">
              <div className="h-full w-[240px] max-w-[240px] bg-white shadow-[4px_0_24px_rgba(0,0,0,0.06)] pt-[env(safe-area-inset-top,0px)]">
                <StandaloneSideNav sidebar={sidebar} onCloseSidebar={toggleSidebar} />
              </div>
              <button
                type="button"
                className="flex-1 bg-[rgba(86,88,105,0.55)]"
                aria-label="Close sidebar overlay"
                onClick={toggleSidebar}
              />
            </div>
          )}

          <div className={guestOuterShell}>
            {/* Desktop sidebar */}
            {!isTabletOrMobile && showSidebarControls && (
              <div
                className={cn(
                  'transition-all duration-300 overflow-hidden flex-shrink-0',
                  sidebarVisible ? 'w-[240px]' : 'w-0',
                )}
              >
                <StandaloneSideNav sidebar={sidebar} />
              </div>
            )}

            {/* Toggle button (desktop) */}
            {!isTabletOrMobile && !isChatShellCompact && showSidebarControls && (
              <NavToggle
                navVisible={sidebarVisible}
                onToggle={toggleSidebar}
                isHovering={isHovering}
                setIsHovering={setIsHovering}
                className="absolute left-2 top-1/2 z-[50]"
                translateX={sidebarWidth - 5}
              />
            )}

            {/* Chat panel */}
            <div
              className={cn(
                'relative flex h-full max-w-full min-w-0 flex-1 flex-col overflow-hidden',
                'p-0',
              )}
            >
              {isChatShellCompact && showSidebarControls && (
                <div className="shrink-0 overflow-hidden rounded-t-xl bg-white">
                  <MobileNav
                    variant="chat"
                    navVisible={sidebarVisible}
                    setNavVisible={setSidebarVisible}
                    persistNavVisibleInLocalStorage={false}
                    navigateToNewChatPath={false}
                    onNewChat={createNewChat}
                  />
                </div>
              )}
              <div
                className={cn(
                  'min-h-0 min-w-0 flex-1 overflow-hidden',
                  isGuestMode
                    ? 'bg-white'
                    : 'rounded-xl border border-[#EBECF0] bg-white shadow-xl',
                  !isGuestMode && 'touch-mobile:rounded-none touch-mobile:border-0 touch-mobile:shadow-none',
                )}
              >
                {activeChatId ? (
                  <AppChat
                    chatId={activeChatId}
                    flowId={flowId}
                    flowType={numericFlowType}
                    apiVersion={apiVersion}
                    isGuestMode={isGuestMode}
                  />
                ) : historyLoaded ? (
                  <ChatEmptyState onNewChat={createNewChat} />
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>
    </StandaloneChatContext.Provider>
  );
}
