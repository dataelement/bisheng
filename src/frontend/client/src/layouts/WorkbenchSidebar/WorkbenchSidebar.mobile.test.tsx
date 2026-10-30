import type { ReactNode } from 'react';
import { useRef, useState } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { WorkbenchSidebar } from './WorkbenchSidebar';

const mockStartNewChat = jest.fn();
const mockFetchNextPage = jest.fn();
const mockRefetch = jest.fn(async () => ({}));
let mockGranted = true;
let mockError: Error | null = null;
const mockData = { pages: [{ conversations: [{ conversationId: 'one', title: 'First chat' }] }] };
const mockProject = { id: 'project-one', name: 'Project one', readonly: false, demoChats: [] };
const noop = () => undefined;

jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ isAuthenticated: true }),
  useLocalize: () => (key: string) => key,
  useNavScrolling: () => ({ containerRef: jest.requireActual('react').useRef(null), moveToTop: noop }),
  useScrollRevealRef: () => noop,
}));
jest.mock('~/hooks/queries/data-provider', () => ({
  useGetBsConfig: () => ({ data: {} }),
  useConversationsInfiniteQuery: () => ({ data: mockData, fetchNextPage: mockFetchNextPage,
    hasNextPage: true, isFetchingNextPage: false, isSuccess: !mockError, isError: !!mockError,
    error: mockError, refetch: mockRefetch }),
}));
jest.mock('~/components/Nav/NewChat', () => ({ useStartNewChat: () => mockStartNewChat }));
jest.mock('../useWorkbenchNavLinks', () => ({ useWorkbenchNavLinks: () => ({
  links: mockGranted ? [{ section: 'home', to: '/c/new' }] : [], showAdminEntry: false,
}) }));
jest.mock('./useSidebarEntries', () => ({
  useSidebarEntries: () => mockGranted ? [{ id: 'capabilities', to: '/capabilities', label: 'Capabilities', icon: <svg /> }] : [],
  splitSidebarEntries: (entries: unknown[]) => ({ shown: entries, more: [] }),
}));
jest.mock('./useSidebarProjects', () => ({ useSidebarProjects: () => [mockProject] }));
jest.mock('./projectsStore', () => ({
  useMockProjectChats: () => ({}), createMockProject: () => mockProject,
  deleteMockProject: noop, renameMockProject: noop,
}));
jest.mock('./ProjectNameDialog', () => ({ ProjectNameDialog: () => null }));
jest.mock('../UserPopMenu', () => ({ UserPopMenu: ({ onNavigate }: { onNavigate: () => void }) => <button onClick={onNavigate}>Account</button> }));
jest.mock('~/components/Conversations/Convo', () => ({ __esModule: true,
  default: ({ toggleNav }: { toggleNav: () => void }) => <button onClick={toggleNav}>First chat</button> }));
jest.mock('~/components/svg', () => ({ Spinner: () => null }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('~/utils/platformAdminUrl', () => ({ getPlatformAdminPanelUrl: () => '/admin' }));
jest.mock('~/api/request', () => ({ showApiError: noop }));
jest.mock('bisheng-icons', () => ({ Outlined: new Proxy({}, { get: () => () => <svg /> }) }));
jest.mock('@bisheng/ui', () => ({
  Button: ({ children, onClick, 'aria-label': label }: { children: ReactNode; onClick: () => void; 'aria-label': string }) => <button aria-label={label} onClick={onClick}>{children}</button>,
  Tooltip: ({ children }: { children: ReactNode }) => children,
  Dropdown: ({ children }: { children: ReactNode }) => children,
  DropdownItem: () => null,
  Alert: ({ description, actions }: { description: string; actions: { label: string; onClick: () => void }[] }) => <div role="alert">{description}{actions.map(action => <button key={action.label} onClick={action.onClick}>{action.label}</button>)}</div>,
}));

function Harness({ mobile = true }: { mobile?: boolean }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLElement | null>(null);
  return <MemoryRouter initialEntries={['/capabilities']}>
    <button ref={(node) => { triggerRef.current = node; }} onClick={() => setOpen(true)}>Open navigation</button>
    <input aria-label="Draft" defaultValue="" />
    <WorkbenchSidebar mobile={mobile} open={mobile && open} onOpenChange={setOpen} triggerRef={triggerRef} />
  </MemoryRouter>;
}

beforeEach(() => { mockGranted = true; mockError = null; });

it('uses the complete sidebar and retains project expansion and drafts after closing', async () => {
  render(<Harness />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox', { name: 'Draft' }), { target: { value: 'Keep this draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
  const dialog = screen.getByRole('dialog', { name: 'BISHENG' });
  expect(within(dialog).getByRole('link', { name: 'Capabilities' })).toBeVisible();
  expect(within(dialog).queryByRole('button', { name: 'com_nav_close_sidebar' })).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Project one' }));
  expect(within(dialog).getByRole('button', { name: 'Project one' })).toHaveAttribute('aria-expanded', 'true');
  fireEvent.keyDown(dialog, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
  expect(screen.getByRole('button', { name: 'Project one' })).toHaveAttribute('aria-expanded', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'First chat' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('textbox', { name: 'Draft' })).toHaveValue('Keep this draft');
  expect(document.body.style.pointerEvents).not.toBe('none');
});

it('closes when selecting the current module and preserves state while switching to desktop', async () => {
  const page = render(<Harness />);
  fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
  fireEvent.click(screen.getByRole('link', { name: 'Capabilities' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
  fireEvent.click(screen.getByRole('button', { name: 'Project one' }));
  page.rerender(<Harness mobile={false} />);
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('button', { name: 'Project one' })).toHaveAttribute('aria-expanded', 'true');
  expect(document.body.style.pointerEvents).not.toBe('none');
});

it('does not expose granted-only navigation when the account has no home entry', () => {
  mockGranted = false;
  render(<Harness />);
  fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
  expect(screen.queryByRole('link', { name: 'Capabilities' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Project one' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument();
});

it('keeps a persistent history error visible with a working retry', async () => {
  mockError = new Error('History unavailable');
  render(<Harness />);
  fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
  expect(screen.getByRole('alert')).toHaveTextContent('History unavailable');
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_retry' }));
  await waitFor(() => expect(mockRefetch).toHaveBeenCalled());
});
