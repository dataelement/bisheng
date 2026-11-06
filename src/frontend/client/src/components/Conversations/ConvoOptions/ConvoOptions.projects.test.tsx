import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import {
  createMockProject, deleteMockProject, moveChatToProject, removeChatFromProject,
} from '~/layouts/WorkbenchSidebar/projectsStore';
import ConvoOptions from './ConvoOptions';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, usePrefersMobileLayout: () => false }));
jest.mock('~/Providers', () => ({ useChatContext: () => ({ index: 0 }) }));
jest.mock('~/mock/demo/ids', () => ({ isDemoDataEnabled: () => false }));
jest.mock('./useDeleteConversationConfirm', () => ({ useDeleteConversationConfirm: () => jest.fn() }));
jest.mock('./ShareButton', () => ({ __esModule: true, default: () => null }));

function Harness() {
  const [open, setOpen] = useState(false);
  return <ConvoOptions conversationId="chat-one" title="Chat one" retainView={() => undefined}
    renameHandler={() => undefined} isPopoverActive={open} setIsPopoverActive={setOpen} />;
}

const projects = (): Array<{ id: string; name: string }> => JSON.parse(localStorage.getItem('bs_mock_projects') ?? '[]');
const assignment = () => JSON.parse(localStorage.getItem('bs_mock_project_chats') ?? '{}')['chat-one'];
let existingId: string;

beforeEach(() => {
  jest.useFakeTimers();
  existingId = createMockProject('e2e-move-existing').id;
  moveChatToProject('chat-one', existingId);
});
afterEach(() => {
  cleanup();
  projects().forEach(project => deleteMockProject(project.id));
  removeChatFromProject('chat-one');
  jest.runOnlyPendingTimers();
  jest.useRealTimers();
});

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
  const { create } = openMoveMenu();
  fireEvent.click(create);
  act(() => jest.runOnlyPendingTimers());
  act(() => jest.runOnlyPendingTimers());
  expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  return screen.getByRole('textbox', { name: 'com_workbench_sidebar.project_name_placeholder' });
}

it('separates new project and remove actions from the project list', () => {
  const { menu } = openMoveMenu();
  expect(within(menu).getAllByRole('menuitem').map(item => item.textContent)).toEqual([
    'com_workbench_sidebar.project_new', 'e2e-move-existing', 'com_workbench_sidebar.move_out_of_project',
  ]);
  expect(within(menu).getAllByRole('separator')).toHaveLength(2);
});

it('offers new project without stray separators when no projects exist', () => {
  deleteMockProject(existingId);
  const { menu } = openMoveMenu();
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(1);
  expect(within(menu).queryByRole('separator')).not.toBeInTheDocument();
});

it('hands focus to the naming dialog, then creates a project and moves the conversation', () => {
  const input = openCreateDialog();
  expect(input).toHaveFocus();
  fireEvent.change(input, { target: { value: 'e2e-move-new' } });
  act(() => jest.advanceTimersByTime(1));
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_create' }));
  const created = projects().find(project => project.name === 'e2e-move-new');
  expect(created).toBeDefined();
  expect(created?.id).not.toBe(existingId);
  expect(assignment()).toBe(created?.id);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('cancels creation without changing projects or the conversation assignment', () => {
  openCreateDialog();
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_cancel' }));
  expect(projects()).toHaveLength(1);
  expect(assignment()).toBe(existingId);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
