import { fireEvent, render, screen } from '@testing-library/react';
import { DesktopSettingsPane } from './DesktopSettingsPane';

const mockReport = jest.fn();
const mockLogout = jest.fn();
let mockPersonalTokenEnabled = false;
let mockUsageError = true;
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: { username: 'Employee', avatar: '' }, logout: mockLogout }) }));
jest.mock('~/hooks/useVersionManagementEnabled', () => ({ usePersonalTokenEnabled: () => mockPersonalTokenEnabled }));
jest.mock('@tanstack/react-query', () => ({ useQuery: () => ({ isLoading: false, isError: mockUsageError, data: mockUsageError ? undefined : {}, refetch: jest.fn() }) }));
jest.mock('~/components/Settings/sections/AccountSection', () => ({ AccountSection: ({ username }: { username: string }) => <div>editor:{username}</div> }));
jest.mock('~/components/Settings/sections/StorageSection', () => ({ StorageSection: () => <div>cloud-storage</div> }));
jest.mock('~/components/dsh/DshUsageCalendar', () => ({ DshUsageCalendar: () => <div>usage-calendar</div> }));
jest.mock('./AiAccessPane', () => ({ AiAccessPane: () => <div>ai-access</div> }));
jest.mock('~/components/approval/ApprovalPane', () => ({ ApprovalPane: ({ compactView, setCompactView }: { compactView: string; setCompactView: (view: 'list' | 'detail') => void }) => <div><span>approval-pane</span><output data-testid="compact-view">{compactView}</output><button onClick={() => setCompactView('list')}>approval-list</button></div> }));
jest.mock('~/components/messageApproval/NotificationPane', () => ({ NotificationPane: ({ onOpenApprovalCenter }: { onOpenApprovalCenter: (target: { tab: 'my_tasks'; taskId: number }) => void }) => <button onClick={() => onOpenApprovalCenter({ tab: 'my_tasks', taskId: 42 })}>open-approval</button> }));

beforeEach(() => { mockPersonalTokenEnabled = false; mockUsageError = true; window.dshChatPresentation = { reportLanding: jest.fn(), reportSettings: mockReport }; mockReport.mockClear(); });
afterEach(() => { delete window.dshChatPresentation; });
it('reuses the account editor without a second logout or desktop-download flow', () => {
  render(<DesktopSettingsPane section="account" />);
  expect(screen.getByText('editor:Employee')).toBeTruthy();
  expect(screen.queryByRole('navigation')).toBeNull();
  expect(screen.queryByText('com_nav_log_out')).toBeNull();
  expect(screen.queryByText('dsh_download')).toBeNull();
  expect(mockLogout).not.toHaveBeenCalled();
  expect(mockReport).toHaveBeenCalledWith('account');
});
it('keeps storage visible when the separate usage request fails', () => {
  render(<DesktopSettingsPane section="desktop-usage" />);
  expect(screen.getByText('cloud-storage')).toBeTruthy();
  expect(screen.getByRole('alert').textContent).toContain('dsh_load_error');
  expect(mockReport).toHaveBeenCalledWith('desktop-usage');
});
it('opens approval details within notifications without changing host selection', () => {
  render(<DesktopSettingsPane section="notifications" />);
  fireEvent.click(screen.getByRole('button', { name: 'open-approval' }));
  expect(screen.getByText('approval-pane')).toBeTruthy();
  expect(screen.getByTestId('compact-view').textContent).toBe('detail');
  fireEvent.click(screen.getByRole('button', { name: 'approval-list' }));
  expect(screen.getByTestId('compact-view').textContent).toBe('list');
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  expect(screen.getByRole('button', { name: 'open-approval' })).toBeTruthy();
  expect(mockReport).toHaveBeenCalledTimes(1);
  expect(mockReport).toHaveBeenCalledWith('notifications');
});
it('reports ready only after storage and usage content is mounted', () => {
  mockUsageError = false;
  mockReport.mockImplementationOnce(() => {
    expect(screen.getByText('cloud-storage')).toBeTruthy();
    expect(screen.getByText('usage-calendar')).toBeTruthy();
  });
  render(<DesktopSettingsPane section="desktop-usage" />);
  expect(mockReport).toHaveBeenCalledWith('desktop-usage');
});
it('honors the personal AI access deployment flag', () => {
  const { rerender } = render(<DesktopSettingsPane section="ai-access" />);
  expect(screen.queryByText('ai-access')).toBeNull();
  expect(screen.getByRole('status').textContent).toBe('com_ai_access.disabled_notice');
  mockPersonalTokenEnabled = true;
  rerender(<DesktopSettingsPane section="ai-access" />);
  expect(screen.getByText('ai-access')).toBeTruthy();
});
it.each(['my-tasks', 'my-requests'] as const)('mounts the approval content for %s', section => {
  render(<DesktopSettingsPane section={section} />);
  expect(screen.getByText('approval-pane')).toBeTruthy();
  expect(mockReport).toHaveBeenCalledWith(section);
});
it('returns Escape to the host while respecting nested dialogs and removing listeners on teardown', () => {
  const close = jest.fn();
  window.dshChatPresentation!.requestSettingsClose = close;
  const { unmount } = render(<DesktopSettingsPane section="account" />);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(close).toHaveBeenCalledTimes(1);
  const dialog = document.createElement('div');
  dialog.setAttribute('role', 'dialog');
  dialog.dataset.state = 'open';
  document.body.append(dialog);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(close).toHaveBeenCalledTimes(1);
  dialog.remove();
  unmount();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(close).toHaveBeenCalledTimes(1);
});
