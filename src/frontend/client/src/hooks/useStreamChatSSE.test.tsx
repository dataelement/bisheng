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
    const { result } = renderHook(() => useStreamChatSSE(submission));
    return { sse: mockLastSse as MockSSE, onFinal, onMessage: submission.onMessage as jest.Mock, onEnd: submission.onEnd as jest.Mock, abort: result.current.abort };
}

describe('useStreamChatSSE end event', () => {
    it('defers citation fragments until final metadata while continuing ordinary text', () => {
        const { sse, onMessage, onFinal } = start();
        sse.emit('message', { type: 'stream', message: { content: 'Answer know' } });
        expect(onMessage).toHaveBeenLastCalledWith('Answer ');
        sse.emit('message', { type: 'stream', message: { content: 'ledgesearch_15c85c1a:29 More text.' } });
        expect(onMessage).toHaveBeenLastCalledWith('Answer  More text.');
        const text = 'Answer knowledgesearch_15c85c1a:29 More text.';
        const citations = [{ citationId: 'knowledgesearch_15c85c1a', type: 'rag', itemId: '29' }];
        sse.emit('message', { type: 'end', message: { content: text, message_id: 42 }, citations });
        expect(onFinal).toHaveBeenLastCalledWith(text, 42, citations);
    });
    it('restores unknown references and ordinary word prefixes when final metadata is absent', () => {
        const { sse, onMessage, onFinal } = start();
        const text = 'Answer knowledgesearch_deadbeef:99 and know';
        sse.emit('message', { type: 'stream', message: { content: text } });
        expect(onMessage).toHaveBeenLastCalledWith('Answer  and ');
        sse.emit('message', { type: 'end', message: { message_id: 42 } });
        expect(onFinal).toHaveBeenLastCalledWith(text, 42, undefined);
    });
    it.each(['cancel', 'abort'])('releases buffered text on %s', action => {
        const { sse, onMessage, abort } = start();
        const text = 'Answer knowledgesearch_deadbeef:99';
        sse.emit('message', { type: 'stream', message: { content: text } });
        expect(onMessage).toHaveBeenLastCalledWith('Answer ');
        if (action === 'cancel') sse.emit('cancel', {});
        else abort();
        sse.emit('message', { type: 'stream', message: { content: ' late event' } });
        expect(onMessage).toHaveBeenLastCalledWith(text);
    });
    it('keeps the final answer after late cancellation or stream events', () => {
        const { sse, onMessage, onFinal, onEnd } = start();
        sse.emit('message', { type: 'end', message: { content: 'Final answer', message_id: 42 } });
        sse.emit('cancel', {});
        sse.emit('message', { type: 'stream', message: { content: ' late event' } });
        expect(onFinal).toHaveBeenLastCalledWith('Final answer', 42, undefined);
        expect(onMessage).not.toHaveBeenCalled();
        expect(onEnd).toHaveBeenCalledTimes(1);
    });
    it('forwards the exact citation registry with the final persisted answer', () => {
        const { sse, onFinal } = start();
        const citations = [{ citationId: 'knowledgesearch_15c85c1a', itemId: '29' }];
        sse.emit('message', { type: 'end', message: { content: 'Answer', message_id: 42 }, citations });
        expect(onFinal).toHaveBeenCalledWith('Answer', 42, citations);
    });
    it('finalizes with the persisted content, not the raw stream', () => {
        const { sse, onFinal } = start();
        sse.emit('message', { type: 'stream', message: { content: 'Answer.\ue200knowledgesearch_bad:0\ue202' } });
        sse.emit('message', { type: 'end', message: { content: 'Answer.', message_id: 42 } });

        expect(onFinal).toHaveBeenCalledWith('Answer.', 42, undefined);
    });

    it('keeps the thinking block ahead of the persisted content', () => {
        const { sse, onFinal } = start();
        sse.emit('message', { type: 'stream', message: { reasoning_content: 'thinking', content: 'raw' } });
        sse.emit('message', { type: 'end', message: { content: 'clean', message_id: 7 } });

        expect(onFinal).toHaveBeenCalledWith(':::thinking\nthinking\n:::\nclean', 7, undefined);
    });

    it('falls back to the streamed text when the end event carries none', () => {
        const { sse, onFinal } = start();
        sse.emit('message', { type: 'stream', message: { content: 'streamed' } });
        sse.emit('message', { type: 'end', message: { message_id: 9 } });

        expect(onFinal).toHaveBeenCalledWith('streamed', 9, undefined);
    });
});
