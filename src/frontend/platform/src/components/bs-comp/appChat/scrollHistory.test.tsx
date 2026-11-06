import { cleanup, render } from '@testing-library/react';
import type { ComponentType } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import WorkflowChat from '@/pages/BuildPage/flow/FlowChat/Chat';
import AssistantChat from '@/components/bs-comp/chatComponent';
const mock = vi.hoisted(() => ({ scroll: vi.fn(), state: {
    chatId: 'session', messages: [], hisMessages: [], inputForm: null, running: false,
    historyEnd: false, questions: [], inputLocked: false, showGuideQuestion: false,
    setShowGuideQuestion: vi.fn(), eventTarget: new EventTarget(),
} }));
vi.mock('@bisheng/chat', () => ({ useConversationScroll: mock.scroll, SuggestedQuestions: () => null }));
vi.mock('@/components/bs-comp/appChat/PlatformConversationMessages', () => ({ PlatformConversationMessages: () => null }));
vi.mock('@/components/bs-comp/chatComponent/ChatInput', () => ({ default: () => null }));
vi.mock('@/pages/BuildPage/flow/FlowChat/ChatInput', () => ({ default: () => null }));
vi.mock('@/pages/BuildPage/flow/FlowChat/InputForm', () => ({ default: () => null }));
vi.mock('@/components/bs-comp/chatComponent/messageStore', () => ({ useMessageStore: () => mock.state }));
vi.mock('@/pages/BuildPage/flow/FlowChat/messageStore', () => ({ useMessageStore: () => mock.state }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it.each([{ name: 'workflow', component: WorkflowChat }, { name: 'assistant', component: AssistantChat }])('$name does not page without a history loader, while retaining audit paging', ({ component }) => {
    // Legacy hosts have incomplete inferred props; exercise their public optional loader contract.
    const Chat = component as ComponentType<{ debug?: boolean; loadMore?: () => void }>;
    const { rerender } = render(<Chat />);
    expect(mock.scroll).toHaveBeenLastCalledWith(expect.objectContaining({ canLoadOlder: false }));
    const loadMore = vi.fn();
    rerender(<Chat debug loadMore={loadMore} />);
    expect(mock.scroll).toHaveBeenLastCalledWith(expect.objectContaining({ canLoadOlder: true }));
});
