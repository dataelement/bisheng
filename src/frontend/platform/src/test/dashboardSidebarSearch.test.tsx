import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { DashboardSidebar } from '@/pages/Dashboard/components/dashboard/DashboardSidebar';
import type { Dashboard } from '@/pages/Dashboard/types/dataConfig';

vi.mock('@/contexts/userContext', async () => {
  const { createContext } = await import('react');
  return { userContext: createContext({ user: {} }) };
});
vi.mock('@/contexts/alertContext', async () => {
  const { createContext } = await import('react');
  return { alertContext: createContext({}) };
});
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@/controllers/API/dashboard', () => ({
  copyDashboard: vi.fn(), createDashboard: vi.fn(), deleteDashboard: vi.fn(),
}));
vi.mock('@/components/bs-comp/permission/PermissionDialog', () => ({ PermissionDialog: () => null }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }));
vi.mock('@/pages/Dashboard/hook', () => ({ DashboardsQueryKey: 'dashboards' }));
vi.mock('@/pages/Dashboard/components/dashboard/DashboardListItem', () => ({
  DashboardListItem: ({ dashboard }: { dashboard: Dashboard }) => <div>{dashboard.title}</div>,
}));
vi.mock('@tanstack/react-query', () => ({ useMutation: () => ({}), useQueryClient: () => ({}) }));
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

afterEach(cleanup);

it('keeps each typed character, filters immediately, and restores the list when cleared', () => {
  const dashboards = [
    { id: 'sales', title: 'Sales overview' },
    { id: 'operations', title: 'Operations overview' },
  ] as Dashboard[];
  render(<DashboardSidebar dashboards={dashboards} selectedId={null} isCollapsed={false}
    setIsCollapsed={vi.fn()} onSelect={vi.fn()} onRename={vi.fn()} onDefault={vi.fn()} onShare={vi.fn()} />);
  const input = screen.getByPlaceholderText('system.boardName');
  for (const value of ['S', 'Sa', 'Sal', 'Sale', 'Sales']) {
    fireEvent.change(input, { target: { value } });
    expect(input).toHaveValue(value);
  }
  expect(screen.getByText('Sales overview')).toBeInTheDocument();
  expect(screen.queryByText('Operations overview')).toBeNull();
  fireEvent.change(input, { target: { value: '' } });
  expect(input).toHaveValue('');
  expect(screen.getByText('Operations overview')).toBeInTheDocument();
});
