/**
 * NarrationTicker — a single-line "live thought" ticker for the task-mode
 * execution flow (R2 旁白).
 *
 * The model's reasoning streams token-by-token, which made the old narration line
 * churn through half-words and run-ons. This component shows ONE complete sentence
 * at a time and only advances when a genuinely new sentence arrives (empty / equal
 * updates are ignored, so it never flickers blank between thinking passages). When
 * it does advance, the outgoing sentence rolls up + fades out while the incoming one
 * rolls up into place + fades in — a quiet vertical crossfade that reads as discrete
 * thoughts instead of a stream. Honors prefers-reduced-motion (instant swap).
 *
 * It is intentionally quiet (Muted, single line, clamped height) so it sits under a
 * timeline group header as an aside, matching the surrounding restraint.
 */
import { useEffect, useRef, useState } from 'react';
import { MUTED } from './execTokens';

interface NarrationTickerProps {
    /** the current COMPLETE narration sentence; '' / unchanged updates are held */
    text: string;
}

// Slightly longer than the CSS animation (0.42s) so the leaving line is removed
// only after it has finished fading out.
const EXIT_MS = 460;

export function NarrationTicker({ text }: NarrationTickerProps) {
    // `current` is the line in place; `leaving` is the previous line animating out.
    const [current, setCurrent] = useState(text);
    const [leaving, setLeaving] = useState('');
    // Monotonic key so two identical consecutive sentences still re-trigger the
    // entrance animation (key change forces a remount → CSS animation replays).
    const [cycle, setCycle] = useState(0);
    const exitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        // Hold the last complete sentence: ignore empty (a new thinking passage
        // that hasn't finished its first sentence) and no-op updates so the ticker
        // never blanks out mid-run.
        if (!text || text === current) return;
        setCurrent((prevCurrent) => {
            setLeaving(prevCurrent);
            return text;
        });
        setCycle((c) => c + 1);
        if (exitTimer.current) clearTimeout(exitTimer.current);
        exitTimer.current = setTimeout(() => setLeaving(''), EXIT_MS);
        return () => {
            if (exitTimer.current) clearTimeout(exitTimer.current);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- advance only on a new `text`
    }, [text]);

    if (!current && !leaving) return null;

    return (
        // Fixed one-line height + overflow-hidden so the rolling text is clipped to
        // the line box and the row never reflows as sentences swap.
        <div className="relative mt-0.5 h-5 overflow-hidden">
            {leaving && (
                <span
                    key={`out-${cycle}`}
                    className="absolute inset-x-0 top-0 block animate-narration-out truncate text-xs leading-5 motion-reduce:animate-none"
                    style={{ color: MUTED }}
                >
                    {leaving}
                </span>
            )}
            {current && (
                <span
                    key={`in-${cycle}`}
                    className="block animate-narration-in truncate text-xs leading-5 motion-reduce:animate-none"
                    style={{ color: MUTED }}
                >
                    {current}
                </span>
            )}
        </div>
    );
}
