import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { normalizeApiError } from '@bisheng/api-client';
import { applyMenuAccessApi } from '~/api/approval';
import MenuUnavailablePage from './MenuUnavailablePage';
const mockToast = jest.fn();
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn(), useSearchParams: () => [new URLSearchParams('plugin=apps')] }));
jest.mock('~/api/approval', () => ({ applyMenuAccessApi: jest.fn(), checkMenuAccessPendingApi: jest.fn(async () => ({ has_pending: false })) }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: { menu_approval_mode_workbench: true, plugins: [] } }),
  useLocalize: () => (key: string) => key,
  useWorkbenchMenuNames: () => ({ apps: 'Applications' }),
}));
jest.mock('~/components/workbench/WorkbenchEmptyIllustration', () => ({ WorkbenchEmptyIllustration: () => null }));
beforeEach(() => jest.clearAllMocks());
it.each([false, true])('retains the reason and restores submit after an approval rejection, already presented=%s', async presented => {
  const error = normalizeApiError({ status_code: 25001, data: { reason: 'policy' } }, { message: 'An approval is already pending.' });
  if (presented) error.presentation = 'toast';
  (applyMenuAccessApi as jest.Mock).mockRejectedValue(error);
  render(<MenuUnavailablePage />);
  fireEvent.click(screen.getByRole('button', { name: 'com_menu_unavailable_apply_button' }));
  const reason = screen.getByPlaceholderText('com_menu_unavailable_reason_placeholder');
  fireEvent.change(reason, { target: { value: 'Need access for my work' } });
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_submit' }));
  await waitFor(() => expect(applyMenuAccessApi).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'com_ui_submit' })).toBeEnabled());
  expect(reason).toHaveValue('Need access for my work');
  expect(screen.getByRole('dialog')).toBeVisible();
  expect(mockToast).toHaveBeenCalledTimes(presented ? 0 : 1);
  if (!presented) expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({ message: error.message }));
});
