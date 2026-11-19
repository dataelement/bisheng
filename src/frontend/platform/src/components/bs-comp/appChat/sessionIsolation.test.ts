import { describe, expect, it, vi } from 'vitest';
import { createMessageStore as createAssistantStore } from '../chatComponent/messageStore';
import { createMessageStore as createWorkflowStore } from '@/pages/BuildPage/flow/FlowChat/messageStore';
const mock = vi.hoisted(() => ({ history: vi.fn() }));
vi.mock('@/controllers/API', () => ({ getChatHistory: mock.history }));
function deferred<T>() {
    let resolve: (value: T) => void = () => undefined;
    const promise = new Promise<T>(done => { resolve = done; });
    return { promise, resolve };
}
for (const [mode, createStore] of [['assistant', createAssistantStore], ['workflow', createWorkflowStore]] as const) {
    describe(`${mode} host isolation`, () => {
        it('owns state independently in two simultaneously mounted panels', () => {
            const a = createStore(); const b = createStore();
            a.getState().changeChatId('a'); b.getState().changeChatId('b');
            a.getState().createSendMsg('Question A');
            b.getState().createSendMsg('Question B');
            expect(a.getState().messages).toHaveLength(1);
            expect(b.getState().messages).toHaveLength(1);
            a.getState().clearMsgs();
            expect(b.getState().messages).toHaveLength(1);
            expect(b.getState().chatId).toBe('b');
        });
        it('discards late A history after A → B → A without replacing the latest A', async () => {
            const oldA = deferred<unknown[]>(); const b = deferred<unknown[]>(); const newA = deferred<unknown[]>();
            mock.history.mockReset().mockReturnValueOnce(oldA.promise).mockReturnValueOnce(b.promise).mockReturnValueOnce(newA.promise);
            const store = createStore();
            const load = (chatId: string) => store.services.loadHistoryMsg('flow', chatId, { appendHistory: true, lastMsg: '' });
            const one = load('a'); const two = load('b'); const three = load('a');
            newA.resolve([{ id: 3, category: 'answer', is_bot: true, message: 'Newest A' }]); await three;
            b.resolve([{ id: 2, category: 'answer', is_bot: true, message: 'B' }]); await two;
            oldA.resolve([{ id: 1, category: 'answer', is_bot: true, message: 'Old A' }]); await one;
            expect(store.getState().messages).toHaveLength(1);
            expect(store.getState().messages[0].message).toBe('Newest A');
        });
    });
}
