/**
 * The end event carries the answer as persisted, after the backend dropped
 * citation markers it could not back. The hook must finalize with that text,
 * not the raw streamed one, or those markers render as broken badges until a
 * reload (knowledge-space and channel chat).
 */
import { renderHook } from '@testing-library/react';
import useStreamChatSSE, { type StreamChatSSESubmission } from './useStreamChatSSE';

type Listener = (e: { data: string }) => void;
let mockLastSse: MockSSE | null = null;

class MockSSE {
    listeners: Record<string, Listener[]> = {};
    constructor() {
        // eslint-disable-next-line @typescript-eslint/no-this-alias
        mockLastSse = this;
    }
    addEventListener(type: string, fn: Listener) {
        (this.listeners[type] ||= []).push(fn);
    }
    emit(type: string, data: unknown) {
        (this.listeners[type] || []).forEach((fn) => fn({ data: JSON.stringify(data) }));
    }
    stream() {}
    close() {}
}

jest.mock('sse.js', () => ({ SSE: jest.fn().mockImplementation(() => new MockSSE()) }));

function start() {
    const onFinal = jest.fn();
    const submission: StreamChatSSESubmission = {
        sseUrl: '/x',
        payload: {},
        onStart: jest.fn(),
        onMessage: jest.fn(),
        onFinal,
        onError: jest.fn(),
        onEnd: jest.fn(),
    };
    renderHook(() => useStreamChatSSE(submission));
    return { sse: mockLastSse as MockSSE, onFinal };
}

describe('useStreamChatSSE end event', () => {
    it('finalizes with the persisted content, not the raw stream', () => {
        const { sse, onFinal } = start();
        sse.emit('message', { type: 'stream', message: { content: 'Answer.\ue200knowledgesearch_bad:0\ue202' } });
        sse.emit('message', { type: 'end', message: { content: 'Answer.', message_id: 42 } });

        expect(onFinal).toHaveBeenCalledWith('Answer.', 42);
    });

    it('keeps the thinking block ahead of the persisted content', () => {
        const { sse, onFinal } = start();
        sse.emit('message', { type: 'stream', message: { reasoning_content: 'thinking', content: 'raw' } });
        sse.emit('message', { type: 'end', message: { content: 'clean', message_id: 7 } });

        expect(onFinal).toHaveBeenCalledWith(':::thinking\nthinking\n:::\nclean', 7);
    });

    it('falls back to the streamed text when the end event carries none', () => {
        const { sse, onFinal } = start();
        sse.emit('message', { type: 'stream', message: { content: 'streamed' } });
        sse.emit('message', { type: 'end', message: { message_id: 9 } });

        expect(onFinal).toHaveBeenCalledWith('streamed', 9);
    });
});
