import { Button, notification } from "@bisheng/ui";
import { speechToText } from "@/controllers/API/workbench";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { VoiceSession } from "../../../../shared/voice/session";
import { getAsrWebSocketUrl } from "../../../../shared/voice/url";
import { useAudioPlayerStore, useAudioStore } from "./audioPlayerStore";

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
  const { t } = useTranslation("knowledge");
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<VoiceSession | null>(null);
  const callbacks = useRef(props);
  callbacks.current = props;
  const { stopAudio, setCurrentPlayingId } = useAudioPlayerStore();
  const { setIsLoading } = useAudioStore();
  const errorRef = useRef(() => {});
  errorRef.current = () =>
    notification.open({ description: t("voiceInput.failed"), type: "error" });

  useEffect(
    () => () => {
      sessionRef.current?.cancel();
    },
    [],
  );
  useEffect(() => {
    sessionRef.current?.stop();
  }, [props.stopSignal]);
  useEffect(() => {
    if (props.disabled) sessionRef.current?.cancel();
  }, [props.disabled]);

  const handleClick = () => {
    if (recording) {
      sessionRef.current?.stop();
      return;
    }
    if (sessionRef.current || props.disabled) return;
    stopAudio();
    setCurrentPlayingId(null);
    callbacks.current.onRecordingStart?.();
    const version =
      (window as Window & { chat_version?: string }).chat_version || "v1";
    const session = new VoiceSession(
      {
        realtime: !!props.realtime && version === "v1",
        modelId: props.modelId ?? "",
        websocketUrl: getAsrWebSocketUrl(import.meta.env.BASE_URL, window.location.origin),
        transcribe: async (form) => {
          const response: unknown = await speechToText(form, version);
          if (typeof response === "string") return response;
          if (
            response &&
            typeof response === "object" &&
            "data" in response &&
            typeof response.data === "string"
          )
            return response.data;
          return "";
        },
      },
      {
        onState: (active, pending) => {
          setRecording(active);
          setBusy(pending);
          setIsLoading(active);
          callbacks.current.onBusyChange?.(pending);
        },
        onText: (text) => callbacks.current.onChange(text),
        onError: () => errorRef.current(),
        onEnd: () => {
          sessionRef.current = null;
          callbacks.current.onRecordingEnd?.();
        },
      },
    );
    sessionRef.current = session;
    void session.start();
  };

  const label = t(recording ? "voiceInput.pause" : "voiceInput.start");
  return (
    <div className="absolute right-12 top-5">
      <Button
        type="button"
        size="small"
        iconOnly
        variant="text"
        color="default"
        className="h-6 w-6"
        disabled={!recording && (props.disabled || busy)}
        aria-label={label}
        title={label}
        aria-pressed={recording}
        onMouseDown={(event) => event.preventDefault()}
        onClick={handleClick}
      >
        {recording ? <Outlined.PlayerPause /> : <Outlined.Microphone />}
      </Button>
    </div>
  );
}

export default SpeechToTextComponent;
