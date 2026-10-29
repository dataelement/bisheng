import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { getVoiceModels, transcribeVoice, type VoiceTarget } from '~/api/voice';
import { useVoiceTarget } from '~/hooks/useVoice';
import { VoiceSession } from '../../../../shared/voice/session';
import { SpeechToTextComponent } from './SpeechToText';

const mockVoiceHarness: {
  callbacks: { onState: (active: boolean, pending: boolean) => void } | null;
} = { callbacks: null };

jest.mock('~/api/voice', () => ({
  transcribeVoice: jest.fn(),
  getVoiceModels: jest.fn(),
  selectVoiceModels: (response: { data: unknown }) => response.data,
}));
jest.mock('~/hooks/useVoice', () => ({ useVoiceTarget: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('@bisheng/ui', () => ({
  Tooltip: ({ content, children }: { content: string; children: React.ReactNode }) => (
    <span data-tooltip={content}>{children}</span>
  ),
}));
jest.mock('~/components/ui', () => ({
  Button: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button
      onClick={props.onClick}
      disabled={props.disabled}
      aria-label={props['aria-label']}
      aria-pressed={props['aria-pressed']}
    />
  ),
}));
jest.mock('recoil', () => ({ useRecoilState: () => [false, jest.fn()] }));
jest.mock('./textToSpeechStore', () => ({
  interruptAudioAtom: {}, useRecordingAudioLoading: () => [false, jest.fn()],
}));
jest.mock('bisheng-icons', () => ({ Outlined: { Microphone: () => null, PlayerPause: () => null } }));
jest.mock('../../../../shared/voice/session', () => ({
  VoiceSession: jest.fn().mockImplementation((_options, callbacks) => {
    mockVoiceHarness.callbacks = callbacks;
    return {
      start: jest.fn().mockResolvedValue(undefined), stop: jest.fn(), cancel: jest.fn(),
    };
  }),
}));

test.each<[VoiceTarget, boolean, boolean]>([
  [{ version: 'v1' }, true, true],
  [{ version: 'v1' }, false, false],
  [{ version: 'v3', flowId: 'published-app' }, true, false],
])('routes voice for %j with realtime=%s', async (target, realtime, expectedRealtime) => {
  jest.mocked(VoiceSession).mockClear();
  jest.mocked(useVoiceTarget).mockReturnValue(target);
  jest.mocked(transcribeVoice).mockResolvedValue({ data: 'recognized text' });
  jest.mocked(getVoiceModels).mockResolvedValue({
    data: { asr_model: { id: 'current-asr', realtime } },
  });
  const { unmount } = render(
    <SpeechToTextComponent onChange={jest.fn()} modelId="asr-model" realtime={realtime} />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'voice_input.start' }));
  await waitFor(() => expect(VoiceSession).toHaveBeenCalled());
  const options = jest.mocked(VoiceSession).mock.calls[0][0];
  expect(options.realtime).toBe(expectedRealtime);
  expect(options.modelId).toBe('current-asr');
  expect(getVoiceModels).toHaveBeenCalledWith(target);
  const audio = new FormData();
  await expect(options.transcribe(audio)).resolves.toBe('recognized text');
  expect(transcribeVoice).toHaveBeenCalledWith(audio, target);
  unmount();
});

test('shows pause as soon as recording starts and start again after it stops', async () => {
  jest.mocked(VoiceSession).mockClear();
  mockVoiceHarness.callbacks = null;
  jest.mocked(useVoiceTarget).mockReturnValue({ version: 'v1' });
  let release: (value: Awaited<ReturnType<typeof getVoiceModels>>) => void = () => {};
  jest.mocked(getVoiceModels).mockReturnValue(new Promise((resolve) => {
    release = resolve;
  }));
  render(<SpeechToTextComponent onChange={jest.fn()} modelId="asr-model" realtime />);

  const hint = () => screen.getByRole('button').parentElement;
  expect(screen.getByRole('button', { name: 'voice_input.start' })).toHaveAttribute('aria-pressed', 'false');
  expect(hint()).toHaveAttribute('data-tooltip', 'voice_input.start');

  fireEvent.click(screen.getByRole('button', { name: 'voice_input.start' }));
  expect(screen.getByRole('button', { name: 'voice_input.pause' })).toHaveAttribute('aria-pressed', 'true');
  expect(hint()).toHaveAttribute('data-tooltip', 'voice_input.pause');

  await act(async () => {
    release({ data: { asr_model: { id: 'current-asr', realtime: true } } });
  });
  await waitFor(() => expect(VoiceSession).toHaveBeenCalled());
  expect(hint()).toHaveAttribute('data-tooltip', 'voice_input.pause');

  act(() => { mockVoiceHarness.callbacks?.onState(false, false); });
  expect(screen.getByRole('button', { name: 'voice_input.start' })).toHaveAttribute('aria-pressed', 'false');
  expect(hint()).toHaveAttribute('data-tooltip', 'voice_input.start');
});

test('returns to start when the click is cancelled before the session opens', async () => {
  jest.mocked(VoiceSession).mockClear();
  jest.mocked(useVoiceTarget).mockReturnValue({ version: 'v1' });
  let release: (value: Awaited<ReturnType<typeof getVoiceModels>>) => void = () => {};
  jest.mocked(getVoiceModels).mockReturnValue(new Promise((resolve) => {
    release = resolve;
  }));
  render(<SpeechToTextComponent onChange={jest.fn()} modelId="asr-model" realtime />);

  fireEvent.click(screen.getByRole('button', { name: 'voice_input.start' }));
  fireEvent.click(screen.getByRole('button', { name: 'voice_input.pause' }));
  expect(screen.getByRole('button', { name: 'voice_input.start' })).toBeInTheDocument();

  await act(async () => {
    release({ data: { asr_model: { id: 'current-asr', realtime: true } } });
  });
  expect(VoiceSession).not.toHaveBeenCalled();
});
