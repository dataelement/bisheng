import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AliveScope } from 'react-activation';
import { createMemoryRouter, Link, Navigate, Outlet, RouterProvider, useLocation } from 'react-router-dom';
import MainLayout from '~/layouts/MainLayout';
import AppRoot from '~/routes/AppRoot';
import AppChatEntry from '~/pages/appChat/AppChatEntry';
import ExplorePlaza from './explore';
import { readAppChatReturnTo } from '~/pages/appChat/appChatOrigin';

const mockUser = { id: 'tester' };
const mockSetState = jest.fn();
let mockHistory: Array<{ chat_id: string }> = [];
let mockMobile = false;
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: mockUser, isAuthenticated: true }),
  useLocalize: () => (key: string) => key,
  useWorkbenchMenuNames: () => ({ apps: 'Apps' }),
  usePrefersMobileLayout: () => mockMobile,
  useMediaQuery: (query: string) => mockMobile && query === '(max-width: 1023px)',
  useScrollRevealRef: () => ({ current: null }),
}));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: {} }) }));
jest.mock('~/components/Chat/desktopEmbedding', () => ({ isDesktopEmbedded: () => true }));
jest.mock('~/api/apps', () => ({
  getBysConfigApi: async () => ({ data: {} }),
  getChatOnlineApi: async () => ({ list: [{ id: 'assistant', flow_type: 5, name: 'Assistant' }], hasMore: false }),
  getAppConversationsApi: async () => ({ data: { list: mockHistory } }),
}));
jest.mock('recoil', () => ({
  useRecoilState: (key: string) => jest.requireActual('react').useState(key === 'config' ? {} : key === 'sidebar'),
  useRecoilValue: () => null,
  useSetRecoilState: () => mockSetState,
}));
jest.mock('~/store', () => ({ __esModule: true, default: { mobileSystemMenuOpenState: 'menu' } }));
jest.mock('~/pages/appChat/store/atoms', () => ({ bishengConfState: 'config', currentChatState: 'chat' }));
jest.mock('~/pages/appChat/store/appSidebarAtoms', () => ({ sidebarVisibleState: 'sidebar', appConversationsState: 'conversations' }));
jest.mock('~/pages/appChat/hooks/useAppSidebar', () => ({ useAppSidebar: () => ({ groups: [], currentApp: { name: 'Assistant' } }) }));
jest.mock('~/pages/appChat/components/AppSwitcherDropdown', () => ({ AppSwitcherDropdown: () => null }));
jest.mock('~/pages/appChat/components/AppSidebarConvoItem', () => ({ AppSidebarConvoItem: () => null }));
jest.mock('~/pages/appChat/components/ChatEmptyState', () => ({ ChatEmptyState: () => null }));
jest.mock('~/components/Avator', () => ({ __esModule: true, default: () => null }));
jest.mock('~/components/Banners', () => ({ Banner: () => null }));
jest.mock('~/components/Nav', () => ({ MobileNav: ({ appSurfaceBackAction }: { appSurfaceBackAction: () => void }) => <button onClick={appSurfaceBackAction}>Mobile back</button> }));
jest.mock('~/components/Nav/MobileSidebarHeaderTabs', () => ({ MobileSidebarHeaderTabs: () => null }));
jest.mock('~/components/Nav/MobileAppHistoryDropdown', () => ({ MobileAppHistoryDropdown: () => null }));
jest.mock('~/components/Nav/NavToggle', () => ({ __esModule: true, default: () => null }));
jest.mock('~/components/Chat/Input/AgentToolSelector', () => ({ useAgentToolPreferences: () => {} }));
jest.mock('~/layouts/DesktopShellBridge', () => ({ DesktopShellBridge: () => null }));
jest.mock('~/layouts/WorkbenchAccessGuard', () => ({ __esModule: true, default: () => null }));
jest.mock('~/layouts/WorkbenchSidebar', () => ({ WorkbenchSidebar: () => null }));
jest.mock('~/layouts/UserPopMenu', () => ({ UserPopMenu: () => null }));
jest.mock('~/layouts/useWorkbenchNavLinks', () => ({ useWorkbenchNavLinks: () => ({ links: [] }) }));
jest.mock('~/components/ui/Button', () => ({ Button: () => null }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));
jest.mock('~/components/ui/Dialog', () => ({ Dialog: () => null, DialogContent: () => null, DialogFooter: () => null, DialogHeader: () => null, DialogTitle: () => null }));
jest.mock('~/components/ui/Tooltip2', () => ({
  TooltipProvider: ({ children }: React.PropsWithChildren) => children,
  Tooltip: ({ children }: React.PropsWithChildren) => children,
  TooltipTrigger: ({ children }: React.PropsWithChildren) => children,
  TooltipContent: () => null,
}));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/common', () => ({ NotificationSeverity: {} }));
jest.mock('~/utils', () => ({ cn: (...args: unknown[]) => args.filter(Boolean).join(' '), generateUUID: () => 'fresh-chat' }));
jest.mock('./appUtils', () => ({ getAppShareUrl: () => '' }));
jest.mock('~/components/illustrations', () => ({ EmptyStateIllustration: () => null }));
jest.mock('./components/AppSearchBar', () => ({ AppSearchBar: () => null }));
jest.mock('./components/AgentNavigation', () => ({ AgentNavigation: ({ onCategoryChange }: { onCategoryChange: (id: number) => void }) => <button onClick={() => onCategoryChange(28)}>Category</button> }));
jest.mock('./components/AgentCard', () => ({ AgentCard: ({ agent, onStartChat }: { agent: unknown; onStartChat: (agent: unknown) => void }) => <button onClick={() => onStartChat(agent)}>Open assistant</button> }));

// The router only needs request metadata; these routes have no loaders.
class NavigationRequest {
  constructor(public url: string, public init: RequestInit) {}
  get signal() { return this.init.signal; }
  get method() { return this.init.method || 'GET'; }
}
Object.defineProperty(globalThis, 'Request', { configurable: true, value: NavigationRequest });
Object.defineProperty(globalThis, 'IntersectionObserver', { configurable: true, value: class { observe() {} disconnect() {} } });

function Controls() {
  const location = useLocation();
  return <nav><output data-testid="address">{location.pathname}{location.search}</output>
    <Link to="/square?type=apps">Square</Link>
    <Link to="/app/center-chat/assistant/5?returnTo=%2Fapps" state={{ appSurfaceReturn: '/apps' }}>Center chat</Link>
  </nav>;
}
function Chat() {
  const location = useLocation();
  return <output data-testid="chat-address">{location.pathname}</output>;
}
function LegacyExploreRoute() {
  return mockMobile ? <ExplorePlaza /> : <Navigate to="/square?type=apps" replace />;
}
function open(initial = '/square?type=apps') {
  const router = createMemoryRouter([{
    element: <><Controls /><AliveScope><Outlet /></AliveScope></>,
    children: [{ element: <MainLayout />, children: [
      { path: 'square', element: <ExplorePlaza /> },
      { path: 'apps/explore', element: <LegacyExploreRoute /> },
      { path: 'apps', element: <h1>App center</h1> },
      { path: 'app', element: <AppRoot />, children: [
        { path: ':fid/:type', element: <AppChatEntry /> },
        { path: ':conversationId/:fid/:type', element: <Chat /> },
      ] },
    ] }],
  }], { initialEntries: [initial] });
  render(<RouterProvider router={router} />);
}
async function enterFromSquare() {
  fireEvent.click(await screen.findByRole('button', { name: 'Category' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Open assistant' }));
  const chatId = mockHistory[0]?.chat_id ?? 'fresh-chat';
  await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent(`/app/${chatId}/assistant/5`));
  await waitFor(() => expect(screen.getByTestId('chat-address')).toHaveTextContent(`/app/${chatId}/assistant/5`));
}
beforeEach(() => { sessionStorage.clear(); mockHistory = []; mockMobile = false; });

it.each([false, true])('returns a square conversation to the apps tab (history=%s)', async hasHistory => {
  if (hasHistory) mockHistory = [{ chat_id: 'existing-chat' }];
  open();
  await enterFromSquare();
  expect(readAppChatReturnTo(hasHistory ? 'existing-chat' : 'fresh-chat')).toBe('/square?type=apps');
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent('/square?type=apps'));
  await screen.findByRole('button', { name: 'Category' });
});

it('uses the square entry after previously opening an app-center conversation', async () => {
  open('/app/center-chat/assistant/5?returnTo=%2Fapps');
  await screen.findByTestId('chat-address');
  fireEvent.click(screen.getByRole('link', { name: 'Square' }));
  await screen.findByRole('button', { name: 'Category' });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 1100)); });
  await enterFromSquare();
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent('/square?type=apps'));
  await screen.findByRole('button', { name: 'Category' });
});

it('returns an app-center conversation to the app center', async () => {
  open('/app/center-chat/assistant/5?returnTo=%2Fapps');
  await screen.findByTestId('chat-address');
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  await screen.findByRole('heading', { name: 'App center' });
  expect(screen.getByTestId('address')).toHaveTextContent(/^\/apps$/);
});

it('keeps the mobile explore return target', async () => {
  mockMobile = true;
  open('/apps/explore');
  await enterFromSquare();
  expect(readAppChatReturnTo('fresh-chat')).toBe('/apps/explore');
  fireEvent.click(screen.getByRole('button', { name: 'Mobile back' }));
  await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent(/^\/apps\/explore$/));
  await screen.findByRole('button', { name: 'Category' });
});
