import { useEffect, useRef } from 'react';
import { checkSopQueueStatus } from '~/api/linsight';
import { useLinsightManager } from './useLinsightManager';

/** Poll interval while a task is queued (ms). Coarse enough to be cheap,
 *  fine enough that a freshly-picked-up task clears the badge promptly. */
const POLL_INTERVAL = 5000;

/**
 * Poll ``/workbench/queue-status`` while a task sits in the Linsight worker
 * queue and keep ``queueCount`` (the 1-based position among queued NEW tasks)
 * in sync on the store, so <QueueCard> can render "排队中(第 N 位)".
 *
 * Replaces the old inline ``useQueueStatus`` in Sop/index.tsx, fixing its three
 * defects so BOTH the standalone /linsight viewer (ExecutionFlow) and the F035
 * daily-conversation task turn (TaskTurnPanel) share one robust implementation:
 *   1. it re-arms whenever ``enabled`` flips true (e.g. right after
 *      start-execute sets status=Running), not only on a versionId change;
 *   2. it stops only when the worker actually picks the task up (index === 0)
 *      or the run leaves the queued state (``enabled`` → false) — a transient
 *      first 0 no longer kills polling permanently;
 *   3. it polls every 5s instead of 60s.
 *
 * The queue badge is non-critical UI: a failed poll is retried on the next tick
 * rather than surfaced, so a flaky queue-status call can never wedge the view.
 *
 * @param versionId linsight session_version id of the turn being executed
 * @param enabled   poll only while the turn may be queued (status===Running and
 *                  no execution output yet); the caller computes this.
 */
export function useLinsightQueuePolling(versionId: string, enabled: boolean) {
    const { updateLinsight } = useLinsightManager();
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        if (!enabled || !versionId || versionId === 'new') return;

        let cancelled = false;

        const poll = async () => {
            try {
                // request wrapper returns an untyped envelope; index is the
                // 1-based position among queued new tasks (0 = picked up).
                const res: any = await checkSopQueueStatus(versionId);
                const count = res?.data?.index ?? 0;
                if (cancelled) return;
                updateLinsight(versionId, { queueCount: count } as any);
                // index>0 → still queued, keep polling; index===0 → the worker
                // has picked us up (item removed from the Redis list), stop.
                if (count > 0) {
                    timerRef.current = setTimeout(poll, POLL_INTERVAL);
                }
            } catch {
                // Best-effort: the badge is non-critical. Retry next tick so a
                // transient error doesn't drop us out of polling for good.
                if (!cancelled) timerRef.current = setTimeout(poll, POLL_INTERVAL);
            }
        };

        poll();

        return () => {
            cancelled = true;
            if (timerRef.current) clearTimeout(timerRef.current);
        };
    }, [versionId, enabled, updateLinsight]);
}
