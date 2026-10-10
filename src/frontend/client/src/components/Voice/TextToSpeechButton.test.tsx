import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import request from '~/api/request';
import { StandaloneChatContext } from '~/pages/standaloneChat/StandaloneChatContext';
import { TextToSpeechButton } from './TextToSpeechButton';

const mockPlayAudio = jest.fn(async (_messageId: string, load: () => Promise<string>) => load());
const originalBaseUrl = __APP_ENV__.BASE_URL;
afterEach(() => { __APP_ENV__.BASE_URL = originalBaseUrl; });
jest.mock('./textToSpeechStore', () => ({
  useAudioPlayer: () => ({ activeMessageId: null, isPlaying: false, isLoadingAudio: false, playAudio: mockPlayAudio }),
}));
jest.mock('~/api', () => ({ getWorkbenchModelListApi: jest.fn(), textToSpeech: jest.fn() }));
jest.mock('~/api/request', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/utils', () => ({ cn: (...names: string[]) => names.join(' ') }));
jest.mock('bisheng-icons', () => ({ Outlined: { VolumeNotice: () => null, Loading: () => null, PlayerPause: () => null } }));

test('mount loads only public config; clicking reads speech and preserves the absolute media URL', async () => {
  __APP_ENV__.BASE_URL = '/deployment';
  jest.mocked(request.get).mockResolvedValue({ data: { tts_model: { id: 'tts' } } });
  jest.mocked(request.post).mockResolvedValue({ data: 'https://media.example/speech.mp3' });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { unmount } = render(
    <QueryClientProvider client={client}>
      <StandaloneChatContext.Provider value={{ mode: 'guest', flowType: 'assistant', flowId: 'app-1', apiVersion: 'v3', autoRerunOnOpen: false }}>
        <TextToSpeechButton messageId="message-1" text="Read this" />
      </StandaloneChatContext.Provider>
    </QueryClientProvider>,
  );
  const play = await screen.findByRole('button', { name: 'Play' });
  expect(request.get).toHaveBeenCalledWith('/api/v3/llm/workbench?flow_id=app-1', { skip403Redirect: true });
  expect(request.post).not.toHaveBeenCalled();
  fireEvent.click(play);
  await waitFor(() => expect(request.post).toHaveBeenCalledWith(
    '/api/v3/llm/workbench/tts?flow_id=app-1', { text: 'Read this' }, { skip403Redirect: true },
  ));
  await expect(mockPlayAudio.mock.results[0].value).resolves.toBe('https://media.example/speech.mp3');
  unmount();
  client.clear();
});
