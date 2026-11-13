import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { SidebarProjects } from './SidebarProjects';

const noop = () => undefined;
const mockProject = { id: 'project-one', name: 'Project one', readonly: false, demoChats: [] };
const mockReadonlyProject = { id: 'demo', name: 'Demo project', readonly: true, demoChats: [] };

jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ isAuthenticated: true }),
  useLocalize: () => (key: string) => key,
}));
jest.mock('~/hooks/queries/data-provider', () => ({
  useConversationsInfiniteQuery: () => ({ data: { pages: [{ conversations: [] }] } }),
}));
jest.mock('./useSidebarProjects', () => ({ useSidebarProjects: () => [mockProject, mockReadonlyProject] }));
jest.mock('./projectsStore', () => ({
  useMockProjectChats: () => ({}), createMockProject: () => mockProject,
  deleteMockProject: noop, renameMockProject: noop,
}));
jest.mock('./ProjectNameDialog', () => ({ ProjectNameDialog: () => null }));
jest.mock('~/components/Conversations/Convo', () => ({ __esModule: true, default: () => null }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('bisheng-icons', () => ({ Outlined: new Proxy({}, { get: () => () => <svg /> }) }));
jest.mock('@bisheng/ui', () => ({
  Tooltip: ({ children }: { children: ReactNode }) => children,
  Dropdown: ({ children }: { children: ReactNode }) => children,
  DropdownItem: () => null,
}));

it('starts a chat in the selected project and expands it', () => {
  const onStartChat = jest.fn();
  render(<SidebarProjects onStartChat={onStartChat} />);
  expect(screen.getByRole('button', { name: 'Project one' })).toHaveAttribute('aria-expanded', 'false');

  fireEvent.click(screen.getByRole('button', { name: 'com_nav_start_new_chat · Project one' }));

  expect(onStartChat).toHaveBeenCalledWith('project-one');
  expect(screen.getByRole('button', { name: 'Project one' })).toHaveAttribute('aria-expanded', 'true');
});

it('offers no new-chat entry on read-only demo projects', () => {
  render(<SidebarProjects onStartChat={jest.fn()} />);
  expect(screen.queryByRole('button', { name: 'com_nav_start_new_chat · Demo project' })).not.toBeInTheDocument();
});
