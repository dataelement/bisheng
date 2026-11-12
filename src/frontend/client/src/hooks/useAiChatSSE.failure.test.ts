import { openChatStream, type ChatStreamHandle, type SSESubmission } from './useAiChatSSE';

interface StreamOptions {
    payload: string;
    headers: Record<string, string>;
}
interface StreamDouble {
    readyState: number;
    options: StreamOptions;
    emit: (name: string, event?: unknown) => void;
}
const mockStreams: StreamDouble[] = [];
const mockHandles: ChatStreamHandle[] = [];

jest.mock('sse.js', () => ({ SSE: class {
    readyState = 1;
    listeners = new Map<string, ((event: unknown) => void)[]>();
    options: StreamOptions;
    constructor(_url: string, options: StreamOptions) {
        this.options = options;
        mockStreams.push(this);
    }
    addEventListener(name: string, listener: (event: unknown) => void) {
        this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
    }
    emit(name: string, event: unknown = {}) {
        this.listeners.get(name)?.forEach((listener) => listener(event));
    }
    stream() { this.emit('open'); }
    close() { this.readyState = 2; this.emit('readystatechange', { readyState: 2 }); }
    dispatchEvent(event: { type: string }) { this.emit(event.type, event); }
} }));
jest.mock('~/api/chatApi', () => ({ getSSEUrl: () => '/chat' }));
jest.mock('~/api/request', () => ({ translateApiErrorMessage: () => '' }));
jest.mock('~/layouts/WorkbenchSidebar/projectChatCreation', () => ({
    captureProjectChatDraft: () => null,
    bindProjectChatCreation: () => ({}),
}));

function open(overrides: Partial<SSESubmission> = {}) {
    const submission: SSESubmission = {
        payload: {}, projectDraft: null,
        userMessage: { messageId: 'question', parentMessageId: '', conversationId: 'chat', sender: 'user', text: 'Question' },
        onCreated: jest.fn(), onMessage: jest.fn(), onAgentUpdate: jest.fn(), onFinal: jest.fn(),
        onError: jest.fn(), onStart: jest.fn(), onEnd: jest.fn(), onTaskHandoff: jest.fn(),
        ...overrides,
    };
    const handle = openChatStream(submission, (key) => key);
    mockHandles.push(handle);
    return { submission, handle, stream: mockStreams[mockStreams.length - 1] };
}

beforeEach(() => {
    jest.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
});
afterEach(async () => {
    mockHandles.forEach((handle) => handle.close());
    await Promise.resolve();
    mockHandles.length = 0;
    mockStreams.length = 0;
    jest.restoreAllMocks();
});

it('reports an unfinished close once and preserves partial answer updates', async () => {
    const { stream, submission } = open();
    stream.emit('message', { data: JSON.stringify({ category: 'agent_answer', type: 'stream', message: { msg: 'Partial' } }) });
    stream.emit('readystatechange', { readyState: 2 });
    await Promise.resolve();
    stream.emit('error', { data: '' });
    expect(submission.onError).toHaveBeenCalledTimes(1);
    expect(submission.onError).toHaveBeenCalledWith('api_errors.failure_network', undefined, {
        failureInfo: expect.objectContaining({ category: 'network', service: 'transport' }),
    });
    expect(submission.onAgentUpdate).toHaveBeenCalledWith(expect.objectContaining({ text: 'Partial' }));
    expect(submission.onEnd).toHaveBeenCalledTimes(1);
});

it('lets a typed error beat close in the same event turn', async () => {
    const { stream, submission } = open();
    const failure = { version: 1, category: 'model_service', failure_id: 'model-failure', occurred_at: '2026-11-05T08:00:00Z' };
    stream.emit('readystatechange', { readyState: 2 });
    stream.emit('error', { data: JSON.stringify({ status_code: 11090, data: { error_type: 'content_filter', failure_info: failure, reference_id: 'reference-1' } }) });
    await Promise.resolve();
    expect(submission.onError).toHaveBeenCalledTimes(1);
    expect(submission.onError).toHaveBeenCalledWith('api_errors.fallback', 11090,
        expect.objectContaining({ errorType: 'content_filter', failureInfo: failure, referenceId: 'reference-1' }));
});

it.each([
    { final: true },
    { event: 'linsight_task_handoff', data: { session_version_id: 'version-1', chat_id: 'chat' } },
    { category: 'processing', type: 'close' },
])('does not manufacture a network failure after a normal terminal frame: %o', async (frame) => {
    const { stream, submission } = open();
    stream.emit('message', { data: JSON.stringify(frame) });
    stream.emit('readystatechange', { readyState: 2 });
    await Promise.resolve();
    window.dispatchEvent(new Event('offline'));
    expect(submission.onError).not.toHaveBeenCalled();
});

it('accepts the mainline answer-end then processing-close sequence', async () => {
    const { stream, submission } = open();
    stream.emit('message', { data: JSON.stringify({ category: 'agent_answer', type: 'end', message: { msg: 'Done' } }) });
    stream.emit('message', { data: JSON.stringify({ category: 'processing', type: 'close' }) });
    stream.emit('readystatechange', { readyState: 2 });
    await Promise.resolve();
    expect(submission.onError).not.toHaveBeenCalled();
});

it('ends immediately on offline even when XHR has not reported an error', async () => {
    const { stream, submission } = open();
    window.dispatchEvent(new Event('offline'));
    window.dispatchEvent(new Event('offline'));
    await Promise.resolve();
    expect(stream.readyState).toBe(2);
    expect(submission.onError).toHaveBeenCalledTimes(1);
    expect(submission.onEnd).toHaveBeenCalledTimes(1);
});

it('does not open an already-offline request and removes its listener', () => {
    jest.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    const remove = jest.spyOn(window, 'removeEventListener');
    const { submission } = open();
    expect(submission.onStart).not.toHaveBeenCalled();
    expect(submission.onError).toHaveBeenCalledTimes(1);
    expect(submission.onEnd).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledWith('offline', expect.any(Function));
});

it('does not report local stop as a network failure', async () => {
    const { handle, submission } = open();
    handle.close();
    window.dispatchEvent(new Event('offline'));
    await Promise.resolve();
    expect(submission.onError).not.toHaveBeenCalled();
    expect(submission.onEnd).toHaveBeenCalledTimes(1);
});

it.each([401, 500, 502])('keeps an HTTP %s failure separate from transport loss', async (responseCode) => {
    const { stream, submission } = open();
    stream.emit('readystatechange', { readyState: 2 });
    stream.emit('error', { data: '<html>Error</html>', responseCode });
    await Promise.resolve();
    expect(submission.onError).toHaveBeenCalledWith('api_errors.fallback', responseCode);
    expect(submission.onError).toHaveBeenCalledTimes(1);
});

it('retains the mainline flow-lease header on streams with the offline watcher', () => {
    const { stream } = open({ flowLeaseId: 'lease-1' });
    expect(stream.options.headers['X-Flow-Lease-Id']).toBe('lease-1');
});
