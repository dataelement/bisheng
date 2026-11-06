import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ChatMessages from '@/pages/BuildPage/flow/FlowChat/ChatMessages';
import { MessageStoreProvider, useMessageStore, createMessageStore } from '@/pages/BuildPage/flow/FlowChat/messageStore';
vi.mock('@/components/bs-comp/appChat/PlatformConversationMessages', () => ({ PlatformConversationMessages: () => <div>Transcript</div> }));
vi.mock('@/controllers/API', () => ({ getChatHistory: vi.fn() }));
afterEach(cleanup);
it('keeps workflow suggestions in the message scroller and sends them through the panel-local transport event', () => {
    let panel!: ReturnType<ReturnType<typeof createMessageStore>['getState']>;
    function Harness() { panel = useMessageStore(); return null; }
    render(<MessageStoreProvider><Harness /><ChatMessages canExecute logo="" useName="" guideWord="" title="Workflow" loadMore={async () => {}} version="v1" /></MessageStoreProvider>);
    act(() => { panel.setInputLocked(false); panel.setQuestions(['Try this']); });
    const question = screen.getByRole('button', { name: 'Try this' });
    expect(question.closest('#message-panne')).not.toBeNull();
    const listener = vi.fn(); panel!.eventTarget.addEventListener('userResendMsgEvent', listener);
    fireEvent.click(question);
    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ send: true, message: 'Try this' });
    act(() => panel.setInputLocked(true));
    expect(screen.queryByRole('button', { name: 'Try this' })).toBeNull();
    act(() => { panel.setInputLocked(false); panel.clearMsgs(); });
    expect(screen.queryByRole('button', { name: 'Try this' })).toBeNull();
});
