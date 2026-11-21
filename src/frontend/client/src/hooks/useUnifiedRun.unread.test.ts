/**
 * F004 design §7 items 1, 3 and 6 at the page level: unread messages given
 * back on a stop or a failed relay leave the list and reach the input box
 * once; a blocked send shows the stored turn without following any run.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { useState } from 'react';
import type { ChatMessage } from '~/api/chatApi';

const mockFollow = jest.fn();
jest.mock('./useRunEvents', () => ({ useRunEvents: () => ({ follow: mockFollow }) }));
const mockSend = jest.fn();
const mockStop = jest.fn();
jest.mock('~/api/runApi', () => ({
    sendRunMessage: (...args: unknown[]) => mockSend(...args),
    stopConversationRun: (...args: unknown[]) => mockStop(...args),
}));
const mockGetAgentMessages = jest.fn();
jest.mock('~/api/chatApi', () => ({ getAgentMessages: (...args: unknown[]) => mockGetAgentMessages(...args) }));
jest.mock('~/api/memory', () => ({
    getMemoryFlagsApi: () => Promise.resolve({}),
    mergeMemoryFlags: (messages: unknown) => messages,
}));
jest.mock('~/api/request', () => ({ __esModule: true, default: {}, translateApiErrorMessage: () => 'failed' }));
jest.mock('~/api/linsight', () => ({ getLinsightSessionVersionList: () => Promise.resolve([]) }));
jest.mock('i18next', () => ({ __esModule: true, default: { t: (key: string) => key } }));

import { useRunStore, type RunEvent } from '~/store/runStore';
import { handedReturnedIds, rememberHandedReturnedIds } from '~/utils/returnedMessageLog';
import { useUnifiedRun } from './useUnifiedRun';

const row = (id: string, isCreatedByUser: boolean, extra: Partial<ChatMessage> = {}): ChatMessage => ({
    text: id,
    sender: isCreatedByUser ? 'User' : 'AI',
    isCreatedByUser,
    messageId: id,
    parentMessageId: '',
    conversationId: 'c1',
    error: false,
    ...extra,
});
const unread = (id: string, text: string) => ({ message_id: id, text, files: [] });

let entry = 0;
const emit = (...events: Array<Record<string, unknown>>) =>
    act(() => {
        for (const event of events) {
            useRunStore.getState().applyEvent('c1', { run_id: 'r1', data: {}, ...event } as RunEvent, `6-${++entry}`);
        }
    });
const conv = () => useRunStore.getState().conversations.c1;

function renderPage(initial: ChatMessage[], options: { enabled?: boolean; isLoading?: boolean } = {}) {
    return renderHook(
        (props: { isLoading: boolean }) => {
            const [messages, setMessages] = useState(initial);
            const unified = useUnifiedRun({
                enabled: options.enabled ?? true,
                conversationId: 'c1',
                bucketId: 'c1',
                messages,
                isLoading: props.isLoading,
                setMessagesFor: (_bucket, updater) =>
                    setMessages((prev) => (typeof updater === 'function' ? updater(prev) : updater)),
                sender: 'AI',
            });
            return { unified, stored: messages, setMessages };
        },
        { initialProps: { isLoading: options.isLoading ?? false } },
    );
}

beforeEach(() => {
    entry = 0;
    localStorage.clear();
    mockFollow.mockReset();
    mockSend.mockReset();
    mockStop.mockReset();
    // The stored turn of the stopped run; the queued question rows were deleted.
    mockGetAgentMessages.mockReset().mockResolvedValue([row('q', true), row('a-stored', false, { stopped: true })]);
    act(() => useRunStore.setState({ conversations: {} }));
});

// Let the history reload a test started settle inside act.
afterEach(async () => {
    await act(async () => {
        for (let i = 0; i < 5; i += 1) await Promise.resolve();
    });
});

describe('stop gives the unread messages back (item 6)', () => {
    const live = [row('q', true), row('run:r1', false, { liveRunId: 'r1', text: '' }), row('m1', true, { text: 'one' }), row('m2', true, { text: 'two' })];

    it('removes the queued rows and hands their text to the input box when run_stopped carries them', async () => {
        const { result } = renderPage(live);
        emit(
            { type: 'run_started' },
            { type: 'text', data: { text: 'so far' } },
            { type: 'steer_accepted', data: { message_id: 'm1' } },
            { type: 'steer_accepted', data: { message_id: 'm2' } },
        );
        emit({ type: 'run_stopped', data: { reason: 'user', status: 'stopped', unread_messages: [unread('m1', 'one'), unread('m2', 'two')] } });
        expect(conv().draftReturn).toBe('one\n\ntwo');
        expect(conv().queuedMessages).toEqual({});
        // The stored turn replaces the list; the returned messages are not appended again.
        await waitFor(() => expect(result.current.stored.map((m) => m.messageId)).toEqual(['q', 'a-stored']));
        expect(result.current.stored[1].stopped).toBe(true);
        // Let the memory-flag request of the reload settle inside act.
        await act(async () => {
            await Promise.resolve();
            await Promise.resolve();
        });
    });

    it('keeps the frozen answer as stopped, not failed, until the history arrives', () => {
        mockGetAgentMessages.mockReturnValue(new Promise(() => undefined));
        const { result } = renderPage(live);
        emit({ type: 'run_started' }, { type: 'text', data: { text: 'so far' } }, { type: 'steer_accepted', data: { message_id: 'm1' } });
        emit({ type: 'run_stopped', data: { unread_messages: [unread('m1', 'one')] } });
        expect(result.current.stored.map((m) => m.messageId)).toEqual(['q', 'run:r1', 'm2']);
        expect(result.current.stored[1]).toMatchObject({ text: 'so far', stopped: true, error: false });
    });

    it('takes them from the stop response and ignores the same ones in the event that follows', async () => {
        mockStop.mockResolvedValue({ run_id: 'r1', status: 'stopped', unread_messages: [unread('m1', 'one')] });
        const { result } = renderPage(live);
        emit({ type: 'run_started' }, { type: 'steer_accepted', data: { message_id: 'm1' } });
        await act(async () => {
            await result.current.unified.stopRun();
        });
        expect(mockStop).toHaveBeenCalledWith('c1', 'r1');
        expect(conv().draftReturn).toBe('one');
        expect(result.current.stored.some((m) => m.messageId === 'm1')).toBe(false);
        act(() => useRunStore.getState().clearDraftReturn('c1'));
        emit({ type: 'run_stopped', data: { unread_messages: [unread('m1', 'one')] } });
        expect(conv().draftReturn).toBeNull();
        expect(conv().returnedMessages).toEqual([]);
    });

    it('returns nothing for a "stopping" answer; the event delivers', async () => {
        mockStop.mockResolvedValue({ run_id: 'r1', status: 'stopping', unread_messages: [] });
        const { result } = renderPage(live);
        emit({ type: 'run_started' }, { type: 'steer_accepted', data: { message_id: 'm1' } });
        await act(async () => {
            await result.current.unified.stopRun();
        });
        expect(conv().draftReturn).toBeNull();
        expect(result.current.stored.some((m) => m.messageId === 'm1')).toBe(true);
    });

    it('works for a reopened conversation whose queued rows came from the history', () => {
        mockGetAgentMessages.mockReturnValue(new Promise(() => undefined));
        const reopened = [row('q', true), row('a', false), row('8801', true, { steerMessageId: 'm1', text: 'one' })];
        const { result, rerender } = renderPage(reopened, { isLoading: true });
        emit({ type: 'resync', data: { text: 'so far', thinking: '', plan: [], files: [] } });
        emit({ type: 'run_stopped', data: { unread_messages: [unread('m1', 'one')] } });
        // Nothing is decided while the history is still loading.
        expect(conv().returnedMessages).toHaveLength(1);
        rerender({ isLoading: false });
        expect(conv().draftReturn).toBe('one');
        expect(result.current.stored.map((m) => m.messageId)).toEqual(['q', 'a']);
    });

    it('does not refill the input box when a later visit replays the ended run', () => {
        // An earlier visit of this browser handed the text over.
        rememberHandedReturnedIds(['m1']);
        const { result } = renderPage([row('q', true), row('a', false, { stopped: true })]);
        emit(
            { type: 'run_started' },
            { type: 'steer_accepted', data: { message_id: 'm1' } },
            { type: 'run_stopped', data: { unread_messages: [unread('m1', 'one')] } },
        );
        expect(conv().draftReturn).toBeNull();
        expect(conv().returnedMessages).toEqual([]);
        expect(result.current.stored.map((m) => m.messageId)).toEqual(['q', 'a']);
    });
});

describe('relay run that could not be created (item 1)', () => {
    const failure = { code: 11091, reason: 'task_aborted', detail: 'boom', reference_id: 'r2' };

    it('returns the messages and shows the failure when start and failure arrive together', () => {
        const { result } = renderPage([row('q', true), row('a', false), row('m1', true, { text: 'one' })]);
        emit({ type: 'run_started' }, { type: 'steer_accepted', data: { message_id: 'm1' } }, { type: 'run_finished' });
        emit(
            { type: 'run_started', run_id: 'r2', data: { profile: 'planned', relay: true } },
            { type: 'run_failed', run_id: 'r2', data: { ...failure, unread_messages: [unread('m1', 'one')] } },
        );
        expect(conv().draftReturn).toBe('one');
        expect(result.current.stored.map((m) => m.messageId)).toEqual(['q', 'a', 'run:r2']);
        expect(result.current.stored[2]).toMatchObject({ error: true, errorCode: 11091, referenceId: 'r2', errorText: '' });
        // The history has no row for this run: it must not replace the failure.
        expect(mockGetAgentMessages).not.toHaveBeenCalled();
    });

    it('does the same when the relay run was seen running first', async () => {
        const { result } = renderPage([row('q', true), row('a', false), row('m1', true, { text: 'one' })]);
        emit({ type: 'run_started' }, { type: 'steer_accepted', data: { message_id: 'm1' } }, { type: 'run_finished' });
        emit({ type: 'run_started', run_id: 'r2', data: { profile: 'planned', relay: true } });
        await waitFor(() => expect(result.current.stored.some((m) => m.liveRunId === 'r2')).toBe(true));
        emit({ type: 'run_failed', run_id: 'r2', data: { ...failure, unread_messages: [unread('m1', 'one')] } });
        expect(conv().draftReturn).toBe('one');
        expect(result.current.stored.map((m) => m.messageId)).toEqual(['q', 'a', 'run:r2']);
        expect(result.current.stored[2]).toMatchObject({ error: true, errorCode: 11091 });
        expect(result.current.stored[2].liveRunId).toBeUndefined();
    });
});

describe('a missed terminal event: the resync gives the unread messages back (item 6)', () => {
    const live = [row('q', true), row('run:r1', false, { liveRunId: 'r1', text: '' }), row('m1', true, { text: 'one' })];
    const resync = (data: Record<string, unknown>) =>
        emit({ type: 'resync', data: { text: 'so far', thinking: '', plan: [], files: [], ended: true, ...data } });

    it('returns the text of a stopped run whose run_stopped event never arrived', async () => {
        // The stop answered `stopping` with an empty list.
        mockStop.mockResolvedValue({ run_id: 'r1', status: 'stopping', unread_messages: [] });
        const { result } = renderPage(live);
        emit({ type: 'run_started' }, { type: 'steer_accepted', data: { message_id: 'm1' } });
        await act(async () => {
            await result.current.unified.stopRun();
        });
        expect(conv().queuedMessages).toEqual({ m1: true });

        resync({ status: 'stopped', unread_messages: [unread('m1', 'one')] });

        expect(conv().draftReturn).toBe('one');
        expect(conv().queuedMessages).toEqual({});
        await waitFor(() => expect(result.current.stored.map((m) => m.messageId)).toEqual(['q', 'a-stored']));
    });

    it('takes a message once when the event and a later resync both carry it', () => {
        renderPage(live);
        emit({ type: 'run_started' }, { type: 'steer_accepted', data: { message_id: 'm1' } });
        emit({ type: 'run_stopped', data: { status: 'stopped', unread_messages: [unread('m1', 'one')] } });
        resync({ status: 'stopped', unread_messages: [unread('m1', 'one')] });
        expect(conv().draftReturn).toBe('one');
        expect(conv().returnedMessages).toEqual([]);
    });

    it('hands the text over even when the history reload already removed the rows', () => {
        // The stop was not handled before the page was reloaded: the history no
        // longer holds the deleted question rows, the stream replays the stop.
        renderPage([row('q', true), row('a-stored', false, { stopped: true })]);
        resync({ status: 'stopped', unread_messages: [unread('m1', 'one')] });
        expect(conv().draftReturn).toBe('one');
        expect(conv().returnedMessages).toEqual([]);
        expect(handedReturnedIds().has('m1')).toBe(true);
    });

    it('hands the text over when the stop response arrived while another conversation was open', () => {
        // The store took the messages; the history loaded on the way back has no rows for them.
        act(() => useRunStore.getState().applyUnreadMessages('c1', [unread('m1', 'one'), unread('m2', 'two')]));
        const { rerender } = renderPage([row('q', true), row('a-stored', false, { stopped: true })], { isLoading: true });
        expect(conv().draftReturn).toBeNull();
        rerender({ isLoading: false });
        expect(conv().draftReturn).toBe('one\n\ntwo');
    });

    it('drops returned messages this browser handed over in an earlier visit', () => {
        rememberHandedReturnedIds(['m1']);
        renderPage([row('q', true), row('a-stored', false, { stopped: true })]);
        resync({ status: 'stopped', unread_messages: [unread('m1', 'one')] });
        expect(conv().draftReturn).toBeNull();
        expect(conv().returnedMessages).toEqual([]);
    });

    it('shows the failure of a relay run that could not be created and keeps it on screen', async () => {
        const { result } = renderPage([row('q', true), row('a', false), row('m1', true, { text: 'one' })]);
        act(() => useRunStore.getState().applySendResult('c1', { run_id: 'r0', disposition: 'queued', message_id: 'm1' }));
        resync({ text: '', status: 'failed', unread_messages: [unread('m1', 'one')] });
        expect(conv().draftReturn).toBe('one');
        await waitFor(() => expect(result.current.stored.map((m) => m.messageId)).toEqual(['q', 'a', 'run:r1']));
        expect(result.current.stored[2]).toMatchObject({ error: true, errorText: 'failed' });
        expect(mockGetAgentMessages).not.toHaveBeenCalled();
    });
});

describe('blocked send (item 3)', () => {
    it('shows the question and the auto-reply with the stored ids and follows no run', async () => {
        mockSend.mockResolvedValue({
            status_code: 200,
            data: {
                run_id: null,
                disposition: 'blocked',
                message_id: null,
                conversation_id: 'c1',
                content_safety: true,
                auto_reply: 'not allowed',
                question_message_id: 901,
                answer_message_id: 902,
            },
        });
        const { result } = renderPage([row('u1', true, { text: 'bad words' }), row('u1_', false, { liveRunId: '', text: '' })]);
        const onConversation = jest.fn();
        const onRejected = jest.fn();
        let sent: Awaited<ReturnType<typeof result.current.unified.send>> | undefined;
        await act(async () => {
            sent = await result.current.unified.send({
                payload: { text: 'bad words' },
                conversationId: 'c1',
                userMessageId: 'u1',
                setMessages: result.current.setMessages,
                onConversation,
                onRejected,
            });
        });
        expect(sent).toEqual({ accepted: true, conversationId: 'c1', disposition: 'blocked', runId: null, answered: false });
        expect(onConversation).toHaveBeenCalledWith('c1');
        expect(onRejected).not.toHaveBeenCalled();
        expect(mockFollow).not.toHaveBeenCalled();
        expect(mockGetAgentMessages).not.toHaveBeenCalled();
        expect(result.current.stored.map((m) => m.messageId)).toEqual(['901', '902']);
        expect(result.current.stored[1]).toMatchObject({ text: 'not allowed', category: 'agent_answer', error: false });
        expect(result.current.stored[1].liveRunId).toBeUndefined();
        // The conversation stays idle: no run in the store.
        expect(conv()?.run ?? null).toBeNull();
        expect(result.current.unified.isRunning).toBe(false);
    });
});

describe('tenant switch off', () => {
    it('does not touch the list or the input box', () => {
        const rows = [row('q', true), row('m1', true)];
        const { result } = renderPage(rows, { enabled: false });
        act(() => useRunStore.getState().applyUnreadMessages('c1', [unread('m1', 'one')]));
        expect(result.current.stored).toBe(rows);
        expect(conv().draftReturn).toBeNull();
    });
});

describe('a run whose events the page stopped following', () => {
    it('freezes the answer row with the lost-connection copy', () => {
        // The history request fails too (for example after a logout).
        mockGetAgentMessages.mockReturnValue(new Promise(() => undefined));
        const live = [row('q', true), row('run:r1', false, { liveRunId: 'r1', text: '' })];
        const { result } = renderPage(live);
        emit({ type: 'run_started' }, { type: 'text', data: { text: 'so far' } });
        // What useRunEvents applies when it gives up (no entry id: a local event).
        act(() => {
            useRunStore.getState().applyEvent('c1', {
                type: 'run_failed',
                run_id: 'r1',
                data: { code: 0, reason: '', detail: '', connection_lost: true },
            } as RunEvent);
        });
        expect(result.current.unified.isRunning).toBe(false);
        expect(result.current.stored[1]).toMatchObject({ error: true, errorText: 'workstation.chat.connection_lost' });
    });
});
