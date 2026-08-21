import { act, renderHook } from '@testing-library/react';
import { useConversationDraft } from './chatDraft';

// The composer's draft must belong to the conversation, not to the component:
// ChatView is NOT remounted when the route's conversationId changes, so the
// hook is what keeps one conversation's half-typed text out of another.
// Each test uses its own ids — the backing store is module-level by design.
describe('store/chatDraft — useConversationDraft', () => {
  it('holds the text typed for the current conversation', () => {
    const { result } = renderHook(() => useConversationDraft('hold-a'));

    expect(result.current[0]).toBe('');
    act(() => result.current[1]('half a sentence'));
    expect(result.current[0]).toBe('half a sentence');
  });

  it('does not carry a draft into the next conversation opened', () => {
    const { result, rerender } = renderHook(({ id }) => useConversationDraft(id), {
      initialProps: { id: 'carry-a' },
    });

    act(() => result.current[1]('meant for A'));
    rerender({ id: 'carry-b' });

    expect(result.current[0]).toBe('');
  });

  it('restores the draft belonging to each conversation when the user switches back', () => {
    const { result, rerender } = renderHook(({ id }) => useConversationDraft(id), {
      initialProps: { id: 'back-a' },
    });

    act(() => result.current[1]('meant for A'));
    rerender({ id: 'back-b' });
    act(() => result.current[1]('meant for B'));

    rerender({ id: 'back-a' });
    expect(result.current[0]).toBe('meant for A');

    rerender({ id: 'back-b' });
    expect(result.current[0]).toBe('meant for B');
  });

  it('forgets a draft once it is cleared (what sending does)', () => {
    const { result, rerender } = renderHook(({ id }) => useConversationDraft(id), {
      initialProps: { id: 'clear-a' },
    });

    act(() => result.current[1]('about to send'));
    act(() => result.current[1]('')); // send handler clears the composer
    rerender({ id: 'clear-b' });
    rerender({ id: 'clear-a' });

    expect(result.current[0]).toBe('');
  });

  it('gives the fresh-chat draft its own slot, separate from real conversations', () => {
    const { result, rerender } = renderHook(({ id }) => useConversationDraft(id), {
      initialProps: { id: 'new' },
    });

    act(() => result.current[1]('unsent first message'));
    rerender({ id: 'promoted-id' });
    expect(result.current[0]).toBe('');

    rerender({ id: 'new' });
    expect(result.current[0]).toBe('unsent first message');
  });
});
