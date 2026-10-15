import { useState } from "react";
import type { ClipboardEvent, CompositionEvent } from "react";

export function normalizeSubjectKeyword(value: string): string {
  return value.replace(/\r\n|[\r\n]/g, " ").replace(
    /^[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,
    "",
  );
}

export function useSubjectKeyword() {
  const [keyword, setKeyword] = useState("");
  const [composing, setComposing] = useState(false);
  const normalized = normalizeSubjectKeyword(keyword);
  const tooLong = Array.from(normalized).length > 255;
  return {
    keyword, setKeyword, normalized, tooLong, composing,
    onCompositionStart: () => setComposing(true),
    onCompositionEnd: (event: CompositionEvent<HTMLInputElement>) => {
      setKeyword(event.currentTarget.value);
      setComposing(false);
    },
    onPaste: (event: ClipboardEvent<HTMLInputElement>) => {
      const text = event.clipboardData.getData("text");
      if (!/[\r\n]/.test(text)) return;
      event.preventDefault();
      const input = event.currentTarget;
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? start;
      const replacement = text.replace(/\r\n|[\r\n]/g, " ");
      setKeyword(input.value.slice(0, start) + replacement + input.value.slice(end));
    },
  };
}
