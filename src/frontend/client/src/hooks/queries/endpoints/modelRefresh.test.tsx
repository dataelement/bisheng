import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import AiModelSelect from '~/components/Chat/AiModelSelect';
import { dataService, QueryKeys, type BsConfig } from '~/types/chat';
import { useGetBsConfig } from './queries';

jest.mock('recoil', () => ({ useRecoilValue: () => true }));
jest.mock('~/store', () => ({ __esModule: true, default: { queriesEnabled: 'queries-enabled' } }));
jest.mock('~/api', () => ({ getKnowledgeStatusApi: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/types/chat', () => {
  const actual = jest.requireActual('~/types/chat');
  return { ...actual, dataService: { ...actual.dataService, getBishengConfig: jest.fn() } };
});

let client: QueryClient;
afterEach(() => { client?.clear(); focusManager.setFocused(undefined); jest.useRealTimers(); });

function mount() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onChange = jest.fn();
  function Picker() {
    const { data } = useGetBsConfig();
    return <AiModelSelect options={data?.models} value={42} disabled={false} onChange={onChange} />;
  }
  const view = render(<QueryClientProvider client={client}><Picker /></QueryClientProvider>);
  return { ...view, onChange };
}

const response = (displayName: string): BsConfig => ({
  applicationCenterWelcomeMessage: '', applicationCenterDescription: '', enable_etl4lm: false,
  sidebarIcon: { enabled: false, image: '' }, assistantIcon: { enabled: false, image: '' },
  welcomeMessage: '', functionDescription: '', inputPlaceholder: '',
  models: [{ id: '42', key: '42', name: 'qwen-max', displayName }],
  voiceInput: { enabled: false, model: '' },
  webSearch: { enabled: false, tool: '', bingKey: '', bingUrl: '', prompt: '' },
  knowledgeBase: { enabled: false, prompt: '' }, fileUpload: { enabled: false, prompt: '' },
  host: '', linsight_invitation_code: false, linsight_cache_dir: '', waiting_list_url: '',
});

test('refreshes a cleared alias on focus within the old five-minute cache and preserves selection', async () => {
  const fetch = jest.mocked(dataService.getBishengConfig);
  fetch.mockImplementationOnce(async () => response('Previous'))
    .mockImplementationOnce(async () => response(''))
    .mockImplementationOnce(async () => response('Renamed'));
  const { onChange } = mount();
  await screen.findByRole('button', { name: 'Previous' });
  await act(async () => { focusManager.setFocused(false); focusManager.setFocused(true); });
  await screen.findByRole('button', { name: 'qwen-max' });
  expect(screen.queryByText('Previous')).toBeNull();
  await act(async () => { focusManager.setFocused(false); focusManager.setFocused(true); });
  await screen.findByRole('button', { name: 'Renamed' });
  expect(onChange).toHaveBeenCalledTimes(0);
  expect(fetch).toHaveBeenCalledTimes(3);
});

test('keeps the current label on a failed read and applies the next successful empty alias', async () => {
  const fetch = jest.mocked(dataService.getBishengConfig);
  fetch.mockImplementationOnce(async () => response('Previous'))
    .mockRejectedValueOnce(new Error('offline'))
    .mockImplementationOnce(async () => response('   '));
  const log = jest.spyOn(console, 'error').mockImplementation(() => undefined);
  mount();
  await screen.findByRole('button', { name: 'Previous' });
  await act(async () => { focusManager.setFocused(false); focusManager.setFocused(true); });
  await waitFor(() => expect(client.getQueryState([QueryKeys.bishengConfig])?.status).toBe('error'));
  expect(screen.getByRole('button', { name: 'Previous' })).toBeInTheDocument();
  await act(async () => { focusManager.setFocused(false); focusManager.setFocused(true); });
  await screen.findByRole('button', { name: 'qwen-max' });
  log.mockRestore();
});


test('refreshes the selected label after 30 seconds while the same conversation remains mounted', async () => {
  jest.useFakeTimers();
  const fetch = jest.mocked(dataService.getBishengConfig);
  fetch.mockImplementationOnce(async () => response('Previous'))
    .mockImplementation(async () => response(''));
  const { onChange } = mount();
  await screen.findByRole('button', { name: 'Previous' });
  await act(async () => { jest.advanceTimersByTime(30_000); });
  await screen.findByRole('button', { name: 'qwen-max' });
  expect(onChange).toHaveBeenCalledTimes(0);
});
