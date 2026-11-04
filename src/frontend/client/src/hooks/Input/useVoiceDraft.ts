import { useLayoutEffect, useRef, useState, type RefObject } from "react";
import { VoiceDraft } from "../../../../shared/voice/draft";

export function useVoiceDraft(
  ref: RefObject<HTMLTextAreaElement | HTMLDivElement>,
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
  const caretRef = useRef<number | null>(null);

  const apply = (transcript: string) => {
    if (!draft.current) return;
    if (composing.current) {
      pending.current = transcript;
      return;
    }
    const next = draft.current.apply(valueRef.current, transcript);
    if (next !== value) caretRef.current = draft.current.caret();
    valueRef.current = next;
    setValue(next);
  };
  useLayoutEffect(() => {
    const element = ref.current;
    const caret = caretRef.current;
    if (!element || caret == null) return;
    caretRef.current = null;
    if (element instanceof HTMLTextAreaElement) {
      const pos = Math.max(0, Math.min(caret, element.value.length));
      element.setSelectionRange(pos, pos);
    } else {
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
        acceptNode: (node) => node.parentElement?.closest("[data-composer-reference]")
          ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
      });
      let remaining = caret;
      let node = walker.nextNode();
      const range = document.createRange();
      range.selectNodeContents(element);
      range.collapse(false);
      while (node) {
        const length = node.textContent?.length ?? 0;
        if (remaining <= length) { range.setStart(node, remaining); range.collapse(true); break; }
        remaining -= length;
        node = walker.nextNode();
      }
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
    }
  }, [ref, value]);
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
      onRecordingStart: (...mode: [boolean?]) => {
        void mode;
        const element = ref.current;
        const current = element instanceof HTMLTextAreaElement ? element.value : valueRef.current;
        valueRef.current = current;
        draft.current = new VoiceDraft(
          current,
          ref.current && document.activeElement === ref.current
            ? (element instanceof HTMLTextAreaElement ? element.selectionEnd : editorCaret(element, current.length))
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

function editorCaret(element: HTMLDivElement | null, fallback: number): number {
  const selection = window.getSelection();
  if (!element || !selection?.rangeCount || !element.contains(selection.focusNode)) return fallback;
  const range = document.createRange();
  range.selectNodeContents(element);
  range.setEnd(selection.focusNode!, selection.focusOffset);
  const fragment = range.cloneContents();
  fragment.querySelectorAll("[data-composer-reference]").forEach(node => node.remove());
  return fragment.textContent?.length ?? fallback;
}
