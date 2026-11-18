/**
 * F004 design §7 items 1 and 6: unread messages a run gives back, and the
 * "queued" mark of a relay run's messages.
 */
import { emptyConversationRunState, reduceRunEvent, useRunStore, type RunEvent } from './runStore';
import {
    joinReturnedText,
    mergeReturnedText,
    reduceResolveReturned,
    reduceUnreadMessages,
    unreadMessagesOf,
} from './runUnread';

const unread = (id: string, text: string) => ({ message_id: id, text, files: [] });

let entry = 0;
const emit = (event: Record<string, unknown>, cid = 'c1') =>
    useRunStore.getState().applyEvent(cid, { run_id: 'r1', data: {}, ...event } as RunEvent, `9-${++entry}`);
const conv = (cid = 'c1') => useRunStore.getState().conversations[cid];

beforeEach(() => {
    entry = 0;
    useRunStore.setState({ conversations: {} });
});

describe('unreadMessagesOf', () => {
    it('reads the list of an event or a stop response and skips malformed entries', () => {
        expect(unreadMessagesOf({ unread_messages: [unread('m1', 'a'), { text: 'no id' }, null, { message_id: 7 }] })).toEqual([
            { message_id: 'm1', text: 'a', files: [] },
            { message_id: '7', text: '' },
        ]);
        expect(unreadMessagesOf({})).toEqual([]);
        expect(unreadMessagesOf(null)).toEqual([]);
        expect(unreadMessagesOf({ unread_messages: 'x' })).toEqual([]);
    });
});

describe('returned text', () => {
    it('joins the messages in send order with a blank line', () => {
        expect(joinReturnedText([unread('m1', 'first'), unread('m2', '  '), unread('m3', 'third')])).toBe('first\n\nthird');
    });

    it('goes before what the input box already holds', () => {
        expect(mergeReturnedText('first\n\nsecond', '')).toBe('first\n\nsecond');
        expect(mergeReturnedText('first', 'typed since')).toBe('first\n\ntyped since');
        expect(mergeReturnedText('first', '   ')).toBe('first');
        expect(mergeReturnedText('', 'typed since')).toBe('typed since');
    });
});

describe('run_stopped with unread messages', () => {
    it('ends the run as stopped, clears the queued marks and keeps the messages for the page', () => {
        emit({ type: 'run_started' });
        emit({ type: 'steer_accepted', data: { message_id: 'm1' } });
        emit({ type: 'steer_accepted', data: { message_id: 'm2' } });
        emit({
            type: 'run_stopped',
            data: { reason: 'user', status: 'stopped', unread_messages: [unread('m1', 'one'), unread('m2', 'two')] },
        });
        expect(conv().run?.status).toBe('stopped');
        expect(conv().run?.error).toBeNull();
        expect(conv().queuedMessages).toEqual({});
        expect(conv().returnedMessages.map((m) => m.message_id)).toEqual(['m1', 'm2']);
    });

    it('takes a message once when the stop response and the event both deliver it', () => {
        emit({ type: 'run_started' });
        emit({ type: 'steer_accepted', data: { message_id: 'm1' } });
        useRunStore.getState().applyUnreadMessages('c1', [unread('m1', 'one')]);
        useRunStore.getState().resolveReturnedMessages('c1', new Set(['m1']));
        expect(conv().draftReturn).toBe('one');
        emit({ type: 'run_stopped', data: { unread_messages: [unread('m1', 'one'), unread('m2', 'two')] } });
        expect(conv().returnedMessages.map((m) => m.message_id)).toEqual(['m2']);
    });

    it('leaves the state alone when nothing was unread', () => {
        emit({ type: 'run_started' });
        emit({ type: 'run_stopped', data: { reason: 'user', status: 'stopped', unread_messages: [] } });
        expect(conv().returnedMessages).toEqual([]);
        expect(conv().draftReturn).toBeNull();
    });

    it('takes the messages even when the terminal event names a run that was replaced', () => {
        const start = reduceRunEvent(emptyConversationRunState(), { type: 'run_started', run_id: 'r2', data: {} });
        const next = reduceRunEvent(start, { type: 'run_stopped', run_id: 'r1', data: { unread_messages: [unread('m1', 'one')] } });
        expect(next.run?.runId).toBe('r2');
        expect(next.run?.status).toBe('running');
        expect(next.returnedMessages).toHaveLength(1);
    });
});

describe('run_failed of a relay run that could not be created (item 1)', () => {
    it('fails the run and gives the messages back', () => {
        emit({ type: 'run_started' });
        emit({ type: 'steer_accepted', data: { message_id: 'm1' } });
        emit({ type: 'run_finished' });
        emit({ type: 'run_started', run_id: 'r2', data: { profile: 'planned', relay: true } });
        emit({
            type: 'run_failed',
            run_id: 'r2',
            data: { code: 11091, reason: 'task_aborted', detail: 'boom', reference_id: 'r2', unread_messages: [unread('m1', 'one')] },
        });
        expect(conv().run).toMatchObject({ runId: 'r2', status: 'failed' });
        expect(conv().run?.error?.code).toBe(11091);
        expect(conv().queuedMessages).toEqual({});
        expect(conv().returnedMessages).toEqual([unread('m1', 'one')]);
    });
});

describe('relay run reads the queued messages', () => {
    it('clears "queued" for each steer_read that follows a relay run_started', () => {
        emit({ type: 'run_started' });
        useRunStore.getState().applySendResult('c1', { run_id: 'r1', disposition: 'queued', message_id: 'm1' });
        emit({ type: 'steer_accepted', data: { message_id: 'm2' } });
        emit({ type: 'run_finished' });
        expect(Object.keys(conv().queuedMessages)).toEqual(['m1', 'm2']);
        emit({ type: 'run_started', run_id: 'r2', data: { profile: 'direct', relay: true } });
        expect(Object.keys(conv().queuedMessages)).toEqual(['m1', 'm2']);
        emit({ type: 'steer_read', run_id: 'r2', data: { message_id: 'm1' } });
        emit({ type: 'steer_read', run_id: 'r2', data: { message_id: 'm2' } });
        expect(conv().queuedMessages).toEqual({});
        expect(conv().run).toMatchObject({ runId: 'r2', status: 'running' });
        expect(conv().returnedMessages).toEqual([]);
    });
});

describe('resolving returned messages', () => {
    it('hands the text of the messages that had a row to the input box and drops the others', () => {
        const taken = reduceUnreadMessages(emptyConversationRunState(), [unread('m1', 'one'), unread('m2', 'two'), unread('m3', 'three')]);
        const resolved = reduceResolveReturned(taken, new Set(['m1', 'm3']));
        expect(resolved.draftReturn).toBe('one\n\nthree');
        expect(resolved.returnedMessages).toEqual([]);
        // Dropped ones are not taken again from a later delivery.
        expect(reduceUnreadMessages(resolved, [unread('m2', 'two')])).toBe(resolved);
    });

    it('keeps text the input box has not taken yet in front of a later batch', () => {
        let state = reduceResolveReturned(reduceUnreadMessages(emptyConversationRunState(), [unread('m1', 'one')]), new Set(['m1']));
        state = reduceResolveReturned(reduceUnreadMessages(state, [unread('m2', 'two')]), new Set(['m2']));
        expect(state.draftReturn).toBe('one\n\ntwo');
    });

    it('clears the handed text once the input box took it', () => {
        useRunStore.getState().applyUnreadMessages('c1', [unread('m1', 'one')]);
        useRunStore.getState().resolveReturnedMessages('c1', new Set(['m1']));
        useRunStore.getState().clearDraftReturn('c1');
        expect(conv().draftReturn).toBeNull();
        expect(conv().returnedIds).toEqual(['m1']);
    });
});
