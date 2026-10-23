import i18next from 'i18next';
import messages from '../../../locales/en/api_errors.gen.json';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { normalizeApiError } from '@bisheng/api-client';
import { addSpaceTagApi, batchUpdateTagsApi, deleteSpaceTagApi, getSpaceTagsApi, updateFileTagsApi } from '~/api/knowledge';
import { EditTagsModal } from './EditTagsModal';

const mockNotify = jest.fn();
jest.mock('~/api/knowledge', () => ({ getSpaceTagsApi: jest.fn(), addSpaceTagApi: jest.fn(), updateFileTagsApi: jest.fn(), batchUpdateTagsApi: jest.fn(), deleteSpaceTagApi: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockNotify }) }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' '), getFullWidthLength: (value: string) => value.length }));
jest.mock('~/components/ui', () => ({ ...jest.requireActual('~/components/ui/dialog'), ...jest.requireActual('~/components/ui/button') }));

const reason = messages['10987'];
beforeAll(async () => { await i18next.init({ lng: 'en', resources: { en: { translation: { api_errors: messages } } } }); });
const failure = () => normalizeApiError({ status_code: 10987, status_message: 'PRIVATE server details' }, { message: 'PRIVATE server details' });
const onClose = jest.fn();
function mount(batch = false) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <EditTagsModal isOpen spaceId="space" fileId={batch ? undefined : '1'} fileIds={batch ? ['1', '2'] : undefined} onClose={onClose} />
  </QueryClientProvider>);
}
beforeEach(() => {
  window.showToast = mockNotify;
  jest.mocked(getSpaceTagsApi).mockReset().mockResolvedValue([{ id: 1, name: 'Report' }]);
});

it('preserves the reason when loading available tags fails', async () => {
  jest.mocked(getSpaceTagsApi).mockRejectedValueOnce(failure());
  mount();
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: reason })));
});

it.each([false, true])('preserves the reason when tag saving fails (batch=%s) and allows retry', async batch => {
  const save = jest.mocked(batch ? batchUpdateTagsApi : updateFileTagsApi);
  save.mockRejectedValueOnce(failure());
  mount(batch);
  await screen.findByText('Report');
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: reason })));
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'com_knowledge.confirm' })).not.toBeDisabled();
  save.mockResolvedValueOnce(undefined);
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  await waitFor(() => expect(onClose).toHaveBeenCalledWith(true));
});

it('preserves the reason when creating a tag fails', async () => {
  jest.mocked(addSpaceTagApi).mockRejectedValueOnce(failure());
  mount();
  await screen.findByText('Report');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'New' } });
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: reason })));
});

it('preserves the reason when deleting a tag fails', async () => {
  jest.mocked(deleteSpaceTagApi).mockRejectedValueOnce(failure());
  mount();
  await screen.findByText('Report');
  fireEvent.click(screen.getByTitle('com_knowledge.delete'));
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: reason })));
  expect(screen.getByText('Report')).toBeInTheDocument();
});

it.each(['canceled', 'global'] as const)('does not replace a %s error with a generic failure notice', async kind => {
  const error = normalizeApiError(kind === 'canceled' ? { code: 'ERR_CANCELED' } : { status_code: 500 }, { message: 'Handled elsewhere' });
  if (kind === 'global') error.presentation = 'global';
  jest.mocked(updateFileTagsApi).mockRejectedValueOnce(error);
  mount();
  await screen.findByText('Report');
  fireEvent.click(screen.getByRole('button', { name: 'com_knowledge.confirm' }));
  await waitFor(() => expect(updateFileTagsApi).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'com_knowledge.confirm' })).not.toBeDisabled());
  expect(mockNotify).not.toHaveBeenCalled();
});

it('keeps overlong tag names from being submitted', async () => {
  mount();
  await screen.findByText('Report');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '123456789' } });
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: 'com_knowledge.tags_char_limit_exceeded' })));
  expect(addSpaceTagApi).not.toHaveBeenCalled();
});

it('uses a local fallback for an unregistered tag failure while retaining the dialog', async () => {
  jest.mocked(getSpaceTagsApi).mockRejectedValueOnce(normalizeApiError({ status_code: 49999, status_message: 'PRIVATE' }, { message: 'PRIVATE' }));
  mount();
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: messages.fallback })));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
});
