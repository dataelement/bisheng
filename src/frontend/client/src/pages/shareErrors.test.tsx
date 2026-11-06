import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { normalizeApiError } from '@bisheng/api-client';
import { getShareParamsApi } from '~/api';
import Share from './share';
const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({ useParams: () => ({ token: 'test-token' }), useNavigate: () => mockNavigate }));
jest.mock('~/api', () => ({ getShareParamsApi: jest.fn() }));
jest.mock('~/api/request', () => ({ showApiError: jest.fn((error: unknown) => error) }));
jest.mock('~/components/Chat/ChatView', () => () => <div>Shared conversation</div>);
jest.mock('~/components/Sop', () => () => null);
jest.mock('./appChat', () => () => null);
jest.mock('~/utils', () => ({ generateUUID: () => 'test-id' }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
afterEach(() => jest.clearAllMocks());
it('redirects an expired share instead of leaving an empty page', async () => {
  (getShareParamsApi as jest.Mock).mockRejectedValue(normalizeApiError({ status_code: 404 }, { message: 'expired' }));
  render(<Share />);
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/404', { replace: true }));
});
it('renders a retryable network failure and can recover the shared conversation', async () => {
  (getShareParamsApi as jest.Mock).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ data: { resource_type: 'workbench_chat', resource_id: 7 } });
  render(<Share />);
  expect(await screen.findByRole('alert')).toHaveTextContent('offline');
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_retry' }));
  expect(await screen.findByText('Shared conversation')).toBeVisible();
  expect(mockNavigate).not.toHaveBeenCalled();
});
it('keeps maintenance handling on the share route', async () => {
  const error = normalizeApiError({ status_code: 500 }, { message: 'maintenance' });
  error.presentation = 'global';
  (getShareParamsApi as jest.Mock).mockRejectedValue(error);
  render(<Share />);
  expect(await screen.findByRole('alert')).toHaveTextContent('maintenance');
  expect(mockNavigate).not.toHaveBeenCalled();
});
