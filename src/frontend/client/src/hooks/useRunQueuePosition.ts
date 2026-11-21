/**
 * F004 (AC-36): place of a conversation's deep-research run in the worker queue.
 *
 * Polls `GET /conversations/{id}/queue-position` while `enabled` (the caller
 * passes true while the run is in progress and has produced nothing yet). The
 * position moves as the runs ahead of it end, so it is asked again every
 * `POLL_INTERVAL_MS`. A failed request keeps the last known value and is
 * retried on the next tick: the queue card is not critical.
 */
import { useEffect, useState } from 'react';
import { getRunQueuePosition } from '~/api/runApi';

export const POLL_INTERVAL_MS = 5000;

export function useRunQueuePosition(conversationId: string | undefined, enabled: boolean): number | null {
    const [position, setPosition] = useState<number | null>(null);

    useEffect(() => {
        if (!enabled || !conversationId || conversationId === 'new') {
            setPosition(null);
            return undefined;
        }
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const poll = async () => {
            try {
                const next = await getRunQueuePosition(conversationId);
                if (!cancelled) setPosition(next);
            } catch {
                // Non-critical: keep the last value and ask again on the next tick.
            }
            if (!cancelled) timer = setTimeout(poll, POLL_INTERVAL_MS);
        };
        void poll();
        return () => {
            cancelled = true;
            if (timer) clearTimeout(timer);
        };
    }, [conversationId, enabled]);

    return enabled ? position : null;
}
