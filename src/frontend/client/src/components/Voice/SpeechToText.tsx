import { Outlined } from 'bisheng-icons';
import { Pause } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useRecoilState } from 'recoil';
import { getVoice2TextApi } from '~/api';
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
  const { showToast } = useToastContext();
  const [interruptAudio] = useRecoilState(interruptAudioAtom);
  const [, setAudioOpening] = useRecordingAudioLoading();
  const errorRef = useRef(() => {});
  errorRef.current = () => showToast({ message: localize('voice_input.failed'), status: 'error' });

  useEffect(() => { sessionRef.current?.stop(); }, [interruptAudio]);
  useEffect(() => () => { sessionRef.current?.cancel(); }, []);
  useEffect(() => { sessionRef.current?.stop(); }, [props.stopSignal]);
  useEffect(() => { if (props.disabled) sessionRef.current?.cancel(); }, [props.disabled]);

  const handleClick = () => {
    if (recording) { sessionRef.current?.stop(); return; }
    if (sessionRef.current || props.disabled) return;
    callbacks.current.onRecordingStart?.();
    const session = new VoiceSession({
      realtime: !!props.realtime,
      modelId: props.modelId ?? '',
      websocketUrl: getAsrWebSocketUrl(import.meta.env.BASE_URL, window.location.origin),
      transcribe: async (form) => {
        const response = await getVoice2TextApi(form);
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
  };

  const label = localize(recording ? 'voice_input.pause' : 'voice_input.start');
  return (
    <Button
      type="button" size="icon" variant={recording ? 'outline' : 'default'}
      className="rounded-full w-8 h-8" disabled={!recording && (props.disabled || busy)}
      aria-label={label} title={label} aria-pressed={recording}
      onMouseDown={(event) => event.preventDefault()} onClick={handleClick}
    >
      {recording ? <Pause size={18} /> : <Outlined.Microphone size={18} />}
    </Button>
  );
}

export default SpeechToTextComponent;
