import { act, render, renderHook, screen } from '@testing-library/react';
// eslint-disable-next-line no-restricted-imports -- Exercise the existing conversation store without adding state.
import { RecoilRoot, useRecoilValue } from 'recoil';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { bishengConfState, chatIdState, chatsState, currentChatState, runningState } from './store/atoms';
import useChatHelpers from './useChatHelpers';
import { closeAppChatWebSocket, useWebSocket } from './useWebsocket';
import ChatMessages from './ChatMessages';

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
    useToast: () => ({ showToast: jest.fn() }),
    useAuthContext: () => ({ user: { username: 'tester' } }),
}));
jest.mock('~/api/apps', () => ({ baseMsgItem: { chat_id: '', is_bot: true, message: '', category: '' } }));
jest.mock('~/api/chat/data-service', () => ({ genTitle: jest.fn() }));
jest.mock('~/utils', () => ({ formatDate: () => '2026-11-25T10:00:00', generateUUID: () => 'uuid-1' }));
jest.mock('~/utils/logger', () => ({ __esModule: true, default: { debug: jest.fn() } }));
jest.mock('.', () => ({ FLOW_TYPES: { WORK_FLOW: 10, ASSISTANT: 5 } }));
jest.mock('@bisheng/chat', () => ({
    ConversationMessages: ({
        messages,
        slots,
    }: {
        messages: Array<{ key: string; text: string }>;
        slots: {
            content: (text: string, msg: { key: string; text: string }) => ReactNode;
            footer?: (msg: { key: string; text: string }, ref: { current: null }) => ReactNode;
        };
    }) => (
        <div>
            {messages.map((m) => (
                <div key={m.key}>
                    {slots.content(m.text, m)}
                    {slots.footer?.(m, { current: null })}
                </div>
            ))}
        </div>
    ),
    SuggestedQuestions: () => null,
    useConversationScroll: () => undefined,
}));
jest.mock('./useAreaText', () => ({ emitAreaTextEvent: jest.fn(), EVENT_TYPE: {} }));
jest.mock('./appUtils/skillMethod', () => ({ SkillMethod: {}, runLogsTypes: [] }));
jest.mock('./components/ClientChatMarkdown', () => ({ ClientChatMarkdown: () => null }));
jest.mock('./components/ClientMessageFooter', () => ({ ClientMessageFooter: () => null }));
jest.mock('./components/ClientMessageAttachments', () => ({ ClientMessageAttachments: () => null }));
jest.mock('./components/ClientUserActions', () => ({ ClientUserActions: () => null }));
jest.mock('./components/InputForm', () => ({ __esModule: true, default: () => null }));
jest.mock('./components/InputFormSkill', () => ({ __esModule: true, default: () => null }));
jest.mock('~/components/Chat/MessageSelection', () => ({
    SelectionMessagesProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
    SelectAllBelowBanner: () => null,
    MessageCheckbox: () => null,
}));
jest.mock('~/components/ui/Avatar', () => ({
    Avatar: () => null,
    AvatarImage: () => null,
    AvatarName: () => null,
}));
jest.mock('~/pages/standaloneChat/StandaloneChatContext', () => ({
    useOptionalStandaloneChatContext: () => ({ flowType: 'workflow', autoRerunOnOpen: false }),
}));
jest.mock('~/components/ChatErrorCard', () => ({
    ChatErrorCard: ({ errorType, errorCode }: { errorType?: string; errorCode?: number }) => (
        <div data-testid="chat-error-card" data-error-type={errorType} data-error-code={errorCode}>
            credit_exhausted_card
        </div>
    ),
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

beforeEach(() => {
    Object.defineProperty(window, 'WebSocket', { value: TestSocket, configurable: true });
});

it.each([
    ['assistant', 5, { category: 'error', type: 'end', message: { status_code: 26121, status_message: 'Monthly token limit reached' } }],
    ['workflow_start_or_mid_run', 10, { category: 'error', type: 'over', message: { status_code: 26121, status_message: 'Monthly token limit reached' } }],
    ['guest_error_type', 10, { category: 'error', type: 'over', message: { status_code: 500, status_message: 'limit', data: { error_type: 'credit_exhausted' } } }],
])('renders inline ChatErrorCard in appChat stream on 26121 (%s)', (_label, flowType, frame) => {
    const chatId = `credit-test-${flowType}-${Math.random()}`;
    const Wrapper = ({ children }: { children: ReactNode }) => (
        <MemoryRouter>
            <RecoilRoot initializeState={({ set }) => {
                set(chatIdState, chatId);
                set(bishengConfState, null);
                set(chatsState, {
                    [chatId]: {
                        flow: { id: 'app-1', flow_type: flowType, isNew: false } as never,
                        messages: [],
                        historyEnd: true,
                    },
                });
                set(runningState, {
                    [chatId]: {
                        running: true,
                        inputDisabled: false,
                        error: { code: '', data: null },
                        inputForm: false,
                        showUpload: true,
                        showStop: true,
                        showReRun: false,
                    },
                });
            }}>{children}</RecoilRoot>
        </MemoryRouter>
    );

    function Harness() {
        const helpers = useChatHelpers();
        useWebSocket(helpers);
        const chat = useRecoilValue(currentChatState);
        return (
            <div>
                <div data-testid="msg-count">{chat?.messages?.length ?? 0}</div>
                <ChatMessages readOnly={false} title="App" logo={null} />
            </div>
        );
    }

    const view = render(<Wrapper><Harness /></Wrapper>);
    act(() => TestSocket.latest.onopen?.());
    act(() => {
        TestSocket.latest.receive(frame);
    });

    const card = screen.getByTestId('chat-error-card');
    expect(card).toHaveAttribute('data-error-type', 'credit_exhausted');
    expect(card).toHaveAttribute('data-error-code', '26121');

    view.unmount();
    closeAppChatWebSocket(chatId);
});

it('appendCreditExhaustedMsg helper adds inline credit_exhausted entry cleanly', () => {
    const chatId = 'helper-credit-test';
    const wrapper = ({ children }: { children: ReactNode }) => (
        <RecoilRoot initializeState={({ set }) => {
            set(chatIdState, chatId);
            set(chatsState, {
                [chatId]: { flow: { id: 'app-1', flow_type: 5, isNew: false } as never, messages: [], historyEnd: true },
            });
            set(runningState, {
                [chatId]: { running: true, inputDisabled: false, error: { code: '', data: null }, inputForm: false, showUpload: false, showStop: true, showReRun: false },
            });
        }}>{children}</RecoilRoot>
    );
    const { result } = renderHook(() => {
        const helpers = useChatHelpers();
        const chat = useRecoilValue(currentChatState);
        return { helpers, chat };
    }, { wrapper });

    act(() => {
        result.current.helpers.message.appendCreditExhaustedMsg(chatId, { statusCode: 26121, message: 'Monthly limit' });
    });

    expect(result.current.chat?.messages).toHaveLength(1);
    expect(result.current.chat?.messages[0]).toMatchObject({
        category: 'credit_exhausted',
        extra: { status_code: 26121, error_type: 'credit_exhausted' },
    });
});
