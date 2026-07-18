/**
 * useScrollFade — soft top/bottom fade for a scrollable box.
 *
 * Returns a ref + onScroll handler + maskStyle to spread onto a scroll
 * container. The mask fades only the edge that still has hidden content (top
 * fades once scrolled down, bottom fades until scrolled to the end), so content
 * dissolves softly instead of being hard-cut by the overflow clip. Mirrors the
 * daily /c AiMessageBubble file-list fade. Pass `dep` (e.g. the text content) so
 * the fade re-measures when the content changes (streaming output).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';

/** Fade ramp height at each edge. */
const FADE = '12px';

export function useScrollFade<T extends HTMLElement>(dep?: unknown) {
    const ref = useRef<T>(null);
    const [fade, setFade] = useState<{ top: boolean; bottom: boolean }>({ top: false, bottom: false });

    const onScroll = useCallback(() => {
        const el = ref.current;
        if (!el) return;
        const top = el.scrollTop > 0;
        const bottom = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
        setFade((prev) => (prev.top === top && prev.bottom === bottom ? prev : { top, bottom }));
    }, []);

    // Re-measure on mount and whenever the content changes (e.g. streaming).
    useEffect(() => {
        onScroll();
    }, [onScroll, dep]);

    const maskStyle = useMemo<CSSProperties | undefined>(() => {
        if (!fade.top && !fade.bottom) return undefined;
        const topStop = fade.top ? FADE : '0';
        const bottomStop = fade.bottom ? `calc(100% - ${FADE})` : '100%';
        const value = `linear-gradient(to bottom, transparent, #000 ${topStop}, #000 ${bottomStop}, transparent)`;
        return { maskImage: value, WebkitMaskImage: value };
    }, [fade]);

    return { ref, onScroll, maskStyle };
}
