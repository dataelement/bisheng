/**
 * F004 at the page level: a run that gives way to another run keeps its
 * answer on screen, and a resync clears the "queued" marks the stored rows
 * show as read.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { useState } from 'react';
import type { ChatMessage } from '~/api/chatApi';

jest.mock('./useRunEvents', () => ({ useRunEvents: () => ({ follow: jest.fn() }) }));
jest.mock('~/api/runApi', () => ({ sendRunMessage: jest.fn(), stopConversationRun: jest.fn() }));
const mockGetAgentMessages = jest.fn();
jest.mock('~/api/chatApi', () => ({ getAgentMessages: (...args: unknown[]) => mockGetAgentMessages(...args) }));
jest.mock('~/api/memory', () => ({
    getMemoryFlagsApi: () => Promise.resolve({}),
    mergeMemoryFlags: (messages: unknown) => messages,
}));
jest.mock('~/api/request', () => ({ __esModule: true, default: {}, translateApiErrorMessage: () => 'failed' }));
jest.mock('~/api/linsight', () => ({ getLinsightSessionVersionList: () => Promise.resolve([]) }));

import { selectIsMessageQueued, useRunStore, type RunEvent } from '~/store/runStore';
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

let entry = 0;
const emit = (...events: Array<Record<string, unknown>>) =>
    act(() => {
        for (const event of events) {
            useRunStore.getState().applyEvent('c1', { run_id: 'r1', data: {}, ...event } as RunEvent, `7-${++entry}`);
        }
    });

function renderPage(initial: ChatMessage[]) {
    return renderHook(() => {
        const [messages, setMessages] = useState(initial);
        const unified = useUnifiedRun({
            enabled: true,
            conversationId: 'c1',
            bucketId: 'c1',
            messages,
            isLoading: false,
            setMessagesFor: (_bucket, updater) =>
                setMessages((prev) => (typeof updater === 'function' ? updater(prev) : updater)),
            sender: 'AI',
        });
        return { unified, stored: messages };
    });
}

beforeEach(() => {
    entry = 0;
    // The history is not answered unless a test says so.
    mockGetAgentMessages.mockReset().mockReturnValue(new Promise(() => undefined));
    act(() => useRunStore.setState({ conversations: {} }));
});

describe('a run gives way to another run', () => {
    const live = [row('q', true), row('run:r1', false, { liveRunId: 'r1', text: '' }), row('m2', true, { text: 'more' })];

    it('keeps the answer of a direct run when its end and the relay run arrive together', () => {
        const { result } = renderPage(live);
        emit({ type: 'run_started' }, { type: 'text', data: { text: 'the answer' } });
        expect(result.current.unified.messages[1].text).toBe('the answer');
        // One batch: the page never renders "r1 ended".
        emit({ type: 'run_finished' }, { type: 'run_started', run_id: 'r2', data: { relay: true } });
        const rows = result.current.unified.messages;
        expect(rows.map((m) => m.messageId)).toEqual(['q', 'run:r1', 'm2', 'run:r2']);
        expect(rows[1]).toMatchObject({ text: 'the answer' });
        expect(rows[1].liveRunId).toBeUndefined();
        expect(rows[3].liveRunId).toBe('r2');
        expect(useRunStore.getState().conversations.c1.replacedRuns).toEqual([]);
    });

    it('keeps the answer when a send starts a new run before the old one was seen to end', () => {
        const { result } = renderPage(live.slice(0, 2));
        emit(
            { type: 'run_started' },
            { type: 'text', data: { text: 'the answer' } },
            { type: 'tool_call', data: { call_id: 'k1', name: 'search', status: 'start' } },
        );
        act(() => useRunStore.getState().applySendResult('c1', { run_id: 'r2', disposition: 'started', message_id: 'm9' }));
        const old = result.current.unified.messages[1];
        expect(old.liveRunId).toBeUndefined();
        expect(old.text).toBe('the answer');
        expect(old.events).toMatchObject([{ tool_call_id: 'k1', inflight: false }]);
        // Late events of the old run change nothing.
        emit({ type: 'text', data: { text: ' late' } });
        expect(result.current.unified.messages[1].text).toBe('the answer');
    });

    it('lets the history of the new run replace the list once that run ends', async () => {
        const { result } = renderPage(live);
        emit({ type: 'run_started' }, { type: 'text', data: { text: 'the answer' } });
        emit({ type: 'run_finished' }, { type: 'run_started', run_id: 'r2', data: { relay: true } });
        mockGetAgentMessages.mockResolvedValue([row('q', true), row('a1', false), row('m2', true), row('a2', false)]);
        emit({ type: 'run_finished', run_id: 'r2' });
        await waitFor(() => expect(result.current.stored.map((m) => m.messageId)).toEqual(['q', 'a1', 'm2', 'a2']));
    });
});

describe('queued marks after a resync', () => {
    it('clears the marks of the messages the stored rows show as read', async () => {
        renderPage([
            row('q', true),
            row('run:r1', false, { liveRunId: 'r1', text: '' }),
            row('m1', true),
            row('m2', true),
        ]);
        emit(
            { type: 'run_started' },
            { type: 'steer_accepted', data: { message_id: 'm1' } },
            { type: 'steer_accepted', data: { message_id: 'm2' } },
        );
        expect(mockGetAgentMessages).not.toHaveBeenCalled();
        // The `steer_read` of m1 was among the events the resync stands for.
        mockGetAgentMessages.mockResolvedValue([
            row('q', true),
            row('801', true, { steerMessageId: 'm1', steerQueued: false }),
            row('802', true, { steerMessageId: 'm2', steerQueued: true }),
        ]);
        emit({ type: 'resync', data: { text: 'so far', thinking: '', plan: [], files: [] } });
        await waitFor(() => expect(selectIsMessageQueued('c1', 'm1')(useRunStore.getState())).toBe(false));
        expect(selectIsMessageQueued('c1', 'm2')(useRunStore.getState())).toBe(true);
        expect(mockGetAgentMessages).toHaveBeenCalledTimes(1);
    });

    it('asks nothing when no message is marked', () => {
        renderPage([row('q', true), row('run:r1', false, { liveRunId: 'r1', text: '' })]);
        emit({ type: 'run_started' }, { type: 'resync', data: { text: 'so far', thinking: '', plan: [], files: [] } });
        expect(mockGetAgentMessages).not.toHaveBeenCalled();
    });
});
