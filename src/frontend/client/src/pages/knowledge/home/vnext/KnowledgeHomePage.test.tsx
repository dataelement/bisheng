import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { KnowledgeSpace } from '~/api/knowledge';
import { KnowledgeHomePage } from '../../KnowledgeHomePage';

jest.mock('./componentMode', () => ({ USE_PRODUCT_COMPONENTS: false }));
jest.mock('@bisheng/ui', () => ({
  ...jest.requireActual('../../../../../../packages/ui/src/components/Tooltip/Tooltip.tsx'),
  ...jest.requireActual('../../../../../../packages/ui/src/components/Tabs/Tabs.tsx'),
  ...jest.requireActual('../../../../../../packages/ui/src/components/Button/Button.tsx'),
}));

const mockCreatorInfo = jest.fn();
const mockPin = jest.fn();
const mockDelete = jest.fn();
const mockUpdate = jest.fn();
const mockLeave = jest.fn();
const mockConfirm = jest.fn();
const mockEnsurePermissions = jest.fn();
const mockRetry = jest.fn();
let mockPermissions: Record<string, string[]> = {};
let mockLoading = false;
let mockError: Error | null = null;
let mockPermissionLoading = false;
let mockData: { mine: KnowledgeSpace[]; joined: KnowledgeSpace[]; department: KnowledgeSpace[] };

jest.mock('~/api/knowledge', () => ({ SpaceSortType: { UPDATE_TIME: 'update_time' }, getSpaceInfoApi: (...args: unknown[]) => mockCreatorInfo(...args) }));
jest.mock('~/api/request', () => ({ showApiError: jest.fn() }));
jest.mock('~/mock/demo/ids', () => ({ isDemoId: () => false }));
jest.mock('~/hooks', () => ({
  useWorkbenchMenuNames: () => ({ knowledge: 'Knowledge spaces' }),
  useLocalize: () => (key: string) => key,
}));
jest.mock('~/Providers', () => ({ useConfirm: () => mockConfirm }));
jest.mock('bisheng-icons', () => ({ ...jest.requireActual('bisheng-icons'), Outlined: {
  Edit: () => <svg />, Delete: () => <svg />, Plus: () => <svg />, More: () => <svg />, Pin: () => <svg />, People: () => <svg />,
} }));
jest.mock('../../hooks/useKnowledgeSpaceLists', () => ({ useKnowledgeSpaceLists: () => ({
  mine: { data: mockData.mine, isLoading: mockLoading },
  joined: { data: mockData.joined, isLoading: mockLoading },
  department: { data: mockData.department, isLoading: mockLoading },
  error: mockError, retry: mockRetry,
}) }));
jest.mock('../../hooks/useKnowledgeSpacePermissions', () => ({ useKnowledgeSpaceActions: () => ({
  actions: mockPermissions, ensureSpaceActions: mockEnsurePermissions,
  isSpaceActionsPending: () => mockPermissionLoading,
}) }));
jest.mock('../../hooks/useSpaceActions', () => ({ useSpaceActions: () => ({
  handleUpdateSpace: mockUpdate, handlePinSpace: mockPin, handleDeleteSpace: mockDelete, handleLeaveSpace: mockLeave,
}) }));

function row(id: string, name: string, date = '2026-01-01'): KnowledgeSpace {
  return { id, name, creator: '', creatorId: '', memberCount: 0, fileCount: 0, totalFileCount: 0,
    visibility: 'private' as KnowledgeSpace['visibility'], role: 'member' as KnowledgeSpace['role'],
    isPinned: false, createdAt: date, updatedAt: date, tags: [], isReleased: false };
}
const callbacks = { onSpaceSelect: jest.fn(), onSpaceSettings: jest.fn(), onCreateSpace: jest.fn(), onKnowledgeSquare: jest.fn() };
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><KnowledgeHomePage {...callbacks} /></QueryClientProvider>); }

beforeEach(() => {
  mockData = { mine: [row('1', 'Alpha')], joined: [row('2', 'Beta', '2026-02-01'), row('3', 'Department')], department: [row('3', 'Department')] };
  mockPermissions = {}; mockLoading = false; mockError = null; mockPermissionLoading = false;
  mockUpdate.mockReset(); mockUpdate.mockResolvedValue(undefined); mockPin.mockResolvedValue(undefined); mockConfirm.mockResolvedValue(true);
});

it('binds real counts, category filtering, merged sorting and navigation callbacks', async () => {
  mount();
  expect(screen.getByRole('tab', { name: 'com_knowledge.home_next.all (3)' })).toBeInTheDocument();
  expect(screen.getAllByRole('article').map((card) => within(card).getByRole('heading').textContent)).toEqual(['Beta', 'Alpha', 'Department']);
  fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: 'com_knowledge.home_next.sort_name' }));
  expect(screen.getAllByRole('article').map((card) => within(card).getByRole('heading').textContent)).toEqual(['Alpha', 'Beta', 'Department']);
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'com_knowledge.home_next.joined (1)' }));
  expect(screen.getAllByRole('article')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Beta' }));
  expect(callbacks.onSpaceSelect).toHaveBeenCalledWith(mockData.joined[0]);
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.create_knowledge_space' }));
  expect(screen.queryByRole('button', { name: 'com_knowledge.home_next.square' })).not.toBeInTheDocument();
  expect(callbacks.onCreateSpace).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('BISHENG team')).not.toBeInTheDocument();
});

it('closes sorting with Escape without changing its value and restores keyboard focus', async () => {
  mount();
  const sort = screen.getByRole('combobox');
  fireEvent.keyDown(sort, { key: 'ArrowDown' });
  fireEvent.keyDown(await screen.findByRole('listbox'), { key: 'Escape' });
  await waitFor(() => {
    expect(sort).toHaveAttribute('aria-expanded', 'false');
    expect(sort).toHaveFocus();
  });
  expect(sort).toHaveTextContent('com_knowledge.home_next.sort_create_time');
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

it('supports arrow-key category selection and preserves focus', async () => {
  mount();
  const first = screen.getByRole('tab', { name: 'com_knowledge.home_next.all (3)' });
  act(() => first.focus());
  fireEvent.keyDown(first, { key: 'ArrowRight' });
  await waitFor(() => {
    expect(screen.getByRole('tab', { name: 'com_knowledge.home_next.department (1)' })).toHaveFocus();
    expect(screen.getAllByRole('article')).toHaveLength(1);
  });
});

it('keeps latest pin first through sort changes, unpin and re-pin', async () => {
  mockPin.mockImplementation(async (id: string, isPinned: boolean) => {
    const update = (list: KnowledgeSpace[]) => list.map((space) => space.id === id ? { ...space, isPinned } : space);
    mockData = { mine: update(mockData.mine), joined: update(mockData.joined), department: update(mockData.department) };
  });
  mount();
  const cardNamed = (name: string) => screen.getAllByRole('article').find((node) => within(node).queryByRole('button', { name }))!;
  const order = () => screen.getAllByRole('article').map((node) => within(node).getByRole('heading').textContent);
  fireEvent.click(within(cardNamed('Beta')).getByRole('button', { name: 'com_knowledge.pin_space' }));
  await waitFor(() => expect(within(cardNamed('Beta')).getByRole('button', { name: 'com_knowledge.unpin' })).toBeEnabled());
  fireEvent.click(within(cardNamed('Alpha')).getByRole('button', { name: 'com_knowledge.pin_space' }));
  await waitFor(() => expect(within(cardNamed('Alpha')).getByRole('button', { name: 'com_knowledge.unpin' })).toBeEnabled());
  fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: 'com_knowledge.home_next.sort_name' }));
  expect(order()).toEqual(['Alpha', 'Beta', 'Department']);
  fireEvent.click(within(cardNamed('Beta')).getByRole('button', { name: 'com_knowledge.unpin' }));
  await waitFor(() => expect(order()).toEqual(['Alpha', 'Beta', 'Department']));
  fireEvent.click(within(cardNamed('Beta')).getByRole('button', { name: 'com_knowledge.pin_space' }));
  await waitFor(() => expect(within(cardNamed('Beta')).getByRole('button', { name: 'com_knowledge.unpin' })).toBeEnabled());
  fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: 'com_knowledge.home_next.sort_create_time' }));
  expect(order()).toEqual(['Beta', 'Alpha', 'Department']);
});

it('does not show a successful zero count during loading or failure and exposes retry', () => {
  mockLoading = true;
  const view = mount();
  expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('—');
  expect(screen.queryAllByRole('article')).toHaveLength(0);
  mockLoading = false; mockError = new Error('network');
  view.rerender(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><KnowledgeHomePage {...callbacks} /></QueryClientProvider>);
  expect(screen.getByRole('alert')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_retry' }));
  expect(mockRetry).toHaveBeenCalledTimes(1);
});

it('keeps the home controls when all real lists are empty', () => {
  mockData = { mine: [], joined: [], department: [] };
  mount();
  expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('(0)');
  expect(screen.getByRole('status')).toHaveTextContent('com_knowledge.no_data');
  expect(screen.getByRole('button', { name: 'com_knowledge.create_knowledge_space' })).toBeEnabled();
});

it('locks repeated pin operations and passes the original category from the all tab', async () => {
  let finish: () => void = () => undefined;
  mockPin.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
  mount();
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('button', { name: 'Department' }))!;
  const pin = within(card).getByRole('button', { name: 'com_knowledge.pin_space' });
  fireEvent.click(pin); fireEvent.click(pin);
  expect(mockPin).toHaveBeenCalledTimes(1);
  expect(mockPin).toHaveBeenCalledWith('3', true, 'department');
  expect(pin).toBeDisabled();
  await act(async () => { finish(); });
  expect(pin).toBeEnabled();
});

it('resolves permissions when opening the portaled menu and hides unauthorized edit/delete', async () => {
  mount();
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('button', { name: 'Alpha' }))!;
  fireEvent.keyDown(within(card).getByRole('button', { name: 'com_knowledge.home_next.more' }), { key: 'Enter' });
  await waitFor(() => expect(screen.getByRole('menu')).toBeInTheDocument());
  expect(mockEnsurePermissions).toHaveBeenCalledWith('1');
  expect(screen.queryByRole('menuitem', { name: 'com_knowledge.space_settings' })).not.toBeInTheDocument();
  expect(screen.queryByRole('menuitem', { name: 'com_knowledge.delete_space' })).not.toBeInTheDocument();
});

it('confirms destructive operations and dispatches deletion only with the permission', async () => {
  mockPermissions = { '1': ['delete', 'edit'] };
  mount();
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('button', { name: 'Alpha' }))!;
  fireEvent.keyDown(within(card).getByRole('button', { name: 'com_knowledge.home_next.more' }), { key: 'Enter' });
  const menu = await screen.findByRole('menu');
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(2);
  expect(within(menu).queryByRole('menuitem', { name: 'com_knowledge.pin_space' })).not.toBeInTheDocument();
  fireEvent.click(within(menu).getByRole('menuitem', { name: 'com_knowledge.delete_space' }));
  await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('1'));
  expect(mockConfirm).toHaveBeenCalledWith(expect.objectContaining({ variant: 'destructive' }));
});

it('keeps creation and discovery disabled until the plugin gate resolves', () => {
  render(<QueryClientProvider client={new QueryClient()}><KnowledgeHomePage {...callbacks} enabled={false} /></QueryClientProvider>);
  expect(screen.getByRole('button', { name: 'com_knowledge.create_knowledge_space' })).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'com_knowledge.home_next.square' })).not.toBeInTheDocument();
});

it('shows a permission loading row instead of privileged actions', async () => {
  mockPermissionLoading = true;
  mount();
  const more = screen.getAllByRole('button', { name: 'com_knowledge.home_next.more' })[0];
  fireEvent.keyDown(more, { key: 'Enter' });
  expect(await screen.findByRole('menuitem', { name: 'com_knowledge.loading' })).toHaveAttribute('aria-disabled', 'true');
  expect(screen.queryByRole('menuitem', { name: 'com_knowledge.delete_space' })).not.toBeInTheDocument();
});

it('keeps the joined-space menu free of pin, settings and leave actions', async () => {
  mockPermissions = { '2': ['edit', 'manage_permission'] };
  mount();
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('button', { name: 'Beta' }))!;
  fireEvent.keyDown(within(card).getByRole('button', { name: 'com_knowledge.home_next.more' }), { key: 'Enter' });
  const menu = await screen.findByRole('menu');
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(1);
  expect(within(menu).getByRole('menuitem', { name: 'com_knowledge.space_settings' })).not.toHaveAttribute('aria-disabled', 'true');
  expect(within(menu).queryByRole('menuitem', { name: 'com_knowledge.pin_space' })).not.toBeInTheDocument();
  expect(within(menu).getByRole('menuitem', { name: 'com_knowledge.space_settings' })).toBeInTheDocument();
  expect(within(menu).queryByRole('menuitem', { name: 'com_knowledge.exit_space_short' })).not.toBeInTheDocument();
  expect(mockLeave).not.toHaveBeenCalled();
});

it('unpins from the card button without entering the space', async () => {
  mockData.mine[0].isPinned = true;
  mount();
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('button', { name: 'Alpha' }))!;
  const pin = within(card).getByRole('button', { name: 'com_knowledge.unpin' });
  expect(pin).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(pin);
  await waitFor(() => expect(mockPin).toHaveBeenCalledWith('1', false, 'created'));
  expect(callbacks.onSpaceSelect).not.toHaveBeenCalled();
});

it('loads the actual creator from detail only when the list omits it', async () => {
  mockData.mine[0].creatorId = '42';
  mockCreatorInfo.mockResolvedValue({ ...mockData.mine[0], creator: 'Actual creator' });
  mount();
  expect(await screen.findByText('Actual creator')).toBeInTheDocument();
  expect(mockCreatorInfo).toHaveBeenCalledWith('1');
});

it('opens existing space settings instead of renaming inline', async () => {
  mockPermissions = { '1': ['edit'] };
  mount();
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('button', { name: 'Alpha' }))!;
  fireEvent.keyDown(within(card).getByRole('button', { name: 'com_knowledge.home_next.more' }), { key: 'Enter' });
  fireEvent.click(await screen.findByRole('menuitem', { name: 'com_knowledge.space_settings' }));
  expect(callbacks.onSpaceSettings).toHaveBeenCalledWith(mockData.mine[0]);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(mockUpdate).not.toHaveBeenCalled();
});
