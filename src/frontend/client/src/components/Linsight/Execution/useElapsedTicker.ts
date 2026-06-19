/**
 * useElapsedTicker — group-level elapsed-time hook for task-mode timeline groups.
 *
 * Extracted from the daily /c DeepThinkingGroup timer so task-mode groups tick
 * with the *same* cadence and label math (zero drift from the North Star). While
 * `streaming` is true a 100ms interval re-renders the consumer so a live "用时 N
 * 秒" counter advances; once streaming stops the interval is cleared and the
 * elapsed value freezes at `endMs - startMs`.
 *
 * Wall-clock contract (mirrors DeepThinkingGroup):
 * - `startMs == null`            → no clock; elapsedMs = 0 (caller hides 用时).
 * - streaming                    → elapsedMs = now - startMs (live).
 * - closed with `endMs != null`  → elapsedMs = endMs - startMs (frozen).
 * - closed with `endMs == null`  → elapsedMs = 0 (no end stamp; avoid creeping
 *                                   the label upward against Date.now()).
 *
 * `Date.now()` is only ever read while the component is mounted and rendering,
 * which is valid at runtime (the surrounding workflow-script restriction does
 * not apply to component code).
 */
import { useEffect, useState } from 'react';

export interface ElapsedTicker {
    /** Elapsed milliseconds for the group (0 when unknown — caller hides 用时). */
    elapsedMs: number;
    /** Mirrors `streaming`; convenient for "正在…" vs "已…" label branching. */
    running: boolean;
}

/**
 * Format a duration for the "用时 N 秒" label. Always one decimal place so a
 * sub-second / same-second span never collapses to a bare "0 秒" (e.g. "0.4",
 * "3.4", "142.0"). Non-positive durations render "0.0".
 */
export function formatSeconds(ms: number): string {
    const sec = !ms || ms <= 0 ? 0 : ms / 1000;
    return sec.toFixed(1);
}

/**
 * @param startMs   group start wall-clock (ms); null/undefined ⇒ no clock.
 * @param endMs     group end wall-clock (ms); read only when not streaming.
 * @param streaming true while the group is still open/active.
 */
export function useElapsedTicker(
    startMs: number | null | undefined,
    endMs: number | null | undefined,
    streaming: boolean,
): ElapsedTicker {
    // Live-tick while streaming so the consumer re-renders every 100ms and the
    // header counter advances. The tick value itself is unused — it exists only
    // to trigger re-render; the elapsed math below reads Date.now() fresh.
    const [, setTick] = useState(0);
    useEffect(() => {
        if (!streaming) return;
        const id = window.setInterval(() => setTick((t) => t + 1), 100);
        return () => window.clearInterval(id);
    }, [streaming]);

    let elapsedMs = 0;
    if (startMs != null) {
        if (streaming) {
            elapsedMs = Math.max(0, Date.now() - startMs);
        } else if (endMs != null) {
            // Closed group with a real end stamp: freeze at the measured span.
            elapsedMs = Math.max(0, endMs - startMs);
        }
        // Closed with no end stamp ⇒ leave elapsedMs at 0 so the label hides the
        // 用时 clause rather than creeping upward against Date.now().
    }

    return { elapsedMs, running: streaming };
}
