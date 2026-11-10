import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import type { KnowledgeSpace } from '~/api/knowledge';
import translation from '~/locales/en/translation.json';
import { KnowledgeHomePage } from '../../KnowledgeHomePage';

jest.mock('./componentMode', () => ({ USE_PRODUCT_COMPONENTS: false }));
jest.mock('@bisheng/ui', () => ({
  ...jest.requireActual('../../../../../../packages/ui/src/components/Tooltip/Tooltip.tsx'),
  ...jest.requireActual('../../../../../../packages/ui/src/components/Tabs/Tabs.tsx'),
  ...jest.requireActual('../../../../../../packages/ui/src/components/Button/Button.tsx'),
  ...jest.requireActual('../../../../../../packages/ui/src/components/Dropdown/Dropdown.tsx'),
  ...jest.requireActual('../../../../../../packages/ui/src/components/Select/Select.tsx'),
  ...jest.requireActual('../../../../../../packages/ui/src/components/StateView/StateView.tsx'),
  ...jest.requireActual('../../../../../../packages/ui/src/components/Illustration/EmptyStateIllustration.tsx'),
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
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: { id: 'test-user' } }),
  useWorkbenchMenuNames: () => ({ knowledge: 'Knowledge spaces' }),
  useLocalize: () => (key: string) => key,
}));
jest.mock('~/Providers', () => ({ useConfirm: () => mockConfirm }));
jest.mock('bisheng-icons', () => ({ ...jest.requireActual('bisheng-icons'), Outlined: {
  ...jest.requireActual('bisheng-icons').Outlined,
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
  deletion: { view: null },
}) }));

function row(id: string, name: string, date = '2026-01-01'): KnowledgeSpace {
  return { id, name, creator: '', creatorId: '', memberCount: 0, fileCount: 0, totalFileCount: 0,
    visibility: 'private' as KnowledgeSpace['visibility'], role: 'member' as KnowledgeSpace['role'],
    isPinned: false, createdAt: date, updatedAt: date, tags: [], isReleased: false };
}
const callbacks = { onSpaceSelect: jest.fn(), onSpaceSettings: jest.fn(), onCreateSpace: jest.fn(), onKnowledgeSquare: jest.fn() };
function mount(path = '/knowledge') {
  return render(<MemoryRouter initialEntries={[path]}>
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <KnowledgeHomePage {...callbacks} />
    </QueryClientProvider>
  </MemoryRouter>);
}

beforeEach(() => {
  window.localStorage.clear();
  mockData = { mine: [row('1', 'Alpha')], joined: [row('2', 'Beta', '2026-02-01'), row('3', 'Department')], department: [row('3', 'Department')] };
  mockPermissions = {}; mockLoading = false; mockError = null; mockPermissionLoading = false;
  mockUpdate.mockReset(); mockUpdate.mockResolvedValue(undefined); mockPin.mockResolvedValue(undefined); mockConfirm.mockResolvedValue(true);
});

it('binds real counts, category filtering, merged sorting and navigation callbacks', async () => {
  mount();
  expect(within(screen.getByRole('tab', { name: 'com_knowledge.home_next.all 3' })).getByText('3')).toBeInTheDocument();
  expect(screen.getAllByRole('article').map((card) => within(card).getByRole('heading').textContent)).toEqual(['Beta', 'Alpha', 'Department']);
  fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: 'com_knowledge.home_next.sort_name' }));
  expect(screen.getAllByRole('article').map((card) => within(card).getByRole('heading').textContent)).toEqual(['Alpha', 'Beta', 'Department']);
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'com_knowledge.home_next.joined 1' }));
  expect(screen.getAllByRole('article')).toHaveLength(1);
  fireEvent.click(screen.getByRole('link', { name: 'Beta' }));
  expect(callbacks.onSpaceSelect).toHaveBeenCalledWith(mockData.joined[0]);
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.create_knowledge_space' }));
  expect(screen.queryByRole('button', { name: 'com_knowledge.home_next.square' })).not.toBeInTheDocument();
  expect(callbacks.onCreateSpace).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('BISHENG team')).not.toBeInTheDocument();
});

it('exposes a real detail link with independent controls and the current list tab', () => {
  mount('/knowledge?tab=joined&source=menu');
  const link = screen.getByRole('link', { name: 'Alpha' });
  const card = link.closest('article')!;
  expect(link).toHaveAttribute('href', '/knowledge/space/1?tab=joined');
  expect(within(link).queryByRole('button')).not.toBeInTheDocument();
  expect(link).not.toContainElement(within(card).getByRole('button', { name: 'com_knowledge.pin_space' }));
  expect(link).not.toContainElement(within(card).getByRole('button', { name: 'com_knowledge.home_next.more' }));
});

it.each(['description', 'creator', 'artwork'])('opens from the %s using the existing selection callback', (target) => {
  mockData.mine[0].description = 'Space description';
  mockData.mine[0].creator = 'Space creator';
  mount();
  const link = screen.getByRole('link', { name: 'Alpha' });
  const content = target === 'artwork' ? link.querySelector('img')!
    : within(link).getByText(target === 'description' ? 'Space description' : 'Space creator');
  fireEvent.click(content);
  expect(callbacks.onSpaceSelect).toHaveBeenCalledTimes(1);
  expect(callbacks.onSpaceSelect).toHaveBeenCalledWith(mockData.mine[0]);
});

it.each(['ctrlKey', 'metaKey', 'shiftKey', 'altKey'])('preserves native %s link activation without selecting in this page', (modifier) => {
  mount();
  const link = screen.getByRole('link', { name: 'Alpha' });
  const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, [modifier]: true });
  fireEvent(link, event);
  expect(event.defaultPrevented).toBe(false);
  expect(callbacks.onSpaceSelect).not.toHaveBeenCalled();
});

it('activates the card link with Enter', async () => {
  mount();
  const user = userEvent.setup();
  const link = screen.getByRole('link', { name: 'Alpha' });
  act(() => link.focus());
  await user.keyboard('{Enter}');
  expect(callbacks.onSpaceSelect).toHaveBeenCalledTimes(1);
  expect(callbacks.onSpaceSelect).toHaveBeenCalledWith(mockData.mine[0]);
});

it('keeps demo cards on the home route with disabled actions and no detail fetch', () => {
  mockData.mine[0].id = 'demo-space';
  mockData.mine[0].creatorId = 'demo-owner';
  mount('/knowledge?tab=all');
  const link = screen.getByRole('link', { name: 'Alpha' });
  const card = link.closest('article')!;
  expect(link).toHaveAttribute('href', '/knowledge?tab=all');
  expect(within(card).getByRole('button', { name: 'com_knowledge.pin_space' })).toBeDisabled();
  expect(within(card).getByRole('button', { name: 'com_knowledge.home_next.more' })).toBeDisabled();
  expect(mockCreatorInfo).not.toHaveBeenCalled();
  fireEvent.click(link);
  expect(callbacks.onSpaceSelect).toHaveBeenCalledWith(mockData.mine[0]);
});

it('closes the shared menu with Escape without reopening its tooltip or entering the space', async () => {
  mockPermissions = { '1': ['edit'] };
  mount();
  const card = screen.getByRole('link', { name: 'Alpha' }).closest('article')!;
  const more = within(card).getByRole('button', { name: 'com_knowledge.home_next.more' });
  fireEvent.keyDown(more, { key: 'Enter' });
  fireEvent.keyDown(await screen.findByRole('menu'), { key: 'Escape' });
  await waitFor(() => {
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(more).toHaveFocus();
  });
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  expect(callbacks.onSpaceSelect).not.toHaveBeenCalled();
});

it('closes sorting with Escape without changing its value and restores keyboard focus', async () => {
  mount();
  const sort = screen.getByRole('combobox');
  sort.focus();
  fireEvent.keyDown(sort, { key: 'ArrowDown' });
  await screen.findByRole('listbox');
  fireEvent.keyDown(sort, { key: 'Escape' });
  await waitFor(() => {
    expect(sort).toHaveAttribute('aria-expanded', 'false');
    expect(sort).toHaveFocus();
  });
  expect(sort).toHaveTextContent('com_knowledge.home_next.sort_create_time');
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

it.each(['name', 'update_time'])('restores %s and its card order after the home page remounts', async (sort) => {
  mockData.mine[0].updatedAt = '2026-03-01';
  const view = mount();
  fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: `com_knowledge.home_next.sort_${sort}` }));
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'com_knowledge.home_next.created 1' }));
  expect(screen.getByRole('combobox')).toHaveTextContent(`com_knowledge.home_next.sort_${sort}`);
  view.unmount();

  mount();
  expect(screen.getByRole('combobox')).toHaveTextContent(`com_knowledge.home_next.sort_${sort}`);
  expect(screen.getAllByRole('article').map((card) => within(card).getByRole('heading').textContent))
    .toEqual(['Alpha', 'Beta', 'Department']);
});

it('supports arrow-key category selection and preserves focus', async () => {
  mount();
  const first = screen.getByRole('tab', { name: 'com_knowledge.home_next.all 3' });
  act(() => first.focus());
  fireEvent.keyDown(first, { key: 'ArrowRight' });
  await waitFor(() => {
    expect(screen.getByRole('tab', { name: 'com_knowledge.home_next.department 1' })).toHaveFocus();
    expect(screen.getAllByRole('article')).toHaveLength(1);
  });
});

it('keeps latest pin first through sort changes, unpin and re-pin', async () => {
  mockPin.mockImplementation(async (id: string, isPinned: boolean) => {
    const update = (list: KnowledgeSpace[]) => list.map((space) => space.id === id ? { ...space, isPinned } : space);
    mockData = { mine: update(mockData.mine), joined: update(mockData.joined), department: update(mockData.department) };
  });
  mount();
  const cardNamed = (name: string) => screen.getAllByRole('article').find((node) => within(node).queryByRole('link', { name }))!;
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

it('hides count badges during loading or failure and exposes retry', () => {
  mockLoading = true;
  const view = mount();
  expect(screen.getByRole('tab', { selected: true })).toHaveAccessibleName('com_knowledge.home_next.all');
  expect(screen.queryAllByRole('article')).toHaveLength(0);
  mockLoading = false; mockError = new Error('network');
  view.rerender(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><KnowledgeHomePage {...callbacks} /></QueryClientProvider></MemoryRouter>);
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(screen.getByRole('tab', { selected: true })).toHaveAccessibleName('com_knowledge.home_next.all');
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_retry' }));
  expect(mockRetry).toHaveBeenCalledTimes(1);
});

it('keeps the home controls when all real lists are empty', () => {
  mockData = { mine: [], joined: [], department: [] };
  mount();
  expect(screen.getByRole('tab', { selected: true })).toHaveAccessibleName('com_knowledge.home_next.all');
  expect(screen.getByRole('status')).toHaveTextContent('com_knowledge.home_next.empty_all');
  expect(screen.getByRole('button', { name: 'com_knowledge.create_knowledge_space' })).toBeEnabled();
});

it.each([
  ['created', 'mine', 'Create a space', 'Nothing here yet. Create a space', 'onCreateSpace'],
  ['joined', 'joined', 'Go to the square', 'Nothing here yet. Go to the square to explore', 'onKnowledgeSquare'],
] as const)('offers the next action when the %s tab is empty', async (category, list, label, message, action) => {
  mockData[list] = [];
  const i18n = createInstance();
  await i18n.init({ lng: 'en', resources: { en: { translation } } });
  render(<I18nextProvider i18n={i18n}><MemoryRouter><QueryClientProvider client={new QueryClient()}>
    <KnowledgeHomePage {...callbacks} category={category} />
  </QueryClientProvider></MemoryRouter></I18nextProvider>);

  const status = screen.getByRole('status');
  expect(status).toHaveTextContent(message);
  expect(screen.getByRole('tabpanel').querySelector('svg')).toBeInTheDocument();
  await userEvent.click(within(status).getByRole('button', { name: label }));
  expect(callbacks[action]).toHaveBeenCalledTimes(1);
});

it('locks repeated pin operations and passes the original category from the all tab', async () => {
  let finish: () => void = () => undefined;
  mockPin.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
  mount();
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('link', { name: 'Department' }))!;
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
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('link', { name: 'Alpha' }))!;
  fireEvent.keyDown(within(card).getByRole('button', { name: 'com_knowledge.home_next.more' }), { key: 'Enter' });
  await waitFor(() => expect(screen.getByRole('menu')).toBeInTheDocument());
  expect(mockEnsurePermissions).toHaveBeenCalledWith('1');
  expect(screen.queryByRole('menuitem', { name: 'com_knowledge.space_settings' })).not.toBeInTheDocument();
  expect(screen.queryByRole('menuitem', { name: 'com_knowledge.delete_space' })).not.toBeInTheDocument();
});

it('hands destructive deletion to the confirmation owner only with the permission', async () => {
  mockPermissions = { '1': ['delete', 'edit'] };
  mount();
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('link', { name: 'Alpha' }))!;
  fireEvent.keyDown(within(card).getByRole('button', { name: 'com_knowledge.home_next.more' }), { key: 'Enter' });
  const menu = await screen.findByRole('menu');
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(2);
  expect(within(menu).queryByRole('menuitem', { name: 'com_knowledge.pin_space' })).not.toBeInTheDocument();
  const deleteAction = within(menu).getByRole('menuitem', { name: 'com_knowledge.delete_space' });
  expect(deleteAction).toHaveClass('text-danger');
  fireEvent.click(deleteAction);
  await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('1'));
  expect(mockConfirm).not.toHaveBeenCalled();
});

it('keeps creation and discovery disabled until the plugin gate resolves', () => {
  render(<MemoryRouter><QueryClientProvider client={new QueryClient()}><KnowledgeHomePage {...callbacks} enabled={false} /></QueryClientProvider></MemoryRouter>);
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

it('exposes only permitted settings in the joined-space menu', async () => {
  mockPermissions = { '2': ['edit', 'manage_permission'] };
  mount();
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('link', { name: 'Beta' }))!;
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
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('link', { name: 'Alpha' }))!;
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
  const card = screen.getAllByRole('article').find((node) => within(node).queryByRole('link', { name: 'Alpha' }))!;
  fireEvent.keyDown(within(card).getByRole('button', { name: 'com_knowledge.home_next.more' }), { key: 'Enter' });
  fireEvent.click(await screen.findByRole('menuitem', { name: 'com_knowledge.space_settings' }));
  expect(callbacks.onSpaceSettings).toHaveBeenCalledWith(mockData.mine[0]);
  expect(callbacks.onSpaceSelect).not.toHaveBeenCalled();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(mockUpdate).not.toHaveBeenCalled();
});
