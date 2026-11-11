/** @jest-environment node */
import { openChatStream, type SSESubmission } from './useAiChatSSE';

interface StreamDouble {
    readyState: number;
    emit: (name: string, data?: unknown) => void;
}
const mockStreams: StreamDouble[] = [];

jest.mock('sse.js', () => ({
    SSE: class {
        readyState = 1;
        listeners = new Map<string, ((event: unknown) => void)[]>();
        constructor() { mockStreams.push(this); }
        addEventListener(name: string, listener: (event: unknown) => void) {
            this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
        }
        emit(name: string, event: unknown = {}) {
            this.listeners.get(name)?.forEach((listener) => listener(event));
        }
        stream() { this.emit('open'); }
        close() { this.readyState = 2; this.emit('readystatechange', { readyState: 2 }); }
        dispatchEvent(event: { type: string }) { this.emit(event.type, event); }
    },
}));
jest.mock('~/api/chatApi', () => ({ getSSEUrl: () => '/chat' }));

function open() {
    const submission: SSESubmission = {
        payload: {},
        userMessage: { messageId: 'question', parentMessageId: '', conversationId: 'chat', sender: 'user', text: 'Question' },
        onCreated: jest.fn(), onMessage: jest.fn(), onAgentUpdate: jest.fn(), onFinal: jest.fn(),
        onError: jest.fn(), onStart: jest.fn(), onEnd: jest.fn(), onTaskHandoff: jest.fn(),
    };
    const handle = openChatStream(submission, (key) => key);
    return { submission, handle, stream: mockStreams[mockStreams.length - 1] };
}

describe('daily transport failure boundary', () => {
    it('records a network failure once when an unfinished stream closes', () => {
        const { stream, submission } = open();
        stream.emit('message', { data: JSON.stringify({ category: 'agent_answer', type: 'stream', message: { msg: 'Partial answer' } }) });
        stream.emit('readystatechange', { readyState: 2 });
        stream.emit('error', { data: '' });
        expect(submission.onError).toHaveBeenCalledTimes(1);
        expect(submission.onError).toHaveBeenCalledWith('api_errors.failure_network', undefined, {
            failureInfo: expect.objectContaining({ category: 'network', service: 'transport', failure_id: expect.any(String), occurred_at: expect.any(String) }),
        });
        expect(submission.onAgentUpdate).toHaveBeenCalledWith(expect.objectContaining({ text: 'Partial answer' }));
        expect(submission.onEnd).toHaveBeenCalledTimes(1);
    });

    it('preserves a typed service failure instead of replacing it on close', () => {
        const { stream, submission } = open();
        const failure = { version: 1, category: 'database', service: 'milvus', failure_id: 'failure-one', occurred_at: '2026-11-05T08:00:00Z' };
        stream.emit('error', { data: JSON.stringify({ status_code: 11090, data: { error_type: 'network_timeout', failure_info: failure } }) });
        stream.emit('readystatechange', { readyState: 2 });
        expect(submission.onError).toHaveBeenCalledTimes(1);
        expect(submission.onError).toHaveBeenCalledWith('workstation.chat.answer_failed', 11090, expect.objectContaining({ failureInfo: failure, errorType: 'network_timeout' }));
    });

    it.each([
        { final: true },
        { event: 'linsight_task_handoff', data: { session_version_id: 'version-one', chat_id: 'chat' } },
        { category: 'agent_answer', type: 'end', message: { msg: 'Done' } },
    ])('accepts the normal terminal frame without a fabricated network failure: %o', (frame) => {
        const { stream, submission } = open();
        stream.emit('message', { data: JSON.stringify(frame) });
        stream.emit('readystatechange', { readyState: 2 });
        expect(submission.onError).not.toHaveBeenCalled();
    });

    it('does not report a network failure after an intentional local stop', () => {
        const { handle, submission } = open();
        handle.close();
        expect(submission.onError).not.toHaveBeenCalled();
        expect(submission.onEnd).toHaveBeenCalledTimes(1);
    });

    it('leaves an unclassified HTTP 401 response unclassified', () => {
        const { stream, submission } = open();
        stream.emit('error', { data: JSON.stringify({ status_code: 401, data: {} }) });
        expect(submission.onError).toHaveBeenCalledWith('workstation.chat.answer_failed', 401, expect.objectContaining({ failureInfo: undefined }));
    });
});


it.each([401, 500, 502])('does not label a non-JSON HTTP %s as a transport failure', (responseCode) => {
    const { stream, submission } = open();
    stream.emit('error', { data: '<html>Failure</html>', responseCode });
    stream.emit('readystatechange', { readyState: 2 });
    expect(submission.onError).toHaveBeenCalledTimes(1);
    expect(submission.onError).toHaveBeenCalledWith('workstation.chat.answer_failed', responseCode);
});

it('leaves explicit unknown error text unclassified without transport evidence', () => {
    const {stream,submission} = open();
    stream.emit('error', {data:'Connection error'});
    expect(submission.onError).toHaveBeenCalledWith('workstation.chat.answer_failed', undefined);
});

describe('browser goes offline with a pending stream', () => {
    const windowDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'window');
    const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
    let browser: EventTarget;

    beforeEach(() => {
        browser = new EventTarget();
        Object.defineProperty(globalThis, 'window', { configurable: true, value: browser });
        Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { onLine: true } });
    });

    afterEach(() => {
        if (windowDescriptor) Object.defineProperty(globalThis, 'window', windowDescriptor);
        else Reflect.deleteProperty(globalThis, 'window');
        if (navigatorDescriptor) Object.defineProperty(globalThis, 'navigator', navigatorDescriptor);
        else Reflect.deleteProperty(globalThis, 'navigator');
    });

    it('reports immediately without waiting for an XHR error or close', () => {
        const { stream, submission } = open();
        browser.dispatchEvent(new Event('offline'));
        browser.dispatchEvent(new Event('offline'));
        stream.emit('error', { data: '' });
        expect(stream.readyState).toBe(2);
        expect(submission.onError).toHaveBeenCalledTimes(1);
        expect(submission.onError).toHaveBeenCalledWith('api_errors.failure_network', undefined, {
            failureInfo: expect.objectContaining({ category: 'network' }),
        });
        expect(submission.onEnd).toHaveBeenCalledTimes(1);
    });

    it('removes the listener on normal completion and intentional stop', () => {
        const remove = jest.spyOn(browser, 'removeEventListener');
        const completed = open();
        completed.stream.emit('message', { data: JSON.stringify({ final: true }) });
        const stopped = open();
        stopped.handle.close();
        browser.dispatchEvent(new Event('offline'));
        expect(completed.submission.onError).not.toHaveBeenCalled();
        expect(stopped.submission.onError).not.toHaveBeenCalled();
        expect(remove).toHaveBeenCalledTimes(2);
    });

    it('does not start a stream when already offline', () => {
        Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { onLine: false } });
        const { submission } = open();
        expect(submission.onStart).not.toHaveBeenCalled();
        expect(submission.onError).toHaveBeenCalledTimes(1);
        expect(submission.onEnd).toHaveBeenCalledTimes(1);
    });
});
