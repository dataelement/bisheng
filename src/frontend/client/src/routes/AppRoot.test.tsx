import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import AppRoot from './AppRoot';

const mockNavigate = jest.fn();
const mockCreate = jest.fn();
const mockSwitch = jest.fn();
const mockSystemMenu = jest.fn();
const mockRows = jest.fn();
let mockMobile = false;
let mockCompact = true;
let mockSidebarVisible = true;
let mockMerged = true;
let mockReturnTo = '/square?type=apps';
const mockHeader = { title: 'New conversation', conversationId: 'old', flowId: 'assistant', flowType: 5, hideShare: true };

jest.mock('react-router-dom', () => ({
  useLocation: () => ({ pathname: '/app/old/assistant/5', search: '', state: { appSurfaceReturn: mockReturnTo } }),
  useNavigate: () => mockNavigate,
  useParams: () => ({ fid: 'assistant', type: '5' }),
  Outlet: () => <div>Conversation content</div>,
}));
jest.mock('react-activation', () => ({ useUnactivate: () => undefined }));
jest.mock('recoil', () => ({
  useRecoilState: (key: string) => {
    const [value, setValue] = jest.requireActual('react').useState(mockSidebarVisible);
    return key === 'sidebar' ? [value, setValue] : [[], mockRows];
  },
  useRecoilValue: (key: string) => key === 'header' ? (mockMerged ? mockHeader : null) : key === 'conversation' ? mockHeader : false,
  useSetRecoilState: () => mockSystemMenu,
}));
jest.mock('~/store', () => ({ __esModule: true, default: {
  chatMobileNavHiddenState: 'navHidden', chatMobileHeaderState: 'header',
  mobileSystemMenuOpenState: 'systemMenu', conversationByIndex: () => 'conversation',
} }));
jest.mock('~/pages/appChat/store/appSidebarAtoms', () => ({ appConversationsState: 'rows', sidebarVisibleState: 'sidebar' }));
jest.mock('~/pages/appChat/store/atoms', () => ({ currentChatState: 'chat' }));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useAuthContext: () => ({ isAuthenticated: true }),
  useMediaQuery: () => mockCompact,
  usePrefersMobileLayout: () => mockMobile,
  useNewConvo: () => ({ newConversation: jest.fn() }),
}));
jest.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ setQueryData: jest.fn() }) }));
jest.mock('~/types/chat', () => ({ QueryKeys: { messages: 'messages' }, Constants: { NEW_CONVO: 'new' } }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' '), generateUUID: () => 'fresh' }));
jest.mock('~/components/Banners', () => ({ Banner: () => null }));
jest.mock('~/components/Nav', () => ({ MobileNav: jest.requireActual('~/components/Nav/MobileNav').default }));
jest.mock('~/components/Nav/NavToggle', () => ({ __esModule: true, default: () => null }));
jest.mock('~/components/Nav/MobileChatHistoryDropdown', () => ({ MobileChatHistoryDropdown: () => null }));
jest.mock('~/components/Share/ShareChat', () => ({ __esModule: true, default: () => null }));
jest.mock('~/pages/appChat/SideNav', () => ({ SideNav: () => <div>App sidebar</div> }));
jest.mock('~/pages/appChat/hooks/useAppSidebar', () => ({ useAppSidebar: () => ({
  groups: [{ label: 'Today', conversations: [{ id: 'old', title: 'Previous conversation' }] }],
  activeConversationId: 'old', switchConversation: mockSwitch, createNewChat: mockCreate,
  shareApp: jest.fn(), fetchConversations: jest.fn(), currentApp: { name: 'Acceptance assistant', description: 'Description' },
}) }));
jest.mock('~/components/Avator', () => ({ __esModule: true, default: () => null }));
jest.mock('~/pages/appChat/components/AppSwitcherDropdown', () => ({ AppSwitcherDropdown: () => null }));
jest.mock('~/pages/appChat/components/AppSidebarConvoItem', () => ({
  AppSidebarConvoItem: ({ conv, onClick }: { conv: { title: string }; onClick: () => void }) => <button onClick={onClick}>{conv.title}</button>,
}));
jest.mock('~/components/ui/Tooltip2', () => ({ Tooltip: () => null, TooltipProvider: () => null, TooltipTrigger: () => null, TooltipContent: () => null }));
jest.mock('bisheng-icons', () => ({ Outlined: { SidebarMenu: () => null, Plus: () => null, Down: () => null } }));

beforeEach(() => {
  mockMobile = false; mockCompact = true; mockSidebarVisible = true; mockMerged = true;
  localStorage.clear(); sessionStorage.clear(); mockReturnTo = '/square?type=apps';
});

it.each([true, false])('toggles the compact desktop app sidebar from visibility %s', (visible) => {
  mockSidebarVisible = visible;
  render(<AppRoot />);
  const menu = screen.getByTestId('mobile-header-left-action');
  expect(menu).toHaveAttribute('aria-expanded', String(visible));
  fireEvent.click(menu);
  expect(menu).toHaveAttribute('aria-expanded', String(!visible));
  fireEvent.click(menu);
  expect(menu).toHaveAttribute('aria-expanded', String(visible));
  expect(mockSystemMenu).toHaveBeenCalledTimes(0);
});

it.each([true, false])('preserves app sidebar visibility %s when starting with plus', (visible) => {
  mockSidebarVisible = visible;
  render(<AppRoot />);
  fireEvent.click(screen.getByTestId('mobile-header-new-chat-button'));
  expect(screen.getByTestId('mobile-header-left-action')).toHaveAttribute('aria-expanded', String(visible));
  expect(screen.getByText('App sidebar').parentElement).toHaveClass(visible ? 'w-[240px]' : 'w-0');
  expect(mockNavigate).toHaveBeenCalledWith('/app/fresh/assistant/5', { state: { appSurfaceReturn: '/square?type=apps' } });
  expect(mockRows).toHaveBeenCalledTimes(1);
});

it('keeps history stable when the native host evaluates modal presentation', async () => {
  const view = render(<AppRoot />);
  fireEvent.click(screen.getByRole('button', { name: 'New conversation' }));
  // Window expansion crosses the compact-header breakpoint: content 900px, window 1200px.
  const widths: number[] = [];
  for (let frame = 0; frame < 6; frame++) {
    const windowModal = document.querySelector('body > [role="dialog"][aria-modal="true"]');
    const width = windowModal ? 1200 : 900;
    widths.push(width);
    mockCompact = width <= 1023;
    await act(async () => { view.rerender(<AppRoot />); });
  }
  expect(widths).toEqual([900, 900, 900, 900, 900, 900]);
  expect(screen.getByRole('region', { name: 'com_app_chat_sidebar_title' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'New conversation' })).toHaveAttribute('aria-expanded', 'true');
});

it('closes history and toggles the app sidebar with the menu button', () => {
  render(<AppRoot />);
  fireEvent.click(screen.getByRole('button', { name: 'New conversation' }));
  const menu = screen.getByTestId('mobile-header-left-action');
  expect(menu.className).not.toContain('pointer-events-none');
  fireEvent.click(menu);
  expect(screen.queryByRole('region')).toBeNull();
  expect(menu).toHaveAttribute('aria-expanded', 'false');
});

it.each(['plus', 'history'])('closes history and preserves the sidebar when creating through %s', (entry) => {
  render(<AppRoot />);
  fireEvent.click(screen.getByRole('button', { name: 'New conversation' }));
  fireEvent.click(entry === 'plus' ? screen.getByTestId('mobile-header-new-chat-button') : screen.getByRole('button', { name: 'com_knowledge_start_new_chat' }));
  expect(screen.queryByRole('region')).toBeNull();
  expect(screen.getByTestId('mobile-header-left-action')).toHaveAttribute('aria-expanded', 'true');
  if (entry === 'history') expect(mockCreate).toHaveBeenCalledTimes(1);
  else expect(mockNavigate).toHaveBeenCalledTimes(1);
});

it('switches conversations and closes history', () => {
  render(<AppRoot />);
  fireEvent.click(screen.getByRole('button', { name: 'New conversation' }));
  fireEvent.click(screen.getByRole('button', { name: 'Previous conversation' }));
  expect(mockSwitch).toHaveBeenCalledWith({ id: 'old', title: 'Previous conversation' });
  expect(screen.queryByRole('region')).toBeNull();
});

it('returns keyboard focus to the title on Escape and releases its listener', () => {
  const view = render(<AppRoot />);
  const title = screen.getByRole('button', { name: 'New conversation' });
  title.focus(); fireEvent.click(title);
  screen.getByRole('button', { name: 'Previous conversation' }).focus();
  view.rerender(<AppRoot />);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('region')).toBeNull(); expect(title).toHaveFocus();
  fireEvent.click(title); view.unmount();
  const escape = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
  document.dispatchEvent(escape);
  expect(escape.defaultPrevented).toBe(false);
});

it('retains the mobile system menu destination', () => {
  mockMobile = true;
  render(<AppRoot />);
  fireEvent.click(screen.getByTestId('mobile-header-left-action'));
  expect(mockSystemMenu).toHaveBeenCalledWith(true);
});

it('retains the app sidebar toggle before a conversation title is available', () => {
  mockMerged = false;
  render(<AppRoot />);
  const menu = screen.getByTestId('mobile-header-left-action');
  fireEvent.click(menu);
  expect(menu).toHaveAttribute('aria-expanded', 'false');
});

// The compact header owns a visible return action throughout title hydration.
it.each([true, false])('keeps return available as the title loads with sidebar=%s', (visible) => {
  mockSidebarVisible = visible;
  mockMerged = false;
  const view = render(<AppRoot />);
  expect(screen.getByRole('button', { name: 'com_ui_go_back' })).toBeVisible();
  mockMerged = true;
  view.rerender(<AppRoot />);
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  expect(mockNavigate).toHaveBeenCalledWith('/square?type=apps', { replace: false });
});

it('keeps return available on mobile after a title loads', () => {
  mockMobile = true;
  render(<AppRoot />);
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  expect(mockNavigate).toHaveBeenCalledWith('/square?type=apps', { replace: false });
});

it.each(['/square?type=apps', '/apps', '/apps/explore'])('returns to %s with history expanded', (target) => {
  mockReturnTo = target;
  render(<AppRoot />);
  fireEvent.click(screen.getByRole('button', { name: 'New conversation' }));
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  expect(mockNavigate).toHaveBeenCalledWith(target, { replace: target === '/apps' });
});
