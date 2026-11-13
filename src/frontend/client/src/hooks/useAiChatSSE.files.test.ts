import { openChatStream, type ChatStreamHandle, type SSESubmission } from './useAiChatSSE';

type MockListener = (payload: unknown) => void;

const mockStreams: Array<{ emit: (name: string, payload?: unknown) => void }> = [];
const mockHandles: ChatStreamHandle[] = [];

jest.mock('sse.js', () => ({
    SSE: class {
        readyState = 1;
        listeners = new Map();
        constructor() {
            mockStreams.push(this);
        }
        addEventListener(name: string, listener: MockListener) {
            this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
        }
        emit(name: string, payload: unknown = {}) {
            (this.listeners.get(name) ?? []).forEach((listener: MockListener) => listener(payload));
        }
        stream() { this.emit('open'); }
        close() { this.readyState = 2; this.emit('readystatechange', { readyState: 2 }); }
        dispatchEvent(payload: { type: string }) { this.emit(payload.type, payload); }
    },
}));
jest.mock('~/api/chatApi', () => ({ getSSEUrl: () => '/chat' }));
jest.mock('~/api/request', () => ({ translateApiErrorMessage: () => '' }));
jest.mock('~/layouts/WorkbenchSidebar/projectChatCreation', () => ({
    captureProjectChatDraft: () => null,
    bindProjectChatCreation: () => ({}),
}));

function open() {
    const submission: SSESubmission = {
        payload: {}, projectDraft: null,
        userMessage: { messageId: 'question', parentMessageId: '', conversationId: 'chat', sender: 'user', text: 'Question' },
        onCreated: jest.fn(), onMessage: jest.fn(), onAgentUpdate: jest.fn(), onFinal: jest.fn(),
        onError: jest.fn(), onStart: jest.fn(), onEnd: jest.fn(), onTaskHandoff: jest.fn(),
    };
    mockHandles.push(openChatStream(submission, (key) => key));
    return { submission, stream: mockStreams[mockStreams.length - 1] };
}

function answerEnd(message: Record<string, unknown>) {
    return { data: JSON.stringify({ category: 'agent_answer', type: 'end', message }) };
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

it('carries the generated files of the answer-end frame into the final patch', () => {
    const { stream, submission } = open();
    const files = [{ file_id: 'g1', file_name: 'report.docx', path: 'output/report.docx', source: 'code_interpreter' }];

    stream.emit('message', answerEnd({ msg: 'Done', files }));

    expect(submission.onAgentUpdate).toHaveBeenLastCalledWith(expect.objectContaining({ finalised: true, files }));
});

it('leaves files off the final patch when the answer produced none', () => {
    const { stream, submission } = open();

    stream.emit('message', answerEnd({ msg: 'Done', files: [] }));

    const patch = (submission.onAgentUpdate as jest.Mock).mock.calls.at(-1)[0];
    expect(patch).toMatchObject({ finalised: true });
    expect(patch).not.toHaveProperty('files');
});
