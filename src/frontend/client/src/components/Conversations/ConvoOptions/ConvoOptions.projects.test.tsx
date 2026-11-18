import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import ConvoOptions from './ConvoOptions';

const mockMutate = jest.fn();
let mockProjects: Array<{ id: string; name: string; readonly: boolean; demoChats: string[] }> = [];
let mockAssignments: Record<string, string> = {};
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, usePrefersMobileLayout: () => false }));
jest.mock('~/Providers', () => ({ useChatContext: () => ({ index: 0 }), useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks/useChatProjects', () => ({ useChatProjectActions: () => ({ mutateAsync: mockMutate }), useProjectIdentity: () => 'account-a' }));
jest.mock('~/layouts/WorkbenchSidebar/projectsStore', () => ({ useProjectMemberships: () => mockAssignments, PROJECT_NAME_MAX_LENGTH: 30 }));
jest.mock('~/layouts/WorkbenchSidebar/useSidebarProjects', () => ({ useSidebarProjects: () => mockProjects }));
jest.mock('~/mock/demo/ids', () => ({ isDemoDataEnabled: () => false }));
jest.mock('./useDeleteConversationConfirm', () => ({ useDeleteConversationConfirm: () => jest.fn() }));
jest.mock('./ShareButton', () => ({ __esModule: true, default: () => null }));

function Harness() {
  const [open, setOpen] = useState(false);
  return <ConvoOptions conversationId="chat-one" title="Chat one" retainView={() => undefined}
    renameHandler={() => undefined} isPopoverActive={open} setIsPopoverActive={setOpen} />;
}
beforeEach(() => {
  jest.useFakeTimers(); mockMutate.mockReset();
  mockMutate.mockResolvedValue({ epoch: 1, outcome: { project_id: 'created-project' } });
  mockProjects = [{ id: 'existing-project', name: 'Existing', readonly: false, demoChats: [] }];
  mockAssignments = { 'chat-one': 'existing-project' };
});
afterEach(() => { cleanup(); jest.runOnlyPendingTimers(); jest.useRealTimers(); });

function openMoveMenu() {
  render(<Harness />);
  fireEvent.keyDown(screen.getByRole('button', { name: 'com_nav_convo_menu_options' }), { key: 'ArrowDown' });
  act(() => jest.runOnlyPendingTimers());
  fireEvent.keyDown(screen.getByRole('menuitem', { name: 'com_workbench_sidebar.move_to_project' }), { key: 'ArrowRight' });
  act(() => jest.runOnlyPendingTimers());
  const create = screen.getByRole('menuitem', { name: 'com_workbench_sidebar.project_new' });
  return { create, menu: create.closest('[role="menu"]') as HTMLElement };
}
function openCreateDialog() {
  fireEvent.click(openMoveMenu().create);
  act(() => jest.runOnlyPendingTimers()); act(() => jest.runOnlyPendingTimers());
  return screen.getByRole('textbox', { name: 'com_workbench_sidebar.project_name_placeholder' });
}
it('separates new project and remove actions from writable projects', () => {
  const { menu } = openMoveMenu();
  expect(within(menu).getAllByRole('menuitem').map(item => item.textContent)).toEqual([
    'com_workbench_sidebar.project_new', 'Existing', 'com_workbench_sidebar.move_out_of_project',
  ]);
});
it('offers only creation when there are no projects or membership', () => {
  mockProjects = []; mockAssignments = {};
  expect(within(openMoveMenu().menu).getAllByRole('menuitem')).toHaveLength(1);
});
it('creates and assigns in one server operation and waits for confirmation', async () => {
  const input = openCreateDialog();
  expect(input).toHaveFocus();
  fireEvent.change(input, { target: { value: 'Research' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'com_ui_create' })); });
  expect(mockMutate).toHaveBeenCalledWith({ operation: { operation: 'create', project_id: expect.stringMatching(/^[0-9a-f-]{36}$/), name: 'Research', chat_id: 'chat-one' } });
  expect(mockMutate).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it('retains failed input and retries with the same client-generated project id', async () => {
  mockMutate.mockRejectedValueOnce(new Error('offline'));
  const input = openCreateDialog();
  fireEvent.change(input, { target: { value: 'Retry research' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'com_ui_create' })); });
  expect(input).toHaveValue('Retry research');
  expect(screen.getByRole('alert')).toHaveTextContent('project_sync.save_failed');
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'com_ui_create' })); });
  expect(mockMutate.mock.calls[0][0].operation.project_id).toEqual(expect.any(String));
  expect(mockMutate.mock.calls[0][0].operation.project_id).toBe(mockMutate.mock.calls[1][0].operation.project_id);
});
it('cancels without sending a mutation', () => {
  openCreateDialog(); fireEvent.click(screen.getByRole('button', { name: 'com_ui_cancel' }));
  expect(mockMutate).not.toHaveBeenCalled();
});
