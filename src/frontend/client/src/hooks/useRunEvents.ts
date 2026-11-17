/**
 * F004 (T047) — subscription to the run events of one conversation.
 *
 * `GET /api/v1/workstation/conversations/{id}/events` is an SSE stream of
 * `id: <entry id>\ndata: <event JSON>` frames. Every event goes to
 * `runStore.applyEvent`; the store is the only place run progress lives.
 *
 * The server ends the stream when the conversation has no run in progress.
 * This module therefore reads a closed connection like this:
 *   - the store says no run is active        → idle, stay disconnected;
 *   - the connection failed (network)        → reconnect with `Last-Event-ID`;
 *   - it closed cleanly but the store still says "running" → the terminal
 *     event was missed (for example the reader stopped after a `resync` of a
 *     run that had already ended). Reconnect once; when the next connection
 *     also delivers nothing, the run is settled locally as finished.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { SSE } from 'sse.js';
import { getRunEventsUrl } from '~/api/runApi';
import { prepareBrowserHeaders } from '~/api/request';
import { selectIsRunning, useRunStore, type RunEvent } from '~/store/runStore';

// ---------------------------------------------------------------------------
// Pure parts
// ---------------------------------------------------------------------------

/** Parse the `data:` payload of one frame. Returns null for anything that is not a run event. */
export function parseRunEventFrame(data: unknown, entryId?: string | null): RunEvent | null {
    if (typeof data !== 'string' || !data.trim()) return null;
    let parsed: unknown;
    try {
        parsed = JSON.parse(data);
    } catch {
        return null;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    const raw = parsed as Record<string, unknown>;
    if (typeof raw.type !== 'string' || !raw.type) return null;
    const id = entryId || (typeof raw.id === 'string' ? raw.id : null);
    return {
        ...raw,
        data: raw.data && typeof raw.data === 'object' ? raw.data : {},
        ...(id ? { id } : {}),
    } as RunEvent;
}

/** Headers of a (re)connect: the cursor goes out as `Last-Event-ID`. */
export function runEventRequestHeaders(cursor: string | null | undefined): Record<string, string> {
    return cursor ? { 'Last-Event-ID': cursor } : {};
}

export const RECONNECT_BASE_MS = 1000;
export const RECONNECT_MAX_MS = 15000;

/** Delay before the n-th reconnect after a failed connection (1-based). */
export function reconnectDelay(attempt: number): number {
    const n = Math.max(1, Math.floor(attempt));
    return Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** (n - 1));
}

/** Clean closes without any event, while a run looks active, before it is settled. */
export const EMPTY_CLOSES_BEFORE_SETTLE = 2;
const EMPTY_CLOSE_RETRY_MS = 300;

export interface RunEventFrame {
    data: unknown;
    id?: string | null;
}

export interface RunEventSource {
    close: () => void;
}

export interface RunEventSourceHandlers {
    onFrame: (frame: RunEventFrame) => void;
    /** `failed` is true for a network/HTTP failure, false when the server ended the stream. */
    onClose: (failed: boolean) => void;
}

export interface RunEventFollowerDeps {
    /** Last entry id the store applied; sent as `Last-Event-ID`. */
    getCursor: () => string | null;
    applyEvent: (event: RunEvent, entryId?: string | null) => void;
    /** Whether the store still shows a run in progress (running or waiting). */
    isActive: () => boolean;
    /** Called when the stream says "idle" while the store still says "running". */
    settle: () => void;
    open: (cursor: string | null, handlers: RunEventSourceHandlers) => RunEventSource;
    /** Called once when the follower stops because the conversation is idle. */
    onIdle?: () => void;
    schedule?: (fn: () => void, ms: number) => unknown;
    cancel?: (handle: unknown) => void;
}

export interface RunEventFollower {
    close: () => void;
    /** True once the follower stopped (idle or closed by the caller). */
    isStopped: () => boolean;
}

/**
 * Follow the events of one conversation until it is idle. Not a hook: the
 * reconnect logic is plain code so it can be tested without React or a network.
 */
export function followRunEvents(deps: RunEventFollowerDeps): RunEventFollower {
    const schedule = deps.schedule ?? ((fn: () => void, ms: number) => setTimeout(fn, ms));
    const cancel = deps.cancel ?? ((handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>));
    let stopped = false;
    let source: RunEventSource | null = null;
    let timer: unknown = null;
    let failures = 0;
    let emptyCloses = 0;

    const stopIdle = () => {
        stopped = true;
        source = null;
        deps.onIdle?.();
    };

    const connect = () => {
        if (stopped) return;
        timer = null;
        let gotEvent = false;
        let closed = false;
        source = deps.open(deps.getCursor(), {
            onFrame: (frame) => {
                if (stopped || closed) return;
                const event = parseRunEventFrame(frame.data, frame.id);
                if (!event) return;
                failures = 0;
                // A resync alone does not prove the run is alive: the reader
                // also sends one for a run that has already ended.
                if (event.type !== 'resync') gotEvent = true;
                deps.applyEvent(event, event.id ?? null);
            },
            onClose: (failed) => {
                if (stopped || closed) return;
                closed = true;
                source = null;
                if (!deps.isActive()) {
                    stopIdle();
                    return;
                }
                if (failed) {
                    failures += 1;
                    timer = schedule(connect, reconnectDelay(failures));
                    return;
                }
                emptyCloses = gotEvent ? 0 : emptyCloses + 1;
                if (emptyCloses >= EMPTY_CLOSES_BEFORE_SETTLE) {
                    deps.settle();
                    stopIdle();
                    return;
                }
                timer = schedule(connect, emptyCloses ? EMPTY_CLOSE_RETRY_MS : 0);
            },
        });
    };

    connect();

    return {
        close: () => {
            if (stopped) return;
            stopped = true;
            if (timer !== null) cancel(timer);
            timer = null;
            const current = source;
            source = null;
            current?.close();
        },
        isStopped: () => stopped,
    };
}

// ---------------------------------------------------------------------------
// sse.js transport
// ---------------------------------------------------------------------------

/** Open one SSE connection with the same auth/scope headers as the chat stream. */
export function openRunEventSource(
    conversationId: string,
    cursor: string | null,
    handlers: RunEventSourceHandlers,
): RunEventSource {
    const url = getRunEventsUrl(conversationId);
    const sse = new SSE(url, { start: false, method: 'GET', headers: runEventRequestHeaders(cursor) });
    let done = false;
    let failed = false;
    const finish = () => {
        if (done) return;
        done = true;
        handlers.onClose(failed);
    };
    sse.addEventListener('message', (e: MessageEvent & { id?: string | null }) => {
        if (done) return;
        handlers.onFrame({ data: e.data, id: e.id ?? null });
    });
    sse.addEventListener('error', () => {
        failed = true;
    });
    sse.addEventListener('readystatechange', (e: Event & { readyState?: number }) => {
        // sse.js: 0 = connecting, 1 = open, 2 = closed.
        if (e?.readyState === 2) queueMicrotask(finish);
    });
    void prepareBrowserHeaders('GET', url, sse.headers)
        .then((headers) => {
            if (done) return;
            sse.headers = { ...sse.headers, ...headers };
            sse.stream();
        })
        .catch(() => {
            failed = true;
            finish();
        });
    return {
        close: () => {
            done = true;
            sse.close();
        },
    };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseRunEventsResult {
    /** Subscribe again now (after a send whose run the store does not know yet). */
    follow: () => void;
}

/**
 * Keep `runStore` in step with the run of `conversationId`.
 *
 * Subscribes when the conversation is opened (the server answers at once when
 * nothing is running), stops when the conversation is idle and subscribes
 * again when the store shows a new run or `follow()` is called. With
 * `enabled === false` nothing is requested.
 */
export function useRunEvents(conversationId: string | null | undefined, enabled: boolean): UseRunEventsResult {
    const cid = enabled && conversationId && conversationId !== 'new' ? conversationId : '';
    const [wake, setWake] = useState(0);
    const followerRef = useRef<RunEventFollower | null>(null);
    const isRunning = useRunStore(selectIsRunning(cid));

    useEffect(() => {
        if (!cid) return undefined;
        const store = () => useRunStore.getState();
        const follower = followRunEvents({
            getCursor: () => store().conversations[cid]?.lastEventId ?? null,
            applyEvent: (event, entryId) => store().applyEvent(cid, event, entryId),
            isActive: () => selectIsRunning(cid)(store()),
            settle: () => {
                const run = store().conversations[cid]?.run;
                if (!run) return;
                // No entry id: the event is local and must not move the cursor.
                store().applyEvent(cid, { type: 'run_finished', data: {}, run_id: run.runId });
            },
            open: (cursor, handlers) => openRunEventSource(cid, cursor, handlers),
        });
        followerRef.current = follower;
        return () => {
            follower.close();
            if (followerRef.current === follower) followerRef.current = null;
        };
    }, [cid, wake]);

    // A run appeared (send answered "started") while the subscription was idle.
    useEffect(() => {
        if (cid && isRunning && followerRef.current?.isStopped()) setWake((n) => n + 1);
    }, [cid, isRunning]);

    const follow = useCallback(() => {
        if (!followerRef.current || followerRef.current.isStopped()) setWake((n) => n + 1);
    }, []);

    return { follow };
}
