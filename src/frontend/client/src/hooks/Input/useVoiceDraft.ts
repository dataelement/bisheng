import { useRef, useState, type RefObject } from "react";
import { VoiceDraft } from "../../../../shared/voice/draft";

export function useVoiceDraft(
  ref: RefObject<HTMLTextAreaElement>,
  value: string,
  setValue: (value: string) => void,
) {
  const draft = useRef<VoiceDraft | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;
  const composing = useRef(false);
  const pending = useRef<string | null>(null);
  const ended = useRef(false);
  const [busy, setBusy] = useState(false);
  const [stopSignal, setStopSignal] = useState(0);

  const apply = (transcript: string) => {
    if (!draft.current) return;
    if (composing.current) {
      pending.current = transcript;
      return;
    }
    const next = draft.current.apply(valueRef.current, transcript);
    valueRef.current = next;
    setValue(next);
  };
  return {
    busy,
    handleEdit: (next: string) => {
      const previous = valueRef.current;
      valueRef.current = next;
      if (!draft.current || next === previous) return;
      draft.current.freeze();
      setStopSignal((signal) => signal + 1);
    },
    compositionStart: () => {
      composing.current = true;
      if (!draft.current) return;
      draft.current.freeze();
      setStopSignal((signal) => signal + 1);
    },
    compositionEnd: () => {
      composing.current = false;
      if (pending.current !== null && draft.current && !draft.current.isFrozen())
        apply(pending.current);
      pending.current = null;
      if (ended.current) draft.current = null;
    },
    props: {
      stopSignal,
      onBusyChange: setBusy,
      onRecordingStart: () => {
        const current = ref.current?.value ?? valueRef.current;
        valueRef.current = current;
        draft.current = new VoiceDraft(
          current,
          ref.current && document.activeElement === ref.current
            ? ref.current.selectionEnd
            : current.length,
        );
        ended.current = false;
      },
      onRecordingEnd: () => {
        ended.current = true;
        if (!composing.current) draft.current = null;
      },
      onChange: apply,
    },
  };
}
