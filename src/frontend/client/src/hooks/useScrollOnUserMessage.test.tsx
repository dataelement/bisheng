import { renderHook } from '@testing-library/react';
import { useScrollOnUserMessage } from './useScrollOnUserMessage';

const user = (messageId: string) => ({ messageId, isCreatedByUser: true });
const assistant = (messageId: string) => ({ messageId, isCreatedByUser: false });

it('scrolls on a new user message, but not on streamed reply updates', () => {
    const scroll = jest.fn();
    const { rerender } = renderHook(({ messages }) => useScrollOnUserMessage(messages, 'chat-1', true, scroll), {
        initialProps: { messages: [user('old'), assistant('reply')] },
    });
    expect(scroll).not.toHaveBeenCalled();
    rerender({ messages: [user('old'), assistant('reply'), user('new'), assistant('pending')] });
    expect(scroll).toHaveBeenCalledTimes(1);
    rerender({ messages: [user('old'), assistant('reply'), user('new'), assistant('pending')] });
    expect(scroll).toHaveBeenCalledTimes(1);
});

it('does not force scrolling for history loading, conversation changes, or surfaces that did not opt in', () => {
    const scroll = jest.fn();
    const { rerender } = renderHook(({ messages, conversationId, enabled }) => useScrollOnUserMessage(messages, conversationId, enabled, scroll), {
        initialProps: { messages: [user('old')], conversationId: 'chat-1', enabled: true },
    });
    rerender({ messages: [user('earlier'), user('old')], conversationId: 'chat-1', enabled: true });
    rerender({ messages: [user('other')], conversationId: 'chat-2', enabled: true });
    rerender({ messages: [user('other'), user('new')], conversationId: 'chat-2', enabled: false });
    expect(scroll).not.toHaveBeenCalled();
});
