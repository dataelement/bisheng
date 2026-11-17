import {
    EMPTY_CLOSES_BEFORE_SETTLE,
    followRunEvents,
    parseRunEventFrame,
    reconnectDelay,
    RECONNECT_MAX_MS,
    runEventRequestHeaders,
    type RunEventSourceHandlers,
} from './useRunEvents';
import { emptyConversationRunState, reduceRunEvent, type ConversationRunState, type RunEvent } from '~/store/runStore';

jest.mock('sse.js', () => ({ SSE: jest.fn() }));
jest.mock('~/api/request', () => ({ __esModule: true, default: {}, prepareBrowserHeaders: jest.fn() }));

const frame = (event: Record<string, unknown>) => JSON.stringify(event);

describe('parseRunEventFrame', () => {
    it('reads a frame and takes the entry id from the SSE id line', () => {
        const event = parseRunEventFrame(frame({ type: 'text', data: { text: 'hi' }, run_id: 'r1', ts: 1 }), '5-1');
        expect(event).toEqual({ type: 'text', data: { text: 'hi' }, run_id: 'r1', ts: 1, id: '5-1' });
    });

    it('falls back to the id inside the event and defaults data to an object', () => {
        expect(parseRunEventFrame(frame({ type: 'run_started', id: '7-0', run_id: 'r1' }))).toEqual({
            type: 'run_started',
            id: '7-0',
            run_id: 'r1',
            data: {},
        });
    });

    it('ignores anything that is not a run event', () => {
        expect(parseRunEventFrame('')).toBeNull();
        expect(parseRunEventFrame('not json')).toBeNull();
        expect(parseRunEventFrame('[1,2]')).toBeNull();
        expect(parseRunEventFrame(frame({ data: { text: 'x' } }))).toBeNull();
        expect(parseRunEventFrame(undefined)).toBeNull();
    });
});

describe('reconnect cursor and delay', () => {
    it('sends the cursor as Last-Event-ID and nothing without one', () => {
        expect(runEventRequestHeaders('12-3')).toEqual({ 'Last-Event-ID': '12-3' });
        expect(runEventRequestHeaders(null)).toEqual({});
    });

    it('backs off and stays under the cap', () => {
        expect(reconnectDelay(1)).toBe(1000);
        expect(reconnectDelay(2)).toBe(2000);
        expect(reconnectDelay(3)).toBe(4000);
        expect(reconnectDelay(50)).toBe(RECONNECT_MAX_MS);
    });
});

/** A follower wired to the real reducer and a scripted transport. */
function harness() {
    let conv: ConversationRunState = emptyConversationRunState();
    const opened: Array<{ cursor: string | null; handlers: RunEventSourceHandlers; closed: boolean }> = [];
    const timers: Array<{ fn: () => void; ms: number }> = [];
    const settle = jest.fn(() => {
        if (conv.run) conv = reduceRunEvent(conv, { type: 'run_finished', data: {}, run_id: conv.run.runId });
    });
    const onIdle = jest.fn();
    const follower = followRunEvents({
        getCursor: () => conv.lastEventId,
        applyEvent: (event: RunEvent, entryId) => {
            conv = reduceRunEvent(conv, event, entryId);
        },
        isActive: () => conv.run?.status === 'running' || conv.run?.status === 'waiting',
        settle,
        onIdle,
        open: (cursor, handlers) => {
            const entry = { cursor, handlers, closed: false };
            opened.push(entry);
            return { close: () => { entry.closed = true; } };
        },
        schedule: (fn, ms) => timers.push({ fn, ms }),
        cancel: () => undefined,
    });
    const send = (index: number, event: Record<string, unknown>, id: string) =>
        opened[index].handlers.onFrame({ data: frame(event), id });
    const runTimer = () => timers.shift()!.fn();
    return { follower, opened, timers, settle, onIdle, send, runTimer, conv: () => conv };
}

describe('followRunEvents', () => {
    it('stops without reconnecting when the conversation is idle', () => {
        const h = harness();
        expect(h.opened).toHaveLength(1);
        expect(h.opened[0].cursor).toBeNull();
        h.opened[0].handlers.onClose(false);
        expect(h.follower.isStopped()).toBe(true);
        expect(h.onIdle).toHaveBeenCalledTimes(1);
        expect(h.timers).toHaveLength(0);
    });

    it('reconnects after a failure with the last entry id and applies no text twice', () => {
        const h = harness();
        h.send(0, { type: 'run_started', data: {}, run_id: 'r1' }, '10-0');
        h.send(0, { type: 'text', data: { text: 'Hel' }, run_id: 'r1' }, '10-1');
        h.opened[0].handlers.onClose(true);
        expect(h.timers[0].ms).toBe(1000);
        h.runTimer();
        expect(h.opened[1].cursor).toBe('10-1');
        // The server may replay the entry at the cursor; the store skips it.
        h.send(1, { type: 'text', data: { text: 'Hel' }, run_id: 'r1' }, '10-1');
        h.send(1, { type: 'text', data: { text: 'lo' }, run_id: 'r1' }, '10-2');
        h.send(1, { type: 'run_finished', data: {}, run_id: 'r1' }, '10-3');
        h.opened[1].handlers.onClose(false);
        expect(h.conv().run?.text).toBe('Hello');
        expect(h.conv().run?.status).toBe('finished');
        expect(h.follower.isStopped()).toBe(true);
        expect(h.settle).not.toHaveBeenCalled();
    });

    it('grows the delay while failures repeat and resets it after an event', () => {
        const h = harness();
        h.send(0, { type: 'run_started', data: {}, run_id: 'r1' }, '1-0');
        h.opened[0].handlers.onClose(true);
        h.runTimer();
        h.opened[1].handlers.onClose(true);
        expect(h.timers[0].ms).toBe(2000);
        h.runTimer();
        h.send(2, { type: 'text', data: { text: 'a' }, run_id: 'r1' }, '1-1');
        h.opened[2].handlers.onClose(true);
        expect(h.timers[0].ms).toBe(1000);
    });

    it('settles a run whose end was missed: resync of an ended run, then silence', () => {
        const h = harness();
        h.send(0, { type: 'resync', data: { text: 'done text', thinking: '', plan: [], files: [] }, run_id: 'r1' }, '20-9');
        expect(h.conv().run?.status).toBe('running');
        h.opened[0].handlers.onClose(false);
        expect(h.settle).not.toHaveBeenCalled();
        h.runTimer();
        expect(h.opened[1].cursor).toBe('20-9');
        h.opened[1].handlers.onClose(false);
        expect(EMPTY_CLOSES_BEFORE_SETTLE).toBe(2);
        expect(h.settle).toHaveBeenCalledTimes(1);
        expect(h.conv().run?.status).toBe('finished');
        expect(h.conv().run?.text).toBe('done text');
        expect(h.conv().lastEventId).toBe('20-9');
        expect(h.follower.isStopped()).toBe(true);
    });

    it('keeps following a run that waits for an answer', () => {
        const h = harness();
        h.send(0, { type: 'run_started', data: {}, run_id: 'r1' }, '3-0');
        h.send(0, { type: 'ask_user', data: { call_id: 'c', questions: [{ question: 'q' }] }, run_id: 'r1' }, '3-1');
        h.opened[0].handlers.onClose(true);
        expect(h.follower.isStopped()).toBe(false);
        expect(h.timers).toHaveLength(1);
    });

    it('does nothing after it was closed by the caller', () => {
        const h = harness();
        h.send(0, { type: 'run_started', data: {}, run_id: 'r1' }, '4-0');
        h.follower.close();
        expect(h.opened[0].closed).toBe(true);
        h.send(0, { type: 'text', data: { text: 'late' }, run_id: 'r1' }, '4-1');
        h.opened[0].handlers.onClose(true);
        expect(h.conv().run?.text).toBe('');
        expect(h.timers).toHaveLength(0);
    });
});
