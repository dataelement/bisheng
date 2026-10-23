/**
 * F071: the draggable split between the report and its cited source.
 *
 * The split is a ratio of the container, applied as a CSS clamp() so the panes
 * follow the container while it animates open (the chat column handing over its
 * width) without measuring on every frame. Each pane keeps a minimum width —
 * 400px on wide desktops, 360px below 1280px — and the ratio persists per
 * browser, like the channel split (pages/Subscription/hooks/useResizablePanel).
 */
import { useCallback, useRef, useState } from 'react';
import { useMediaQuery } from '~/hooks';

const STORAGE_KEY = 'linsight-citation-compare-ratio';
const KEY_STEP = 0.03;

function readRatio(): number | null {
    try {
        const saved = parseFloat(localStorage.getItem(STORAGE_KEY) || '');
        return saved > 0.1 && saved < 0.9 ? saved : null;
    } catch {
        return null;
    }
}

function saveRatio(ratio: number) {
    try {
        localStorage.setItem(STORAGE_KEY, ratio.toFixed(4));
    } catch {
        // Storage unavailable (private mode) — the split just isn't remembered.
    }
}

export function useCompareSplit() {
    const containerRef = useRef<HTMLDivElement>(null);
    const isWide = useMediaQuery('(min-width: 1280px)');
    const minPane = isWide ? 400 : 360;
    // Narrow desktops give the report a little more by default: it is the
    // document being read, the source is being glanced at.
    const [savedRatio, setSavedRatio] = useState<number | null>(readRatio);
    const ratio = savedRatio ?? (isWide ? 0.5 : 0.55);
    const [dragging, setDragging] = useState(false);

    const clampRatio = useCallback(
        (next: number) => {
            const width = containerRef.current?.getBoundingClientRect().width ?? 0;
            if (!width) return next;
            const min = Math.min(minPane / width, 0.5);
            return Math.min(Math.max(next, min), 1 - min);
        },
        [minPane],
    );

    const handlePointerDown = useCallback(
        (e: React.PointerEvent<HTMLElement>) => {
            const container = containerRef.current;
            if (!container || e.button !== 0) return;
            e.preventDefault();
            const handle = e.currentTarget;
            handle.setPointerCapture(e.pointerId);
            setDragging(true);
            document.body.style.userSelect = 'none';
            let latest = ratio;

            const handleMove = (ev: PointerEvent) => {
                const rect = container.getBoundingClientRect();
                latest = clampRatio((ev.clientX - rect.left) / rect.width);
                setSavedRatio(latest);
            };
            const handleUp = () => {
                setDragging(false);
                document.body.style.userSelect = '';
                saveRatio(latest);
                handle.removeEventListener('pointermove', handleMove);
                handle.removeEventListener('pointerup', handleUp);
                handle.removeEventListener('pointercancel', handleUp);
            };
            handle.addEventListener('pointermove', handleMove);
            handle.addEventListener('pointerup', handleUp);
            handle.addEventListener('pointercancel', handleUp);
        },
        [clampRatio, ratio],
    );

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
            e.preventDefault();
            const next = clampRatio(ratio + (e.key === 'ArrowLeft' ? -KEY_STEP : KEY_STEP));
            setSavedRatio(next);
            saveRatio(next);
        },
        [clampRatio, ratio],
    );

    return {
        containerRef,
        ratio,
        dragging,
        /** Report pane width; the source pane takes the rest. */
        leftStyle: { width: `clamp(${minPane}px, ${(ratio * 100).toFixed(2)}%, calc(100% - ${minPane}px))` },
        rightClassName: 'min-w-0',
        handlePointerDown,
        handleKeyDown,
    };
}
