import { useCallback, useEffect, useRef } from 'react';
import { getLinsightSessionVersionList } from '~/api/linsight';
import type { ChatMessage } from '~/api/chatApi';
import type { useLinsightManager } from './useLinsightManager';

/** Poll cadence for the post-handoff attachment fetch (see the handoff handler).
 *
 * Two-speed on purpose. A small batch lands in seconds and deserves a snappy
 * first paint; a big one is the reason this poll exists at all — 12 bid PDFs
 * measured 19 minutes of ETL — and a fixed fast cadence would have to run for
 * hundreds of round-trips to cover it. So: fast while the common case plays out,
 * then back off and simply outlast the slow case.
 *
 * The deadline is a real bound, not a guess at the worst case: the per-file ETL
 * ceiling is 600s (settings.etl4lm.timeout) and the batch size is capped by the
 * folder-upload limits, so a pathological batch CAN outlive 30 minutes. Past the
 * deadline the drawer degrades to "visible after a refresh", which is where it
 * was before this poll existed — never to a timer that runs for the session's
 * lifetime. */
const INGEST_POLL_FAST_MS = 3000;
const INGEST_POLL_SLOW_MS = 15000;
/** Round-trips kept at the fast cadence before backing off (~1 minute). */
const INGEST_POLL_FAST_ATTEMPTS = 20;
const INGEST_POLL_DEADLINE_MS = 30 * 60 * 1000;
/** Backend SessionVersionStatusEnum values after which nothing will be ingested. */
const TERMINAL_SV_STATUSES = new Set([
    "completed",
    "failed",
    "terminated",
    "sop_generation_failed",
]);

export function useChatAttachmentPoll(updateLinsight: ReturnType<typeof useLinsightManager>['updateLinsight']) {
    const ingestPollsRef = useRef<
        Map<string, { timer: ReturnType<typeof setTimeout> | null; generation: number }>
    >(new Map());
    const ingestPollFor = useCallback((cid: string) => {
        let entry = ingestPollsRef.current.get(cid);
        if (!entry) {
            entry = { timer: null, generation: 0 };
            ingestPollsRef.current.set(cid, entry);
        }
        return entry;
    }, []);
    const cancelIngestPoll = useCallback(
        (cid: string) => {
            const entry = ingestPollFor(cid);
            if (entry.timer) {
                clearTimeout(entry.timer);
                entry.timer = null;
            }
            // Fences a request already in flight: clearing the timeout alone
            // would still let its `.then` re-arm a new one.
            entry.generation += 1;
        },
        [ingestPollFor],
    );
    // Only a real unmount stops every poll. Switching conversations does not.
    useEffect(
        () => () => {
            for (const entry of ingestPollsRef.current.values()) {
                if (entry.timer) clearTimeout(entry.timer);
                entry.generation += 1;
            }
            ingestPollsRef.current.clear();
        },
        [],
    );

    const pollFiles = (chat_id: string, svid: string, conversationId: string, realUserMessageId: string,
        setMessages: (updater: ChatMessage[] | ((previous: ChatMessage[]) => ChatMessage[])) => void) => {
                    if (chat_id) {
                        // Keyed by the turn's conversation, so it survives the
                        // user switching away and writes back where it started.
                        const pollCid = conversationId;
                        cancelIngestPoll(pollCid);
                        const pollEntry = ingestPollFor(pollCid);
                        const pollGeneration = pollEntry.generation;
                        const pollDeadline = Date.now() + INGEST_POLL_DEADLINE_MS;
                        let attempts = 0;
                        const scheduleNextIngestPoll = () => {
                            if (pollEntry.generation !== pollGeneration) return;
                            if (Date.now() >= pollDeadline) return;
                            const delay =
                                attempts < INGEST_POLL_FAST_ATTEMPTS
                                    ? INGEST_POLL_FAST_MS
                                    : INGEST_POLL_SLOW_MS;
                            pollEntry.timer = setTimeout(pollIngestedFiles, delay);
                        };
                        const pollIngestedFiles = () => {
                            attempts += 1;
                            getLinsightSessionVersionList(chat_id, '')
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                                .then((versions: any[]) => {
                                    if (pollEntry.generation !== pollGeneration) return;
                                    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                                    const item = (versions || []).find((v: any) => v.id === svid);
                                    if (item?.files?.length) {
                                        updateLinsight(svid, {
                                            // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                                            files: item.files.map((f: any) => ({
                                                ...f,
                                                file_name: decodeURIComponent(f.original_filename),
                                            })),
                                        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                                        } as any);

                                        // Stamp the user question's attachment chips with each
                                        // file's parse result so a failed attachment shows its
                                        // failed state live (not only after a refresh).
                                        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                                        const statusById = new Map<string, any>(
                                            item.files
                                                // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                                                .filter((f: any) => f?.file_id != null)
                                                // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                                                .map((f: any) => [String(f.file_id), f]),
                                        );
                                        setMessages((prev) =>
                                            prev.map((m) =>
                                                m.messageId === realUserMessageId && m.files?.length
                                                    ? {
                                                          ...m,
                                                          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
                                                          files: m.files.map((mf: any) => {
                                                              const p = statusById.get(String(mf.file_id));
                                                              return p
                                                                  ? {
                                                                        ...mf,
                                                                        valid: p.valid,
                                                                        parsing_status: p.parsing_status,
                                                                        error_message: p.error_message,
                                                                        ...(p.cover_filepath
                                                                            ? { cover_filepath: p.cover_filepath }
                                                                            : {}),
                                                                    }
                                                                  : mf;
                                                          }),
                                                      }
                                                    : m,
                                            ),
                                        );
                                        return;
                                    }
                                    // A terminated / failed / completed run will never
                                    // ingest anything more; keeping the timer alive would
                                    // just poll a settled row for two minutes.
                                    if (item && TERMINAL_SV_STATUSES.has(item.status)) return;
                                    scheduleNextIngestPoll();
                                })
                                .catch(() => {
                                    // best-effort: drawer still works after refresh
                                    scheduleNextIngestPoll();
                                });
                        };
                        pollIngestedFiles();
                    }

    };
    return { cancelIngestPoll, pollFiles };
}
