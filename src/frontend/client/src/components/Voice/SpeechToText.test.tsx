import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { getVoiceModels, transcribeVoice, type VoiceTarget } from '~/api/voice';
import { useVoiceTarget } from '~/hooks/useVoice';
import { VoiceSession } from '../../../../shared/voice/session';
import { SpeechToTextComponent } from './SpeechToText';

jest.mock('~/api/voice', () => ({
  transcribeVoice: jest.fn(),
  getVoiceModels: jest.fn(),
  selectVoiceModels: (response: { data: unknown }) => response.data,
}));
jest.mock('~/hooks/useVoice', () => ({ useVoiceTarget: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/components/ui', () => ({
  Button: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button onClick={props.onClick} disabled={props.disabled} aria-label={props['aria-label']} />
  ),
}));
jest.mock('recoil', () => ({ useRecoilState: () => [false, jest.fn()] }));
jest.mock('./textToSpeechStore', () => ({
  interruptAudioAtom: {}, useRecordingAudioLoading: () => [false, jest.fn()],
}));
jest.mock('bisheng-icons', () => ({ Outlined: { Microphone: () => null, PlayerPause: () => null } }));
jest.mock('../../../../shared/voice/session', () => ({
  VoiceSession: jest.fn().mockImplementation(() => ({
    start: jest.fn().mockResolvedValue(undefined), stop: jest.fn(), cancel: jest.fn(),
  })),
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
