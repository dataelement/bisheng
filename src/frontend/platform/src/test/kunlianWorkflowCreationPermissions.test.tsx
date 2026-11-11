// 覆盖 AC: AC-03, AC-04, AC-07, AC-13
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppType } from '@/types/app';
import Apps from '@/pages/BuildPage/apps';

const state = vi.hoisted(() => ({
  user: { role: 'editor', user_id: 42, tenant_id: 7, web_menu: [] as string[] },
  rows: [] as Array<{ id: string; name: string; flow_type: number }>,
  actions: {} as Record<string, string[]>,
  open: vi.fn(), create: vi.fn(), source: vi.fn(), management: false,
}));
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ get user() { return state.user; } }) }));
vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: {} }) }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { loadNamespaces: vi.fn() } }) }));
vi.mock('@/util/hook', () => ({ useInfiniteCursorTable: () => ({ data: state.rows, loaded: true, loading: false, hasMore: false, reload: vi.fn(), search: vi.fn(), filterData: vi.fn() }) }));
vi.mock('@/components/bs-comp/permission/useResourceActions', () => ({
  useResourceActions: () => ({ actions: state.actions }),
  hasResourceAction: (actions: Record<string, string[]>, id: string, action: string) => actions[id]?.includes(action),
}));
vi.mock('@/components/bs-comp/cardComponent', () => ({ default: ({ data, title, onClick, showCopy, onCopy }: {
  data?: { id: string }; title: string; onClick: () => void; showCopy?: boolean; onCopy?: (data: unknown) => void;
}) => <div><button onClick={onClick}>{title}</button>{showCopy && <button onClick={() => onCopy?.(data)}>copy-{data?.id}</button>}</div> }));
vi.mock('@/pages/BuildPage/CreateApp', async () => {
  const React = await import('react');
  return { default: React.forwardRef(({ workflowManagement }: { workflowManagement?: boolean }, ref) => {
    state.management = workflowManagement === true;
    React.useImperativeHandle(ref, () => ({ open: state.open })); return null;
  }) };
});
vi.mock('@/components/bs-comp/sheets/AppTempSheet', () => ({ default: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@/components/bs-comp/cardComponent/avatar', () => ({ default: () => null }));
vi.mock('@/components/bs-comp/cardComponent/LabelShow', () => ({ default: () => null }));
vi.mock('@/components/bs-comp/permission/PermissionDialog', () => ({ PermissionDialog: () => null }));
vi.mock('@/components/bs-comp/loadMore', () => ({ default: () => null }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }));
vi.mock('@/pages/BuildPage/CreateTemp', () => ({ default: () => null }));
vi.mock('@/pages/BuildPage/CardSelectVersion', () => ({ default: () => null }));
vi.mock('@/pages/BuildPage/HostedAppCard', () => ({ HostedAppCard: () => null }));
vi.mock('@/pages/BuildPage/hook', () => ({
  useCreateTemp: () => ({ flowRef: { current: null }, toggleTempModal: vi.fn() }),
  useQueryLabels: () => ({ selectLabel: { value: -1 }, allOptions: [], filteredOptions: [] }),
}));
vi.mock('@/controllers/API/assistant', () => ({ createAssistantsApi: vi.fn(), getAssistantDetailApi: vi.fn(), saveAssistanttApi: vi.fn(), changeAssistantStatusApi: vi.fn(), deleteAssistantApi: vi.fn() }));
vi.mock('@/controllers/API/flow', () => ({ getWorkflowManagementEditorFlow: state.source, getFlowApi: state.source, getAppsApi: vi.fn(), deleteFlowFromDatabase: vi.fn(), getWorkflowManagementSummary: vi.fn() }));
vi.mock('@/controllers/API/workflow', () => ({ createWorkflowApi: state.create, copyReportTemplate: vi.fn(), onlineWorkflow: vi.fn(), onlineWorkflowApi: vi.fn() }));
vi.mock('@/controllers/request', () => ({ handleUiRequest: (callback: unknown) => callback }));
vi.mock('@bisheng/ui', () => ({ Select: () => null, SearchInput: () => null, Button: () => null, Tag: () => null, notification: { open: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  state.user.web_menu = ['admin', 'build', 'create_workflow'];
  state.rows = []; state.actions = {};
  state.create.mockResolvedValue({ id: 'created' });
  state.source.mockResolvedValue({ id: 'source', name: 'source', description: '', flow_type: 10, data: { nodes: [], edges: [] } });
});
afterEach(cleanup);

function openPage(workflowOnly = true, entry = '/build/workflows') {
  return render(<MemoryRouter initialEntries={[entry]}><Apps workflowOnly={workflowOnly} /></MemoryRouter>);
}

it('offers only Workflow creation and preserves the old general grant', () => {
  const view = openPage();
  fireEvent.click(screen.getByText('build.createWorkflow'));
  expect(state.open).toHaveBeenCalledWith(AppType.FLOW, 0);
  expect(screen.queryByText('log.createBuild')).not.toBeInTheDocument();
  view.unmount(); state.user.web_menu = ['admin', 'build', 'create_app']; openPage();
  expect(screen.getByText('build.createWorkflow')).toBeInTheDocument();
});

it('does not turn the general page into a general creation grant and keeps legacy new targets Workflow-only', async () => {
  openPage(false, '/build/apps?kunlian_workflow=new');
  await waitFor(() => expect(state.open).toHaveBeenCalledWith(AppType.FLOW, 0));
  expect(state.management).toBe(true);
  expect(screen.queryByText('log.createBuild')).not.toBeInTheDocument();
});

it('requires source edit permission for management copying and sends the scoped creation key', async () => {
  state.rows = [{ id: 'source', name: 'source', flow_type: 10 }];
  const view = openPage();
  expect(screen.queryByText('copy-source')).not.toBeInTheDocument();
  view.unmount(); state.actions = { source: ['visible', 'edit'] }; openPage();
  fireEvent.click(screen.getByText('copy-source'));
  await waitFor(() => expect(state.create).toHaveBeenCalled());
  expect(state.create.mock.calls[0][4]).toEqual(expect.any(String));
  expect(state.create.mock.calls[0][5]).toBe(true);
});
