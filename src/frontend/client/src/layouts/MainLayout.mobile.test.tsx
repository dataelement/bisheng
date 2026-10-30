import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AliveScope } from 'react-activation';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import MainLayout from './MainLayout';

let mockMobile = true;
let mockEmbedded = false;
const mockUser = { id: 'mobile-test', username: 'test' };
const noop = () => undefined;
const mockViewportListeners = new Set<() => void>();

// These routes have no loaders or submissions; only navigation metadata is read.
class NavigationRequest {
  constructor(public url: string, public init: RequestInit) {}
  get signal() { return this.init.signal; }
  get method() { return this.init.method || 'GET'; }
}
Object.defineProperty(globalThis, 'Request', { configurable: true, value: NavigationRequest });

jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: mockUser, isUserLoading: false, logout: noop }),
  useLocalize: () => (key: string) => key,
  useWorkbenchMenuNames: () => ({ apps: 'Applications' }),
  usePrefersMobileLayout: () => jest.requireActual('react').useSyncExternalStore(
    (listener: () => void) => { mockViewportListeners.add(listener); return () => { mockViewportListeners.delete(listener); }; },
    () => mockMobile,
  ),
  useScrollRevealRef: () => noop,
}));
jest.mock('~/components/Chat/desktopEmbedding', () => ({ isDesktopEmbedded: () => mockEmbedded }));
jest.mock('~/api/apps', () => ({ getBysConfigApi: async () => ({ data: {} }) }));
jest.mock('~/pages/appChat/store/atoms', () => ({ bishengConfState: 'config' }));
jest.mock('~/store', () => ({ __esModule: true, default: { mobileSystemMenuOpenState: 'menu' } }));
jest.mock('recoil', () => ({ useRecoilState: (key: string) => jest.requireActual('react').useState(key === 'config' ? {} : false) }));
jest.mock('~/components/Chat/Input/AgentToolSelector', () => ({ useAgentToolPreferences: noop }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('./DesktopShellBridge', () => ({ DesktopShellBridge: () => null }));
jest.mock('./WorkbenchAccessGuard', () => ({ __esModule: true, default: () => null }));
jest.mock('./WorkbenchSidebar', () => {
  const { Link } = jest.requireActual('react-router-dom');
  return { WorkbenchSidebar: ({ mobile, open, hidden, onOpenChange }: { mobile: boolean; open: boolean; hidden: boolean; onOpenChange: (value: boolean) => void }) =>
    !hidden && (!mobile || open) ? <nav aria-label="Workbench navigation"><Link to="/knowledge">Knowledge</Link><button onClick={() => onOpenChange(false)}>Close navigation</button></nav> : null };
});
jest.mock('~/components/ui/Button', () => ({ Button: () => null }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));
jest.mock('~/components/ui/Dialog', () => ({
  Dialog: () => null, DialogContent: () => null, DialogFooter: () => null, DialogHeader: () => null, DialogTitle: () => null,
}));

function DraftPage() {
  const [draft, setDraft] = useState('');
  return <input aria-label="Draft" value={draft} onChange={(event) => setDraft(event.target.value)} />;
}
function createHarness() {
  const router = createMemoryRouter([{ element: <AliveScope><Outlet /></AliveScope>, children: [
    { element: <MainLayout />, children: [
      { path: 'capabilities', element: <DraftPage /> },
      { path: 'knowledge', element: <h1>Knowledge page</h1> },
    ] },
  ] }], { initialEntries: ['/capabilities?type=tool'] });
  return { page: <RouterProvider router={router} /> };
}
beforeEach(() => { mockMobile = true; mockEmbedded = false; });

it('opens complete navigation from the narrow header without remounting the page draft', async () => {
  render(createHarness().page);
  const draft = screen.getByRole('textbox', { name: 'Draft' });
  fireEvent.change(draft, { target: { value: 'Keep my input' } });
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'com_nav_open_sidebar' }));
  expect(screen.getByRole('navigation', { name: 'Workbench navigation' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Close navigation' }));
  expect(screen.getByRole('textbox', { name: 'Draft' })).toBe(draft);
  expect(draft).toHaveValue('Keep my input');
  fireEvent.click(screen.getByRole('button', { name: 'com_nav_open_sidebar' }));
  fireEvent.click(screen.getByRole('link', { name: 'Knowledge' }));
  await waitFor(() => expect(screen.queryByRole('navigation')).not.toBeInTheDocument());
  expect(screen.getByRole('heading', { name: 'Knowledge page' })).toBeInTheDocument();
});

it('returns to narrow layout with the menu closed after a desktop round trip', async () => {
  const harness = createHarness();
  render(harness.page);
  fireEvent.change(screen.getByRole('textbox', { name: 'Draft' }), { target: { value: 'Resized draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'com_nav_open_sidebar' }));
  act(() => { mockMobile = false; mockViewportListeners.forEach(listener => listener()); });
  await waitFor(() => expect(screen.queryByRole('button', { name: 'com_nav_open_sidebar' })).not.toBeInTheDocument());
  act(() => { mockMobile = true; mockViewportListeners.forEach(listener => listener()); });
  await waitFor(() => expect(screen.queryByRole('navigation')).not.toBeInTheDocument());
  expect(screen.getByRole('textbox', { name: 'Draft' })).toHaveValue('Resized draft');
});

it('leaves navigation to the desktop host even when its content is narrow', () => {
  mockEmbedded = true;
  render(createHarness().page);
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'com_nav_open_sidebar' })).not.toBeInTheDocument();
});
