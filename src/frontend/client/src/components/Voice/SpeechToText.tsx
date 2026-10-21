import { Outlined } from 'bisheng-icons';
import { useEffect, useRef, useState } from 'react';
import { useRecoilState } from 'recoil';
import { getVoiceModels, selectVoiceModels, transcribeVoice } from '~/api/voice';
import { useVoiceTarget } from '~/hooks/useVoice';
import { Button } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { useToastContext } from '~/Providers';
import { VoiceSession } from '../../../../shared/voice/session';
import { getAsrWebSocketUrl } from '../../../../shared/voice/url';
import { interruptAudioAtom, useRecordingAudioLoading } from './textToSpeechStore';

interface SpeechToTextProps {
  disabled?: boolean;
  realtime?: boolean;
  modelId?: string;
  stopSignal?: number;
  onChange: (text: string) => void;
  onRecordingStart?: () => void;
  onRecordingEnd?: () => void;
  onBusyChange?: (busy: boolean) => void;
}

export function SpeechToTextComponent(props: SpeechToTextProps) {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<VoiceSession | null>(null);
  const callbacks = useRef(props);
  callbacks.current = props;
  const localize = useLocalize();
  const voiceTarget = useVoiceTarget();
  const { showToast } = useToastContext();
  const [interruptAudio] = useRecoilState(interruptAudioAtom);
  const [, setAudioOpening] = useRecordingAudioLoading();
  const errorRef = useRef(() => {});
  const startingRef = useRef(false);
  errorRef.current = () => showToast({ message: localize('voice_input.failed'), status: 'error' });

  useEffect(() => { sessionRef.current?.stop(); }, [interruptAudio]);
  useEffect(() => () => { sessionRef.current?.cancel(); }, []);
  useEffect(() => { sessionRef.current?.stop(); }, [props.stopSignal]);
  useEffect(() => { if (props.disabled) sessionRef.current?.cancel(); }, [props.disabled]);

  const handleClick = () => {
    if (recording) { sessionRef.current?.stop(); return; }
    if (sessionRef.current || props.disabled || startingRef.current) return;
    void begin();
  };

  const begin = async () => {
    startingRef.current = true;
    try {
      // The button was rendered from a cached model. Read the current one so an
      // admin switch does not require a full page reload.
      const models = selectVoiceModels(await getVoiceModels(voiceTarget));
      const modelId = models.asr_model?.id ? String(models.asr_model.id) : '';
      if (!modelId || sessionRef.current || callbacks.current.disabled) {
        if (!modelId) errorRef.current();
        return;
      }
      callbacks.current.onRecordingStart?.();
      const session = new VoiceSession({
        realtime: voiceTarget.version === 'v1' && !!models.asr_model?.realtime,
        modelId,
        websocketUrl: getAsrWebSocketUrl(import.meta.env.BASE_URL, window.location.origin),
        transcribe: async (form) => {
          const response = await transcribeVoice(form, voiceTarget);
          return typeof response.data === 'string' ? response.data : '';
        },
      }, {
        onState: (active, pending) => {
          setRecording(active);
          setBusy(pending);
          setAudioOpening(active);
          callbacks.current.onBusyChange?.(pending);
        },
        onText: (text) => callbacks.current.onChange(text),
        onError: () => errorRef.current(),
        onEnd: () => {
          sessionRef.current = null;
          callbacks.current.onRecordingEnd?.();
        },
      });
      sessionRef.current = session;
      void session.start();
    } catch {
      errorRef.current();
    } finally {
      startingRef.current = false;
    }
  };

  const label = localize(recording ? 'voice_input.pause' : 'voice_input.start');
  return (
    <Button
      type="button" size="icon" variant={recording ? 'outline' : 'default'}
      className="rounded-full w-8 h-8" disabled={!recording && (props.disabled || busy)}
      aria-label={label} title={label} aria-pressed={recording}
      onMouseDown={(event) => event.preventDefault()} onClick={handleClick}
    >
      {recording ? <Outlined.PlayerPause size={18} /> : <Outlined.Microphone size={18} />}
    </Button>
  );
}

export default SpeechToTextComponent;
