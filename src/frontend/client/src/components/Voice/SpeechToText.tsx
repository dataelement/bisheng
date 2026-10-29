import { Tooltip as SharedTooltip } from "@bisheng/ui";
import { isApiError } from "@bisheng/api-client";
import { showApiError } from "~/api/request";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState } from "react";
import { useRecoilState } from "recoil";
import { getVoiceModels, selectVoiceModels, transcribeVoice } from "~/api/voice";
import { useVoiceTarget } from "~/hooks/useVoice";
import { Button } from "~/components/ui";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { VoiceSession } from "../../../../shared/voice/session";
import { getAsrWebSocketUrl } from "../../../../shared/voice/url";
import { interruptAudioAtom, useRecordingAudioLoading } from "./textToSpeechStore";

interface SpeechToTextProps {
  disabled?: boolean;
  realtime?: boolean;
  modelId?: string;
  stopSignal?: number;
  onChange: (text: string) => void;
  onRecordingStart?: (realtime?: boolean) => void;
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
  const errorRef = useRef<(error?: unknown) => void>(() => {});
  const startingRef = useRef(false);
  const attemptRef = useRef(0);
  const armedRef = useRef(false);
  const seenStop = useRef(props.stopSignal);
  errorRef.current = (error) => {
    if (isApiError(error)) showApiError(error);
    else showToast({ message: localize("voice_input.failed"), status: "error" });
  };

  const dropAttempt = () => {
    attemptRef.current += 1;
    startingRef.current = false;
    armedRef.current = false;
    setRecording(false);
  };

  useEffect(() => {
    if (sessionRef.current) sessionRef.current.stop();
    else if (armedRef.current) dropAttempt();
    // The recording hint must clear even when the session has not opened yet.

  }, [interruptAudio]);
  useEffect(
    () => () => {
      sessionRef.current?.cancel();
    },
    [],
  );
  useEffect(() => {
    if (seenStop.current === props.stopSignal) return;
    seenStop.current = props.stopSignal;
    if (sessionRef.current) sessionRef.current.stop();
    else dropAttempt();
  }, [props.stopSignal]);
  useEffect(() => {
    if (!props.disabled) return;
    dropAttempt();
    sessionRef.current?.cancel();
  }, [props.disabled]);

  const handleClick = () => {
    if (recording) {
      if (sessionRef.current) sessionRef.current.stop();
      else dropAttempt();
      return;
    }
    if (props.disabled || startingRef.current) return;
    void begin();
  };

  const begin = async () => {
    const attempt = ++attemptRef.current;
    startingRef.current = true;
    armedRef.current = true;
    setRecording(true);
    try {
      // The button was rendered from a cached model. Read the current one so an
      // admin switch does not require a full page reload.
      const models = selectVoiceModels(await getVoiceModels(voiceTarget));
      if (attempt !== attemptRef.current) return;
      const modelId = models.asr_model?.id ? String(models.asr_model.id) : "";
      if (!modelId || sessionRef.current || callbacks.current.disabled) {
        armedRef.current = false;
        setRecording(false);
        if (!modelId) errorRef.current();
        return;
      }
      const realtime = voiceTarget.version === "v1" && !!models.asr_model?.realtime;
      callbacks.current.onRecordingStart?.(realtime);
      const session = new VoiceSession(
        {
          realtime,
          modelId,
          websocketUrl: getAsrWebSocketUrl(import.meta.env.BASE_URL, window.location.origin),
          transcribe: async (form) => {
            const response = await transcribeVoice(form, voiceTarget);
            return typeof response.data === "string" ? response.data : "";
          },
        },
        {
          onState: (active, pending) => {
            setRecording(active);
            setBusy(pending);
            setAudioOpening(active);
            callbacks.current.onBusyChange?.(pending);
          },
          onText: (text) => callbacks.current.onChange(text),
          onError: (error) => errorRef.current(error),
          onEnd: () => {
            sessionRef.current = null;
            callbacks.current.onRecordingEnd?.();
          },
        },
      );
      if (attempt !== attemptRef.current) return;
      armedRef.current = false;
      sessionRef.current = session;
      void session.start();
    } catch (error) {
      if (attempt === attemptRef.current) {
        armedRef.current = false;
        setRecording(false);
        errorRef.current(error);
      }
    } finally {
      if (attempt === attemptRef.current) startingRef.current = false;
    }
  };

  const label = localize(recording ? "voice_input.pause" : "voice_input.start");
  return (
    <SharedTooltip content={label}>
      <Button
        type="button"
        size="icon"
        variant={recording ? "outline" : "default"}
        className="dsh-composer-voice rounded-full"
        disabled={!recording && (props.disabled || busy)}
        aria-label={label}
        aria-pressed={recording}
        onMouseDown={(event) => event.preventDefault()}
        onClick={handleClick}
      >
        {recording ? <Outlined.PlayerPause size={18} /> : <Outlined.Microphone size={18} />}
      </Button>
    </SharedTooltip>
  );
}

export default SpeechToTextComponent;
