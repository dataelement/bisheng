/**
 * NarrationTicker — a single-line "live thought" ticker for the task-mode
 * execution flow (R2 旁白).
 *
 * The model's reasoning streams token-by-token, which made the old narration line
 * churn through half-words and run-ons. This component shows ONE complete sentence
 * at a time. Two mechanisms keep it calm when a lot of content streams at once:
 *
 *  1. Single-flight + coalescing: only ONE crossfade runs at a time. If several
 *     sentences complete during a transition, the ticker jumps straight to the
 *     LATEST one when the current transition ends — intermediate sentences are
 *     skipped (the full reasoning lives in the expandable body), so the line never
 *     blurs through a stack of overlapping animations ("虚影").
 *  2. A dwell after each transition keeps every shown sentence readable instead of
 *     flickering past.
 *
 * The crossfade itself (narration-in / narration-out keyframes) staggers opacity so
 * the outgoing and incoming lines are never both visible — no ghost frame. Honors
 * prefers-reduced-motion (instant swap, still paced by the dwell). Quiet (Muted,
 * single clamped line) so it sits under a group header as an aside.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// Narration sits one notch lighter than the node title — quiet meta under the header.
const NARRATION_COLOR = '#999999';

interface NarrationTickerProps {
    /** the current COMPLETE narration sentence; '' / unchanged updates are held */
    text: string;
}

// Keep in sync with the narration-in/out keyframe duration in tailwind.config.cjs.
const ANIM_MS = 500;
// Minimum time a sentence stays fully shown before the next transition may start,
// so a burst of completed sentences reads one-at-a-time instead of blurring past.
const DWELL_MS = 900;

export function NarrationTicker({ text }: NarrationTickerProps) {
    const [displayed, setDisplayed] = useState('');
    const [leaving, setLeaving] = useState('');
    // Monotonic key so each transition remounts the spans → the CSS animation
    // replays even when text is structurally similar.
    const [cycle, setCycle] = useState(0);

    const targetRef = useRef(''); // latest complete sentence from props
    const displayedRef = useRef(''); // what is currently settled on screen
    const busyRef = useRef(false); // a transition + dwell is in flight
    const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

    // Run ONE transition toward the latest target, then (after dwell) re-check for a
    // newer target accumulated meanwhile. No-op when idle target == displayed.
    const pump = useCallback(() => {
        if (busyRef.current) return;
        const target = targetRef.current;
        const cur = displayedRef.current;
        if (!target || target === cur) return;

        busyRef.current = true;
        if (cur) setLeaving(cur); // animate the prior sentence out (none for the first)
        displayedRef.current = target;
        setDisplayed(target);
        setCycle((c) => c + 1);

        const t1 = setTimeout(() => setLeaving(''), ANIM_MS);
        const t2 = setTimeout(() => {
            busyRef.current = false;
            pump(); // jump to whatever the latest target is now (coalesced)
        }, ANIM_MS + DWELL_MS);
        timersRef.current.push(t1, t2);
    }, []);

    useEffect(() => {
        // Hold the last complete sentence: ignore empty (a new thinking passage that
        // hasn't finished its first sentence) so the ticker never blanks mid-run.
        if (text) targetRef.current = text;
        pump();
    }, [text, pump]);

    useEffect(() => {
        const timers = timersRef.current;
        return () => timers.forEach(clearTimeout);
    }, []);

    if (!displayed && !leaving) return null;

    return (
        // Fixed one-line height + overflow-hidden so the rolling text is clipped to
        // the line box and the row never reflows as sentences swap.
        <div className="relative mt-0.5 h-5 overflow-hidden">
            {leaving && (
                <span
                    key={`out-${cycle}`}
                    className="absolute inset-x-0 top-0 block animate-narration-out truncate text-xs leading-5 motion-reduce:animate-none"
                    style={{ color: NARRATION_COLOR }}
                >
                    {leaving}
                </span>
            )}
            {displayed && (
                <span
                    key={`in-${cycle}`}
                    className="block animate-narration-in truncate text-xs leading-5 motion-reduce:animate-none"
                    style={{ color: NARRATION_COLOR }}
                >
                    {displayed}
                </span>
            )}
        </div>
    );
}
