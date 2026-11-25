/**
 * F004 (T061): a conversation opened while its deep-research run is going.
 * The stored task row shows the run from the run store; an earlier, ended
 * task row is left alone and the run gets a row of its own.
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
const mockVersionList = jest.fn();
jest.mock('~/api/linsight', () => ({
    getLinsightSessionVersionList: (...args: unknown[]) => mockVersionList(...args),
}));

import { useRunStore, type RunEvent } from '~/store/runStore';
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
const taskRow = row('t', false, { category: 'task', linsightSessionVersionId: 'sv1', text: '' });

let entry = 0;
const emit = (event: Record<string, unknown>) =>
    act(() => {
        useRunStore.getState().applyEvent('c1', { run_id: 'r1', data: {}, ...event } as RunEvent, `5-${++entry}`);
    });

function renderPage(initial: ChatMessage[], enabled = true) {
    return renderHook(() => {
        const [messages, setMessages] = useState(initial);
        const unified = useUnifiedRun({
            enabled,
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
    mockVersionList.mockReset();
    mockGetAgentMessages.mockReset().mockResolvedValue([]);
    act(() => useRunStore.setState({ conversations: {} }));
});

it('shows a run in progress in its stored task row', async () => {
    mockVersionList.mockResolvedValue([{ id: 'sv1', status: 'in_progress' }]);
    const { result } = renderPage([row('q', true), taskRow, row('steer', true)]);
    emit({ type: 'run_started' });
    emit({ type: 'text', data: { text: 'so far' } });
    await waitFor(() => expect(result.current.stored[1].liveRunId).toBe('r1'));
    expect(mockVersionList).toHaveBeenCalledWith('c1', '');
    expect(result.current.unified.messages.map((m) => m.messageId)).toEqual(['q', 't', 'steer']);
    expect(result.current.unified.messages[1]).toMatchObject({ text: 'so far', category: 'task' });
    expect(result.current.unified.isRunning).toBe(true);
});

it('shows the pending question of a reopened run from the run store (resync)', async () => {
    mockVersionList.mockResolvedValue([{ id: 'sv1', status: 'waiting_for_user_input' }]);
    const { result } = renderPage([row('q', true), taskRow]);
    emit({
        type: 'resync',
        data: { text: 'before the question', thinking: '', plan: [], files: [], pending_question: { call_id: 'k', questions: [] } },
    });
    await waitFor(() => expect(result.current.stored[1].liveRunId).toBe('r1'));
    expect(result.current.unified.messages[1].text).toBe('before the question');
    expect(useRunStore.getState().conversations.c1.run?.status).toBe('waiting');
});

it('gives the run its own row when the stored task row is an earlier, ended turn', async () => {
    mockVersionList.mockResolvedValue([{ id: 'sv1', status: 'completed' }]);
    const { result } = renderPage([row('q1', true), taskRow, row('q2', true)]);
    emit({ type: 'run_started' });
    await waitFor(() => expect(result.current.stored).toHaveLength(4));
    expect(result.current.stored[1].liveRunId).toBeUndefined();
    expect(result.current.stored[3]).toMatchObject({ liveRunId: 'r1', messageId: 'run:r1' });
});

it('treats a failed run-record request as "not this run"', async () => {
    mockVersionList.mockRejectedValue(new Error('offline'));
    const { result } = renderPage([row('q1', true), taskRow]);
    emit({ type: 'run_started' });
    await waitFor(() => expect(mockVersionList).toHaveBeenCalled());
    await act(async () => {
        await Promise.resolve();
    });
    expect(result.current.stored.map((m) => m.liveRunId)).toEqual([undefined, undefined]);
});

it('leaves a stored task row to the run-record check when the history is reloaded during the run', async () => {
    mockVersionList.mockResolvedValue([{ id: 'sv1', status: 'in_progress' }]);
    const { result } = renderPage([row('q', true), taskRow]);
    emit({ type: 'run_started' });
    await waitFor(() => expect(result.current.stored[1].liveRunId).toBe('r1'));
    // A history response replaces the list: the bound row is a plain task row again.
    const composed = result.current.unified.composeHistory('c1', [row('q', true), taskRow], result.current.stored);
    expect(composed.map((m) => m.liveRunId)).toEqual([undefined, undefined]);
});

it('does nothing with the switch off', async () => {
    const { result } = renderPage([row('q', true), taskRow], false);
    emit({ type: 'run_started' });
    await act(async () => {
        await Promise.resolve();
    });
    expect(mockVersionList).not.toHaveBeenCalled();
    expect(result.current.unified.messages).toBe(result.current.stored);
    expect(result.current.unified.isRunning).toBe(false);
});
