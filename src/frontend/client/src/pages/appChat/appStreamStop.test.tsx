import { act, renderHook } from '@testing-library/react';
// eslint-disable-next-line no-restricted-imports -- Exercise the existing app conversation store.
import { RecoilRoot, useRecoilValue, useSetRecoilState } from 'recoil';
import type { ReactNode } from 'react';
import { chatIdState, chatsState, currentChatState, currentRunningState, runningState, submitDataState } from './store/atoms';
import useChatHelpers from './useChatHelpers';
import { closeAppChatWebSocket, useWebSocket } from './useWebsocket';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useToast: () => ({ showToast: jest.fn() }) }));
jest.mock('~/api/apps', () => ({ baseMsgItem: { message: '', files: [], thought: '' } }));
jest.mock('~/api/chat/data-service', () => ({ genTitle: jest.fn() }));
jest.mock('~/utils', () => ({ formatDate: () => '', generateUUID: () => 'message' }));
jest.mock('~/utils/logger', () => ({ __esModule: true, default: { debug: jest.fn() } }));
jest.mock('.', () => ({ FLOW_TYPES: { WORK_FLOW: 10, ASSISTANT: 5, SKILL: 1 } }));
jest.mock('./useAreaText', () => ({ emitAreaTextEvent: jest.fn(), EVENT_TYPE: {} }));
jest.mock('~/pages/standaloneChat/StandaloneChatContext', () => ({ useOptionalStandaloneChatContext: () => null }));

class TestSocket {
    static OPEN = 1;
    static CONNECTING = 0;
    static latest: TestSocket;
    readyState = 1;
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    send = jest.fn();
    close = jest.fn();
    constructor() { TestSocket.latest = this; }
    receive(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
}

let sequence = 0;
function openConversation(flowType: number, awaitingFirstToken = false) {
    const chatId = `stream-stop-${++sequence}`;
    const wrapper = ({ children }: { children: ReactNode }) => (
        <RecoilRoot initializeState={({ set }) => {
            set(chatIdState, chatId);
            set(chatsState, { [chatId]: {
                flow: { id: 'flow-1', flow_type: flowType, isNew: false } as never,
                messages: [
                    { id: 1, category: 'stream_msg', is_bot: true, message: 'previous', files: [], end: true },
                    { id: 2, category: 'question', is_bot: false, message: 'long answer', files: [], end: true },
                    { id: 'runoutput', chat_ui_key: `${chatId}:stream:run:output`, category: 'stream_msg', is_bot: true, message: 'partial answer', files: [],
                        reasoning_log: '', thought: '', end: false },
                ].slice(0, awaitingFirstToken ? 2 : 3) as never, historyEnd: true,
            } });
            set(runningState, { [chatId]: {
                running: true, inputDisabled: true, error: { code: '', data: null },
                inputForm: false, showUpload: true, showStop: true,
            } });
        }}>{children}</RecoilRoot>
    );
    const hook = renderHook(() => {
        const helpers = useChatHelpers();
        useWebSocket(helpers);
        return { chat: useRecoilValue(currentChatState), running: useRecoilValue(currentRunningState),
            submit: useSetRecoilState(submitDataState) };
    }, { wrapper });
    act(() => TestSocket.latest.onopen?.());
    return { ...hook, chatId, socket: TestSocket.latest };
}

beforeEach(() => { Object.defineProperty(window, 'WebSocket', { value: TestSocket, configurable: true }); });

test.each([5, 10])('flow type %s manual stop freezes partial output through late frames and terminal close', (flowType) => {
    const { result, socket, chatId, unmount } = openConversation(flowType);
    act(() => result.current.submit({ action: 'stop' }));
    expect(socket.send).toHaveBeenLastCalledWith(JSON.stringify({ action: 'stop' }));
    expect(result.current.chat?.messages[0]).toMatchObject({ message: 'previous', end: true });
    expect(result.current.chat?.messages[0].stopped).toBeUndefined();
    expect(result.current.chat?.messages[2]).toMatchObject({ message: 'partial answer', stopped: true, end: true });
    act(() => {
        socket.receive({ category: 'stream_msg', type: 'stream', message: { unique_id: 'run', output_key: 'output', msg: 'late' } });
        socket.receive({ category: 'processing', type: 'start', is_bot: true, message: '', files: [] });
        socket.receive(flowType === 10
            ? { category: 'stream_msg', type: 'end', message_id: 42, message: { unique_id: 'run', output_key: 'output', msg: 'replacement' } }
            : { category: 'answer', type: 'end', message_id: 42, message: '' });
        socket.receive({ category: 'processing', type: 'close', message: '' });
    });
    expect(result.current.chat?.messages).toHaveLength(3);
    expect(result.current.chat?.messages[2]).toMatchObject({ id: 42, message: 'partial answer', end: true, stopped: true });
    expect(result.current.running?.running).toBe(false);
    if (flowType === 10) expect(result.current.running?.showReRun).toBe(true);
    else {
        expect(result.current.running?.inputDisabled).toBe(false);
        act(() => result.current.submit({ action: 'skill_input', input: 'next', data: { inputs: { input: 'next' } } }));
        act(() => {
            socket.receive({ category: 'answer', type: 'start', is_bot: true, message: '', files: [] });
            socket.receive({ category: 'answer', type: 'stream', message: 'next answer' });
            socket.receive({ category: 'answer', type: 'end', message: '', message_id: 43 });
            socket.receive({ category: 'processing', type: 'close', message: '' });
        });
        const latest = result.current.chat?.messages.slice(-1)[0];
        expect(latest).toMatchObject({ id: 43, message: 'next answer', end: true });
        expect(latest?.stopped).toBeUndefined();
        expect(result.current.chat?.messages[2].stopped).toBe(true);
    }
    unmount();
    closeAppChatWebSocket(chatId);
});

test('normal workflow completion retains its finished-round separator', () => {
    const { result, socket, chatId, unmount } = openConversation(10);
    act(() => {
        socket.receive({ category: 'stream_msg', type: 'end', message_id: 42,
            message: { unique_id: 'run', output_key: 'output', msg: 'full answer' } });
        socket.receive({ category: 'processing', type: 'close', message: '' });
    });
    expect(result.current.chat?.messages[2]).toMatchObject({ message: 'full answer', end: true });
    expect(result.current.chat?.messages[2].stopped).toBeUndefined();
    expect(result.current.chat?.messages[3]).toMatchObject({ category: 'divider', message: 'com_chat_round_finished' });
    unmount();
    closeAppChatWebSocket(chatId);
});


test('stopping before the first token leaves a visible stopped response', () => {
    const { result, socket, chatId, unmount } = openConversation(5, true);
    act(() => result.current.submit({ action: 'stop' }));
    act(() => socket.receive({ category: 'processing', type: 'close', message: '' }));
    expect(result.current.chat?.messages[2]).toMatchObject({ category: 'stream_msg', message: '', end: true, stopped: true });
    expect(result.current.running?.inputDisabled).toBe(false);
    unmount();
    closeAppChatWebSocket(chatId);
});
