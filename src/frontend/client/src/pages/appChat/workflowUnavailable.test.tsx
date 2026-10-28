import { act, renderHook } from '@testing-library/react';
// eslint-disable-next-line no-restricted-imports -- Exercise the existing conversation store without adding state.
import { RecoilRoot, useRecoilValue, useSetRecoilState } from 'recoil';
import type { ReactNode } from 'react';
import { chatIdState, chatsState, currentRunningState, runningState, submitDataState } from './store/atoms';
import useChatHelpers from './useChatHelpers';
import { closeAppChatWebSocket, useWebSocket } from './useWebsocket';

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
    useToast: () => ({ showToast: jest.fn() }),
}));
jest.mock('~/api/apps', () => ({ baseMsgItem: {} }));
jest.mock('~/api/chat/data-service', () => ({ genTitle: jest.fn() }));
jest.mock('~/utils', () => ({ formatDate: () => '', generateUUID: () => 'message' }));
jest.mock('~/utils/logger', () => ({ __esModule: true, default: { debug: jest.fn() } }));
jest.mock('.', () => ({ FLOW_TYPES: { WORK_FLOW: 10 } }));
jest.mock('./useAreaText', () => ({ emitAreaTextEvent: jest.fn(), EVENT_TYPE: {} }));
jest.mock('./appUtils/skillMethod', () => ({ SkillMethod: {}, runLogsTypes: [] }));
jest.mock('~/pages/standaloneChat/StandaloneChatContext', () => ({
    useOptionalStandaloneChatContext: () => ({ flowType: 'workflow', autoRerunOnOpen: true }),
}));

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
function openConversation() {
    const chatId = `offline-test-${++sequence}`;
    const wrapper = ({ children }: { children: ReactNode }) => (
        <RecoilRoot initializeState={({ set }) => {
            set(chatIdState, chatId);
            set(chatsState, { [chatId]: {
                flow: { id: 'flow-1', flow_type: 10, isNew: false } as never,
                messages: [], historyEnd: true,
            } });
            set(runningState, { [chatId]: {
                running: true, inputDisabled: true, error: { code: '', data: null },
                inputForm: { value: [] }, showUpload: true, showStop: true, showReRun: true,
            } });
        }}>{children}</RecoilRoot>
    );
    const hook = renderHook(() => {
        const helpers = useChatHelpers();
        useWebSocket(helpers);
        return {
            state: useRecoilValue(currentRunningState), submit: useSetRecoilState(submitDataState),
            setChatId: useSetRecoilState(chatIdState), setChats: useSetRecoilState(chatsState),
            setRunning: useSetRecoilState(runningState),
        };
    }, { wrapper });
    act(() => TestSocket.latest.onopen?.());
    return { ...hook, chatId, socket: TestSocket.latest };
}

beforeEach(() => { Object.defineProperty(window, 'WebSocket', { value: TestSocket, configurable: true }); });

test.each(['input', 'form_submit', 'message_input', 'restart'])(
'offline error settles the run and blocks stale %s submissions', (action) => {
    const { result, socket, chatId, unmount } = openConversation();
    act(() => {
        socket.receive({ category: 'error', type: 'end', message: { status_code: 13010 } });
        socket.receive({ category: 'processing', type: 'close', message: '' });
        socket.receive({ category: 'processing', type: 'close', chat_id: chatId,
            message: { event: 'workflow_status_checked', status: 'finished' } });
        socket.receive({ category: 'input', message: { node_id: 'input_1', input_schema: { tab: 'form_input' } } });
        socket.onerror?.();
    });
    expect(result.current.state).toMatchObject({
        running: false, showStop: false, showUpload: false, showReRun: false,
        inputDisabled: true, inputForm: false, error: { code: '13010' },
    });
    const sends = socket.send.mock.calls.length;
    act(() => result.current.submit({ action, chatId, flowId: 'flow-1', data: {} }));
    expect(socket.send).toHaveBeenCalledTimes(sends);
    expect(result.current.state?.running).toBe(false);
    unmount();
    closeAppChatWebSocket(chatId);
});

test('normal completion settles running and keeps manual rerun available', () => {
    const { result, socket, chatId, unmount } = openConversation();
    act(() => socket.receive({ category: 'processing', type: 'close', message: '' }));
    expect(result.current.state).toMatchObject({ running: false, showStop: false, showReRun: true, error: { code: '' } });
    unmount();
    closeAppChatWebSocket(chatId);
});

test('late offline-card events preserve their conversation while another chat is open', () => {
    const { result, socket, chatId, unmount } = openConversation();
    act(() => socket.receive({ category: 'error', type: 'end', message: { status_code: 13010 } }));
    const otherId = `${chatId}-other`;
    act(() => {
        result.current.setChats(prev => ({ ...prev, [otherId]: { ...prev[chatId], messages: [] } }));
        result.current.setRunning(prev => ({ ...prev, [otherId]: {
            ...prev[chatId], error: { code: '', data: null }, running: true, showStop: true,
        } }));
        result.current.setChatId(otherId);
    });
    act(() => {
        socket.receive({ category: 'input', message: { node_id: 'input_1', input_schema: { tab: 'dialog_input' } } });
        socket.receive({ category: 'processing', type: 'close', message: '' });
    });
    expect(result.current.state).toMatchObject({ running: true, error: { code: '' } });
    act(() => result.current.setChatId(chatId));
    expect(result.current.state).toMatchObject({ running: false, inputDisabled: true, inputForm: false, error: { code: '13010' } });
    unmount();
    closeAppChatWebSocket(chatId);
    closeAppChatWebSocket(otherId);
});
