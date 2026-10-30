import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import Subscription from './index';

let mockMobile = true;
let mockEmpty = false;
let mockLoading = false;
let mockError: Error | null = null;
const mockMenuOpen = jest.fn();
const mockToast = jest.fn();
const mockDetail = jest.fn(async (id: string) => ({ id, name: `Channel ${id}`, actions: ['visible'], subscription_status: 'subscribed' }));
const channel = { id: 'one', name: 'Channel one', unreadCount: 0, source_list: [], subChannels: [] };
const mockUser = { username: 'reader', plugins: ['subscription'] };
const localize = (key: string) => key;
const noop = () => undefined;

jest.mock('~/hooks', () => ({ useLocalize: () => localize, usePrefersMobileLayout: () => mockMobile, useWorkbenchMenuNames: () => ({ channel: 'Subscription' }) }));
jest.mock('~/hooks/AuthContext', () => ({ useAuthContext: () => ({ user: mockUser, isUserLoading: false }) }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock('~/hooks/useEffectiveQuota', () => ({ useEffectiveQuota: () => ({ isOverQuota: () => false }) }));
jest.mock('react-activation', () => ({ useActivate: noop, useUnactivate: noop }));
jest.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({}) }));
jest.mock('recoil', () => ({ useSetRecoilState: () => mockMenuOpen, useRecoilValue: () => false }));
jest.mock('~/store', () => ({ __esModule: true, default: { mobileSystemMenuOpenState: 'menu' } }));
jest.mock('~/store/subscriptionLayout', () => ({ subscriptionMobileChannelDropdownOpenState: 'dropdown' }));
jest.mock('./hooks/useChannelLists', () => ({ useChannelLists: () => ({ created: { data: mockEmpty ? [] : [channel], isFetched: !mockLoading }, subscribed: { data: [], isFetched: !mockLoading }, error: mockError, retry: noop }) }));
jest.mock('./hooks/useChannelStateRefresh', () => ({ refreshChannelState: noop, useChannelAccessGuard: noop, useChannelStateRefresh: noop }));
jest.mock('~/api/channels', () => ({ getChannelDetailApi: (id: string) => mockDetail(id), SortType: { RECENT_UPDATE: 'recent' }, ChannelRole: { MEMBER: 'member' } }));
jest.mock('~/components/CopyShareLinkButton', () => ({ buildClientShareUrl: (path: string) => path }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => <div role="status">Loading</div> }));
jest.mock('~/components/ApiRequestFailure', () => ({ ApiRequestFailure: ({ error }: { error: Error }) => <div role="alert">{error.message}</div> }));
jest.mock('~/mock/demo/DemoTag', () => ({ DemoTag: () => null }));
jest.mock('~/pages/knowledge/knowledgeUtils', () => ({ formatTimeCard: () => '' }));
jest.mock('~/utils', () => ({ cn: (...parts: unknown[]) => parts.filter(Boolean).join(' ') }));
jest.mock('bisheng-icons', () => ({ Outlined: new Proxy({}, { get: () => () => <svg /> }) }));
jest.mock('@bisheng/ui', () => ({
  Button: ({ children, onClick, ...props }: { children: ReactNode; onClick: () => void }) => <button {...props} onClick={onClick}>{children}</button>,
  Badge: () => null,
  Tooltip: ({ children }: { children: ReactNode }) => children,
}));
jest.mock('./ChannelLayout', () => ({ ChannelLayout: ({ channel: selected, onChannelSelect }: { channel: typeof channel; onChannelSelect: (value: null) => void }) => <div><h1>{selected.name} articles</h1><button onClick={() => onChannelSelect(null)}>Home</button></div> }));
jest.mock('./ChannelDiscoveryHome', () => ({ ChannelDiscoveryHome: () => <h1>Discover channels</h1> }));
jest.mock('../ChannelSquare', () => ({ __esModule: true, default: () => <h1>Channel square</h1> }));
jest.mock('./ChannelSquareTabs', () => ({ ChannelSquareTabs: ({ onChannelClick, onSquareClick }: { onChannelClick: () => void; onSquareClick: () => void }) => <nav><button onClick={onChannelClick}>Channels</button><button onClick={onSquareClick}>Square</button></nav> }));
jest.mock('./ChannelPreviewDrawer', () => ({ ChannelPreviewDrawer: () => null }));
jest.mock('./Article/FullScreenArticle', () => ({ __esModule: true, default: () => null }));
jest.mock('./Sidebar/ChannelSidebar', () => ({ ChannelSidebar: () => null }));

function Harness() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output>{location.pathname}{location.search}</output><button onClick={() => navigate(-1)}>Browser back</button><Subscription /></>;
}
function renderPage(path = '/channel') {
  return render(<MemoryRouter initialEntries={[path]}><Harness /></MemoryRouter>);
}
beforeEach(() => { mockMobile = true; mockEmpty = false; mockLoading = false; mockError = null; });

it('lands on the mobile home without auto-selecting, opens a channel and returns home', async () => {
  renderPage();
  expect(screen.getByRole('heading', { name: 'com_subscription.created_by_me' })).toBeInTheDocument();
  expect(screen.queryByText('Channel one articles')).not.toBeInTheDocument();
  expect(mockDetail).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /Channel one/ }));
  expect(await screen.findByRole('heading', { name: 'Channel one articles' })).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('/channel/one');
  fireEvent.click(screen.getByRole('button', { name: 'Home' }));
  expect(await screen.findByRole('heading', { name: 'com_subscription.created_by_me' })).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('/channel');
});

it('supports a direct channel link and browser Back from a home card', async () => {
  renderPage('/channel/one');
  expect(await screen.findByRole('heading', { name: 'Channel one articles' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Home' }));
  fireEvent.click(await screen.findByRole('button', { name: /Channel one/ }));
  await screen.findByRole('heading', { name: 'Channel one articles' });
  fireEvent.click(screen.getByRole('button', { name: 'Browser back' }));
  expect(await screen.findByRole('heading', { name: 'com_subscription.created_by_me' })).toBeInTheDocument();
});

it('removes the square switcher but keeps global navigation and channel creation', async () => {
  renderPage();
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'com_nav_open_sidebar' }));
  expect(mockMenuOpen).toHaveBeenCalledWith(true);
  fireEvent.click(screen.getByRole('button', { name: 'com_subscription.create_channel' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('/channel/create'));
});

it('retains an exit to home for legacy square deep links', async () => {
  renderPage('/channel?square=1');
  expect(await screen.findByRole('heading', { name: 'Channel square' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  expect(await screen.findByRole('heading', { name: 'com_subscription.created_by_me' })).toBeInTheDocument();
});

it('keeps discovery, loading and request failure states distinct', () => {
  mockEmpty = true;
  const page = renderPage();
  expect(screen.getByRole('heading', { name: 'Discover channels' })).toBeInTheDocument();
  mockLoading = true;
  page.rerender(<MemoryRouter><Harness /></MemoryRouter>);
  expect(screen.getByText('Loading')).toBeInTheDocument();
  mockLoading = false;
  mockError = new Error('Channels unavailable');
  page.rerender(<MemoryRouter><Harness /></MemoryRouter>);
  expect(screen.getByRole('alert')).toHaveTextContent('Channels unavailable');
});

it('preserves the desktop home and its create action', () => {
  mockMobile = false;
  renderPage();
  expect(screen.getByRole('heading', { name: 'Subscription' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Channel one/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'com_nav_open_sidebar' })).not.toBeInTheDocument();
});
