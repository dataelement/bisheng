import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
// eslint-disable-next-line no-restricted-imports -- Exercise existing conversation and header stores.
import { RecoilRoot, useRecoilValue, useSetRecoilState } from 'recoil';
import type { Chat, ChatMessageType } from '~/@types/chat';
import store from '~/store';
import AppChat from './index';
import { chatIdState, chatsState } from './store/atoms';

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
    useAuthContext: () => ({ user: { username: 'Tester' } }),
    useMediaQuery: () => false, usePrefersMobileLayout: () => false,
}));
jest.mock('~/hooks/usePrefersMobileLayout', () => ({ __esModule: true, default: () => false }));
jest.mock('react-activation', () => ({ useUnactivate: jest.fn() }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/api/apps', () => ({}));
jest.mock('~/api/permission', () => ({ checkResourceAction: async () => ({ allowed: true }) }));
jest.mock('~/api/messageExport', () => ({}));
jest.mock('~/api/request', () => ({ translateApiErrorMessage: jest.fn() }));
jest.mock('./useChatHelpers', () => ({ __esModule: true, default: () => ({}) }));
jest.mock('./useWebsocket', () => ({ useWebSocket: jest.fn() }));
jest.mock('~/utils', () => ({ cn: (...values: string[]) => values.filter(Boolean).join(' '), generateUUID: () => 'new-chat' }));
jest.mock('~/components/Avator', () => ({ __esModule: true, default: () => null }));
jest.mock('./ChatInput', () => ({ __esModule: true, default: () => null }));
jest.mock('./ChatMessages', () => ({ __esModule: true, default: () => null }));
jest.mock('./components/ChatEmptyState', () => ({ ChatEmptyState: () => <div>Empty conversation</div> }));
jest.mock('~/components/Chat/MessageSelection', () => ({ ExportFormatSheet: () => null, MessageSelectionToolbar: () => null }));
jest.mock('~/pages/Subscription/Article/AddToKnowledgeModal', () => ({ AddToKnowledgeModal: () => null }));
jest.mock('~/hooks/useMessageSelection', () => ({
    useExitSelectionOnChatChange: jest.fn(),
    useMessageSelection: () => ({ state: {}, getSelectedIds: jest.fn(), exitSelectionMode: jest.fn() }),
}));
jest.mock('~/components/Chat/Messages/Content/useCitationReferencePanel', () => ({ useCitationReferencePanel: () => ({}) }));
jest.mock('~/components/Share/ShareChat', () => ({ __esModule: true, default: () => <button>Share conversation</button> }));

function message(category: string, content: string | object = 'Content'): ChatMessageType {
    return { category, message: content } as ChatMessageType;
}
function conversation(messages: ChatMessageType[], canShare = true): Chat {
    return { flow: { id: 'flow', name: 'App', flow_type: 10, can_share: canShare }, messages, historyEnd: true } as Chat;
}
let updateChats: (chats: Record<string, Chat>) => void;
function Probe() {
    updateChats = useSetRecoilState(chatsState);
    const navigate = useNavigate();
    const header = useRecoilValue(store.chatMobileHeaderState);
    return <><button onClick={() => navigate("/app/fresh/flow/10")}>New conversation</button><output data-testid="compact-share">{header?.hideShare === false && header.readOnly === false ? 'visible' : 'hidden'}</output></>;
}
function setup(chat: Chat, readOnly = false) {
    return render(<RecoilRoot initializeState={({ set }) => {
        set(chatIdState, 'current');
        set(chatsState, { current: chat, fresh: conversation([message("stream_msg", "Welcome")]) });
    }}><MemoryRouter initialEntries={[`/app/current/flow/${chat.flow.flow_type}`]}>
        <Probe />
        <Routes><Route path="/app/:conversationId/:fid/:type" element={<AppChat shareToken={readOnly ? 'shared-link' : ''} />} /></Routes>
    </MemoryRouter></RecoilRoot>);
}
async function expectShare(visible: boolean) {
    await waitFor(() => expect(screen.getByTestId('compact-share')).toHaveTextContent(visible ? 'visible' : 'hidden'));
    expect(screen.queryByRole('button', { name: 'Share conversation' }) !== null).toBe(visible);
}

it.each([
    ['empty', []],
    ['workflow welcome', [message('stream_msg', 'Welcome')]],
    ['configured welcome', [message('guide_word'), message('guide_question')]],
    ['workflow form', [message('output_with_input_msg', { value: [] })]],
    ['automated output', [message('output_msg'), message('answer'), message('divider')]],
] as const)('keeps both share entries hidden for %s', async (_name, messages) => {
    setup(conversation([...messages]));
    await expectShare(false);
});

const attachmentQuestion: ChatMessageType = {
    ...message('question', ''), files: [{ data: 'file', type: 'file', data_type: 'file' }],
};

it.each([
    ['text', message('question', 'Hello')],
    ['form', message('question', { symptoms: 'Cough' })],
    ['attachment', attachmentQuestion],
] as const)('enables both entries after a %s submission and clears them for a new conversation', async (_name, question) => {
    setup(conversation([message('stream_msg', 'Welcome')]));
    await expectShare(false);
    act(() => updateChats({ current: conversation([question]) }));
    await expectShare(true);
    act(() => updateChats({ current: conversation([]) }));
    await expectShare(false);
});

it.each([5, 10])('shares loaded user history for flow type %s', async flowType => {
    const chat = conversation([message('question'), message('answer')]);
    chat.flow.flow_type = flowType;
    setup(chat);
    await expectShare(true);
});

it('requires the existing app sharing permission', async () => {
    setup(conversation([message('question')], false));
    await expectShare(false);
});

it('keeps a read-only shared conversation read-only', async () => {
    setup(conversation([message('question')]), true);
    await expectShare(false);
});

it('derives sharing from the destination conversation while the active store switches', async () => {
    setup(conversation([message('question')]));
    await expectShare(true);
    fireEvent.click(screen.getByRole('button', { name: 'New conversation' }));
    await expectShare(false);
});
