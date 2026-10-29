import React, { useEffect, useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AliveScope } from 'react-activation';
import { createMemoryRouter, Link, Outlet, RouterProvider, useLocation, useNavigate, useParams } from 'react-router-dom';
import MainLayout from './MainLayout';
import Subscription from '~/pages/Subscription';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
let mockMobile = false;
let mockEmbedded = true;
const mockUser = { id: 'test-user', username: 'tester' };
const mockSetRecoil = jest.fn();
const mockLogout = jest.fn();
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: mockUser, logout: mockLogout, isUserLoading: false }),
  useLocalize: () => (key: string) => key,
  useWorkbenchMenuNames: () => ({ channel: 'Channel', apps: 'Apps' }),
  usePrefersMobileLayout: () => mockMobile,
  useScrollRevealRef: () => ({ current: null }),
}));
jest.mock('~/components/Chat/desktopEmbedding', () => ({ isDesktopEmbedded: () => mockEmbedded }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: {} }) }));
jest.mock('~/api/apps', () => ({ getBysConfigApi: async () => ({ data: {} }) }));
jest.mock('~/pages/appChat/store/atoms', () => ({ bishengConfState: 'config' }));
jest.mock('~/store', () => ({ __esModule: true, default: { mobileSystemMenuOpenState: 'mobile' } }));
jest.mock('recoil', () => ({ useRecoilState: (key: string) => jest.requireActual('react').useState(key === 'config' ? {} : false), useSetRecoilState: () => mockSetRecoil, useRecoilValue: () => false }));
jest.mock('~/components/Chat/Input/AgentToolSelector', () => ({ useAgentToolPreferences: () => {} }));
jest.mock('~/utils', () => ({ cn: (...args: unknown[]) => args.filter(Boolean).join(' ') }));
jest.mock('./DesktopShellBridge', () => ({ DesktopShellBridge: () => null }));
jest.mock('./WorkbenchAccessGuard', () => ({ __esModule: true, default: () => null }));
jest.mock('./WorkbenchSidebar', () => ({ WorkbenchSidebar: () => null }));
jest.mock('./UserPopMenu', () => ({ UserPopMenu: () => null }));
jest.mock('./useWorkbenchNavLinks', () => ({ useWorkbenchNavLinks: () => ({ links: [] }) }));
jest.mock('~/components/ui/Button', () => ({ Button: () => null }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));
jest.mock('~/components/ui/Dialog', () => ({ Dialog: () => null, DialogContent: () => null, DialogFooter: () => null, DialogHeader: () => null, DialogTitle: () => null }));

jest.mock('~/hooks/AuthContext', () => ({ useAuthContext: () => ({ user: mockUser, isUserLoading: false }) }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/common', () => ({ NotificationSeverity: { WARNING: 'warning', INFO: 'info' } }));
jest.mock('~/components/CopyShareLinkButton', () => ({ buildClientShareUrl: (path: string) => path }));
jest.mock('~/hooks/useEffectiveQuota', () => ({ useEffectiveQuota: () => ({ isOverQuota: () => false }) }));
jest.mock('~/store/subscriptionLayout', () => ({ subscriptionMobileChannelDropdownOpenState: 'dropdown' }));
jest.mock('~/api/channels', () => ({
  SortType: { RECENT_UPDATE: 'recent_update' }, ChannelRole: { MEMBER: 'member' },
  getChannelsApi: async ({ type }: { type: string }) => type === 'created' ? [{ id: 'one', name: 'one' }, { id: 'two', name: 'two' }] : [],
  getChannelDetailApi: async (id: string) => ({ id, name: id, actions: ['visible'], creator_name: 'someone', visibility: 'public' }),
}));
jest.mock('~/pages/ChannelSquare', () => ({ __esModule: true, default: () => <h1>Square</h1> }));
jest.mock('~/pages/Subscription/ChannelLayout', () => ({ ChannelLayout: ({ channel }: { channel: { name: string } }) => <h1>{channel.name}</h1> }));
jest.mock('~/pages/Subscription/ChannelHomePage', () => ({ ChannelHomePage: ({ onChannelSelect }: { onChannelSelect: (channel: { id: string; name: string }) => void }) => <section><h1>Channel home</h1><button onClick={() => onChannelSelect({ id: 'one', name: 'one' })}>Open one</button></section> }));
jest.mock('~/pages/Subscription/ChannelDiscoveryHome', () => ({ ChannelDiscoveryHome: () => <h1>Discovery</h1> }));
jest.mock('~/pages/Subscription/ChannelSquareTabs', () => ({ ChannelSquareTabs: () => null }));
jest.mock('~/pages/Subscription/ChannelPreviewDrawer', () => ({ ChannelPreviewDrawer: () => null }));
jest.mock('~/pages/Subscription/Article/FullScreenArticle', () => ({ __esModule: true, default: () => null }));
jest.mock('~/pages/Subscription/Sidebar/ChannelSidebar', () => ({ ChannelSidebar: () => null }));
jest.mock('@bisheng/ui', () => ({ Button: () => null, Tooltip: () => null }));

function Controls() {
  const location = useLocation(); const navigate = useNavigate();
  return <nav><output data-testid="address">{location.pathname}{location.search}</output>
    {['/channel', '/channel/one', '/channel/two', '/channel/create', '/channel/two/settings', '/channel/share/three?square=1', '/channel?square=1', '/c/new'].map(path => <Link key={path} to={path}>{path}</Link>)}
    <button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate(1)}>Forward</button>
  </nav>;
}
function ChannelPage() {
  const location = useLocation(); const { channelId } = useParams();
  const [active, setActive] = useState(channelId || 'Channel home');
  useEffect(() => { setActive(channelId || 'Channel home'); }, [channelId]);
  return <section data-testid="channel-page"><h1>{active}</h1><output>{location.pathname}{location.search}</output></section>;
}
function SettingsPage() {
  const { channelId } = useParams();
  return <h1>{channelId ? `Settings ${channelId}` : 'Create channel'}</h1>;
}
function ChatPage() {
  const [draft, setDraft] = useState('');
  return <input aria-label="Draft" value={draft} onChange={event => setDraft(event.target.value)} />;
}
// These routes have no loaders or submissions; only navigation request metadata is used.
class NavigationRequest {
  constructor(public url: string, public init: RequestInit) {}
  get signal() { return this.init.signal; }
  get method() { return this.init.method || 'GET'; }
}
Object.defineProperty(globalThis, 'Request', { configurable: true, value: NavigationRequest });
function open(initial = '/channel', actualSubscription = false) {
  const channelPage = actualSubscription ? <Subscription /> : <ChannelPage />;
  const router = createMemoryRouter([{
    element: <><Controls /><AliveScope><Outlet /></AliveScope></>,
    children: [{ element: <MainLayout />, children: [
      { path: 'channel', element: channelPage },
      { path: 'channel/:channelId', element: channelPage },
      { path: 'channel/share/:channelId', element: channelPage },
      { path: 'channel/create', element: <SettingsPage /> },
      { path: 'channel/:channelId/settings', element: <SettingsPage /> },
      { path: 'c/new', element: <ChatPage /> },
    ] }],
  }], { initialEntries: [initial] });
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } })}><RouterProvider router={router} /></QueryClientProvider>);
}
async function go(path: string, title: string) {
  fireEvent.click(screen.getByRole('link', { name: path }));
  await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent(path));
  await waitFor(() => expect(screen.getByRole('heading', { name: title })).toBeVisible());
}
beforeEach(() => { mockMobile = false; mockEmbedded = true; });
it.each([[false, true], [false, false], [true, false]])('follows list/detail/settings navigation (mobile=%s, embedded=%s)', async (mobile, embedded) => {
  mockMobile = mobile; mockEmbedded = embedded; open();
  await screen.findByRole('heading', { name: 'Channel home' });
  await go('/channel/one', 'one'); await go('/channel/two', 'two');
  await go('/channel/two/settings', 'Settings two'); await go('/channel/create', 'Create channel');
  await go('/channel', 'Channel home'); await go('/channel/share/three?square=1', 'three');
  await go('/channel?square=1', 'Channel home');
  expect(screen.getByTestId('channel-page')).toHaveTextContent('/channel?square=1');
  await go('/channel', 'Channel home');
  expect(screen.getByTestId('channel-page').querySelector('output')).toHaveTextContent(/^\/channel$/);
});
it('follows history back and forward', async () => {
  open(); await go('/channel/one', 'one'); await go('/channel/two', 'two');
  fireEvent.click(screen.getByRole('button', { name: 'Back' }));
  await screen.findByRole('heading', { name: 'one' });
  fireEvent.click(screen.getByRole('button', { name: 'Back' }));
  await screen.findByRole('heading', { name: 'Channel home' });
  fireEvent.click(screen.getByRole('button', { name: 'Forward' }));
  await screen.findByRole('heading', { name: 'one' });
});
it('restores the chat draft while channel routes follow the current address', async () => {
  open('/c/new');
  fireEvent.change(await screen.findByRole('textbox', { name: 'Draft' }), { target: { value: 'keep my draft' } });
  await go('/channel/one', 'one'); await go('/channel', 'Channel home');
  fireEvent.click(screen.getByRole('link', { name: '/c/new' }));
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Draft' })).toHaveValue('keep my draft'));
});

it.each(['/channel', '/channel/two', '/channel/create'])('synchronizes cached channel after returning to %s', async target => {
  open(); await go('/channel/one', 'one');
  fireEvent.click(screen.getByRole('link', { name: '/c/new' }));
  await screen.findByRole('textbox', { name: 'Draft' });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 1100)); });
  await go(target, target === '/channel' ? 'Channel home' : target.endsWith('create') ? 'Create channel' : 'two');
  await go('/channel/two/settings', 'Settings two');
});

it('returns the actual subscription from a cached detail to its home', async () => {
  open('/channel', true);
  fireEvent.click(await screen.findByRole('button', { name: 'Open one' }));
  await screen.findByRole('heading', { name: 'one' });
  fireEvent.click(screen.getByRole('link', { name: '/c/new' }));
  await screen.findByRole('textbox', { name: 'Draft' });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 1100)); });
  await go('/channel', 'Channel home');
  fireEvent.click(screen.getByRole('button', { name: 'Open one' }));
  await screen.findByRole('heading', { name: 'one' });
});
