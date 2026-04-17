import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { Menu } from 'lucide-react';
import { useAuthContext, useMediaQuery } from '~/hooks';
import { AuthContext } from '~/hooks/AuthContext';
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
}

const FLOW_TYPE_MAP = {
  workflow: '10',
  assistant: '5',
};

// Minimal auth context for guest mode — provides "not authenticated" values
// without making any API calls or triggering 401 redirects.
const noop = () => {};
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

export default function StandaloneChatPage({ mode, flowType }: StandaloneChatPageProps) {
  // Guest mode: wrap in a lightweight AuthContext that provides "not authenticated"
  // values so child components (ChatView, MessageUser) that call useAuthContext()
  // don't throw. This avoids using AuthContextProvider which makes API calls and
  // triggers 401 redirects in production.
  if (mode === 'guest') {
    return (
      <AuthContext.Provider value={guestAuthValue}>
        <StandaloneChatInner mode={mode} flowType={flowType} />
      </AuthContext.Provider>
    );
  }

  // Auth mode: AuthContextProvider is already provided by the parent AuthLayout
  return <AuthStandaloneChatInner mode={mode} flowType={flowType} />;
}

// Auth mode wrapper: redirect to login when user is not authenticated
function AuthStandaloneChatInner({ mode, flowType }: StandaloneChatPageProps) {
  const { user, isUserLoading, logout } = useAuthContext();

  useEffect(() => {
    if (!isUserLoading && !user) {
      logout();
    }
  }, [isUserLoading, user, logout]);

  if (!user) return null;

  return <StandaloneChatInner mode={mode} flowType={flowType} />;
}

function StandaloneChatInner({ mode, flowType }: StandaloneChatPageProps) {
  const { flowId } = useParams<{ flowId: string }>();
  const [sidebarVisible, setSidebarVisible] = useRecoilState(sidebarVisibleState);
  const [isHovering, setIsHovering] = useState(false);
  const isTabletOrMobile = useMediaQuery('(max-width: 768px)');
  const sidebarWidth = isTabletOrMobile ? 240 : 280;

  const apiVersion = mode === 'guest' ? 'v2' : 'v1';
  const numericFlowType = FLOW_TYPE_MAP[flowType];

  const contextValue: StandaloneChatContextValue = {
    mode,
    flowType,
    flowId: flowId ?? '',
    apiVersion,
  };

  // Lifted to page level so both sidebar and chat panel share one instance
  // (single init, single draft registry, shared createNewChat for CTA).
  const sidebar = useStandaloneSidebar(contextValue);
  const { activeChatId, historyLoaded, createNewChat } = sidebar;

  const toggleSidebar = () => setSidebarVisible((prev) => !prev);

  if (!flowId) return null;

  return (
    <StandaloneChatContext.Provider value={contextValue}>
      <div className="flex bg-[#fbfbfb]" style={{ height: '100dvh' }}>
        <div className="relative z-0 flex h-full w-full overflow-hidden">

          {/* Desktop sidebar */}
          {!isTabletOrMobile && (
            <div
              className={cn(
                'transition-all duration-300 overflow-hidden flex-shrink-0',
                sidebarVisible ? 'w-[280px]' : 'w-0',
              )}
            >
              <StandaloneSideNav sidebar={sidebar} />
            </div>
          )}

          {/* Mobile overlay sidebar */}
          {isTabletOrMobile && sidebarVisible && (
            <div className="absolute inset-0 z-[55] flex">
              <div className="h-full w-[240px] border-r border-[#ececec] bg-white shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
                <StandaloneSideNav sidebar={sidebar} />
              </div>
              <button
                type="button"
                className="flex-1 bg-[rgba(86,88,105,0.55)]"
                aria-label="Close sidebar overlay"
                onClick={toggleSidebar}
              />
            </div>
          )}

          {/* Toggle button (desktop) */}
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

          {/* Floating toggle (collapsed state) */}
          <div
            className={cn(
              'absolute top-[20px] left-[12px] z-[40] flex items-center gap-[8px] transition-all duration-300',
              sidebarVisible ? 'opacity-0 pointer-events-none' : 'opacity-100 top-3',
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
          </div>

          {/* Chat panel */}
          <div className="relative flex h-full max-w-full min-w-0 flex-1 flex-col overflow-hidden p-2">
            <div className="min-h-0 min-w-0 flex-1 overflow-hidden rounded-[8px] bg-white">
              {activeChatId ? (
                <AppChat
                  chatId={activeChatId}
                  flowId={flowId}
                  flowType={numericFlowType}
                  apiVersion={apiVersion}
                />
              ) : historyLoaded ? (
                <ChatEmptyState onNewChat={createNewChat} />
              ) : null}
            </div>
          </div>

        </div>
      </div>
    </StandaloneChatContext.Provider>
  );
}
