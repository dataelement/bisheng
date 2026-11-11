import { useCallback, useRef, type PointerEvent } from "react";

/** A touch-capable computer can still send with its mouse or keyboard. */
export function useSendInputMethod() {
  const pointerType = useRef("");
  const onSendPointerDown = useCallback((event: PointerEvent) => {
    pointerType.current = event.pointerType;
  }, []);
  const consumeTouchSend = useCallback((event: { detail: number }) => {
    const touchSend = event.detail > 0 && pointerType.current === "touch";
    pointerType.current = "";
    return touchSend;
  }, []);
  return { onSendPointerDown, consumeTouchSend };
}
