import type { PropsWithChildren } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import AiChatMessages from '~/components/Chat/AiChatMessages';
import type { ChatMessage } from '~/api/chatApi';

vi.mock('~/hooks', () => ({ useLocalize: () => (k: string) => k, usePrefersMobileLayout: () => false, useScrollRevealRef: () => vi.fn() }));
vi.mock('~/utils', () => ({ cn: () => '' }));
vi.mock('recoil', () => ({ useSetRecoilState: () => vi.fn() }));
vi.mock('~/store', () => ({ default: {} }));
vi.mock('~/components', () => ({ Button: 'button' }));
vi.mock('~/api/chatApi', () => ({ buildMessageTree: vi.fn() }));
vi.mock('~/components/Chat/AiMessageBubble', () => ({ default: () => null }));
vi.mock('~/components/Chat/HeaderTitle', () => ({ default: () => null }));
vi.mock('~/components/illustrations', () => ({ ArticleQAIllustration: () => null }));
vi.mock('~/components/Chat/MessageSelection', () => ({ SelectionMessagesProvider: ({ children }: PropsWithChildren) => children, SelectAllBelowBanner: () => null }));
vi.mock('~/hooks/useMessageSelection', () => ({ useMessageSelection: () => ({ isActiveForChat: () => false }) }));
vi.mock('~/hooks/useScrollOnUserMessage', () => ({ useScrollOnUserMessage: vi.fn() }));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ getQueryData: vi.fn() }) }));
vi.mock('~/types/chat', () => ({ QueryKeys: {} }));

const messages: ChatMessage[] = [
  { messageId: '11', conversationId: 'chat', parentMessageId: '', sender: 'user', text: 'Old question', isCreatedByUser: true },
  { messageId: '12', conversationId: 'chat', parentMessageId: '11', sender: 'AI', text: 'Old answer' },
  { messageId: '13', conversationId: 'chat', parentMessageId: '12', sender: 'user', text: 'New question', isCreatedByUser: true },
  { messageId: '14', conversationId: 'chat', parentMessageId: '13', sender: 'AI', text: 'New answer' },
];
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
});
afterEach(cleanup);

describe('daily conversation history actions', () => {
  it('addresses the question paired with the clicked answer, including older turns', () => {
    const onDailyMaterialAction = vi.fn();
    render(<AiChatMessages messages={messages} flatMode onDailyMaterialAction={onDailyMaterialAction} />);
    fireEvent.click(screen.getAllByRole('button', { name: 'com_message.regenerate_original_materials' })[0]);
    fireEvent.click(screen.getAllByRole('button', { name: 'com_message.ask_current_materials' })[1]);
    expect(onDailyMaterialAction.mock.calls).toEqual([['11', 'original'], ['13', 'current']]);
  });
  it.each(['share', 'stream', 'task', 'dock'])('does not offer daily material actions on %s', surface => {
    render(<AiChatMessages messages={surface === 'task' ? messages.map(m => ({ ...m, category: 'task' })) : messages} flatMode
      shareToken={surface === 'share' ? 'token' : undefined} isStreaming={surface === 'stream'}
      onDailyMaterialAction={surface === 'dock' ? undefined : vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'com_message.ask_current_materials' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'com_message.regenerate_original_materials' })).toBeNull();
  });
});
