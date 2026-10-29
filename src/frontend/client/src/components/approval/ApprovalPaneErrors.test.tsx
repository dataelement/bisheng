import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { normalizeApiError } from '@bisheng/api-client';
import { getMyApprovalTaskDetailApi, listMyApprovalTasksApi, decideApprovalTaskApi } from '~/api/approval';
import { ApprovalPane } from './ApprovalPane';
jest.mock('~/api/approval', () => ({
  listMyApprovalTasksApi: jest.fn(), listMyApprovalRequestsApi: jest.fn(),
  getMyApprovalTaskDetailApi: jest.fn(), getApprovalInstanceDetailApi: jest.fn(),
  decideApprovalTaskApi: jest.fn(), withdrawApprovalInstanceApi: jest.fn(), revokeMenuAccessGrantApi: jest.fn(),
}));
jest.mock('~/api/request', () => ({ showApiError: jest.fn() }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/utils', () => ({ cn: (...args: unknown[]) => args.filter(Boolean).join(' ') }));
jest.mock('../ui/ExpandableSearchField', () => ({ ExpandableSearchField: () => null }));
jest.mock('./ApprovalDetailPanels', () => ({ TaskDetailPanel: ({ detail }: { detail: { business_name: string } }) => <p>Detail {detail.business_name}</p>, RequestDetailPanel: () => null }));
jest.mock('./approvalPresentation', () => ({
  IN_PROGRESS_STATUSES: new Set(['pending']), StatusBadge: () => null,
  formatTime: () => '', formatTitle: (_scenario: string, name: string) => name,
  getId: (item: { task_id?: number; id?: number } | null) => item?.task_id ?? item?.id ?? null,
}));
beforeEach(() => jest.clearAllMocks());
const props = { open: true, activeTab: 'my_tasks' as const, compactView: 'detail' as const, setCompactView: jest.fn() };
it('clears an old detail when selecting a task whose detail fails, preventing a decision on the wrong task', async () => {
  const tasks = [{ task_id: 1, status: 'pending', business_name: 'First' }, { task_id: 2, status: 'pending', business_name: 'Second' }];
  (listMyApprovalTasksApi as jest.Mock).mockResolvedValue({ data: tasks });
  (getMyApprovalTaskDetailApi as jest.Mock).mockImplementation(async id => {
    if (id === 2) throw normalizeApiError({ status_code: 25001 }, { message: 'detail unavailable' });
    return tasks[0];
  });
  render(<ApprovalPane {...props} />);
  expect(await screen.findByText('Detail First')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Second'));
  await waitFor(() => expect(screen.queryByText('Detail First')).not.toBeInTheDocument());
  expect(await screen.findByRole('alert')).toHaveTextContent('detail unavailable');
  expect(screen.queryByRole('button', { name: 'com_approval_action_approve' })).not.toBeInTheDocument();
  expect(decideApprovalTaskApi).not.toHaveBeenCalled();
});
it('distinguishes a failed list from a successful empty list', async () => {
  (listMyApprovalTasksApi as jest.Mock).mockRejectedValue(new Error('list unavailable'));
  render(<ApprovalPane {...props} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('list unavailable');
  expect(screen.queryByText('com_approval_empty_list')).not.toBeInTheDocument();
});

it('releases a stale detail loader when refreshing the list fails', async () => {
  let finishDetail: (value: unknown) => void = () => undefined;
  (listMyApprovalTasksApi as jest.Mock).mockResolvedValueOnce({ data: [{ task_id: 1, status: 'pending', business_name: 'First' }] }).mockRejectedValueOnce(new Error('refresh unavailable'));
  (getMyApprovalTaskDetailApi as jest.Mock).mockImplementation(() => new Promise(resolve => { finishDetail = resolve; }));
  const view = render(<ApprovalPane {...props} />);
  await waitFor(() => expect(getMyApprovalTaskDetailApi).toHaveBeenCalledWith(1));
  view.rerender(<ApprovalPane {...props} open={false} />);
  view.rerender(<ApprovalPane {...props} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('refresh unavailable');
  await act(async () => { finishDetail({ task_id: 1, status: 'pending', business_name: 'First' }); });
  expect(screen.queryByText('com_approval_loading')).not.toBeInTheDocument();
  expect(screen.queryByText('Detail First')).not.toBeInTheDocument();
});


it('keeps the notification target selected after switching to processed tasks', async () => {
  const tasks = [
    { task_id: 1, instance_id: 40, status: 'cancelled', business_name: 'Other' },
    { task_id: 2, instance_id: 42, status: 'cancelled', business_name: 'Target' },
  ];
  (listMyApprovalTasksApi as jest.Mock).mockResolvedValue({ data: tasks });
  (getMyApprovalTaskDetailApi as jest.Mock).mockImplementation(async id => tasks.find(task => task.task_id === id));
  render(<ApprovalPane {...props} target={{ instanceId: 42 }} />);
  expect(await screen.findByText('Detail Target')).toBeInTheDocument();
  expect(getMyApprovalTaskDetailApi).not.toHaveBeenCalledWith(1);
});

it('reloads the exact target when another notification arrives in the same section', async () => {
  const tasks = [
    { task_id: 1, instance_id: 41, status: 'pending', business_name: 'First' },
    { task_id: 2, instance_id: 42, status: 'pending', business_name: 'Target' },
  ];
  (listMyApprovalTasksApi as jest.Mock).mockResolvedValue({ data: tasks });
  (getMyApprovalTaskDetailApi as jest.Mock).mockImplementation(async id => tasks.find(task => task.task_id === id));
  const view = render(<ApprovalPane {...props} target={{ instanceId: 41 }} />);
  await screen.findByText('Detail First');
  view.rerender(<ApprovalPane {...props} target={{ instanceId: 42 }} />);
  expect(await screen.findByText('Detail Target')).toBeInTheDocument();
});

it('does not open an unrelated record for an unavailable target', async () => {
  (listMyApprovalTasksApi as jest.Mock).mockResolvedValue({ data: [{ task_id: 1, instance_id: 40, status: 'pending', business_name: 'Other' }] });
  render(<ApprovalPane {...props} target={{ instanceId: 42 }} />);
  await waitFor(() => expect(listMyApprovalTasksApi).toHaveBeenCalled());
  expect(getMyApprovalTaskDetailApi).not.toHaveBeenCalled();
  expect(screen.queryByText('Detail Other')).not.toBeInTheDocument();
});
