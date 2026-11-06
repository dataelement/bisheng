/** @jest-environment node */
import { produce } from 'immer';
import { assistantStreamForHost, historyForHost, messagesForPresentation, messagesForTransport, startAssistantForHost, workflowStreamForHost } from '@bisheng/chat/core';

describe('shared conversations inside the existing client state adapter', () => {
    it('keeps workflow deltas and final identity when Immer passes draft rows', () => {
        const options = { mode: 'workflow' as const, sessionKey: 'a' };
        const original = { messages: historyForHost([{ id: 1, category: 'question', message: 'Q' }], options) };
        const first = produce(original, draft => {
            draft.messages = workflowStreamForHost(draft.messages, { type: 'stream', category: 'stream_msg', message: { unique_id: 'run', output_key: 'a', msg: 'ha' } }, 'a');
        });
        const next = produce(first, draft => {
            draft.messages = workflowStreamForHost(draft.messages, { type: 'stream', category: 'stream_msg', message: { unique_id: 'run', output_key: 'a', msg: 'ha' } }, 'a');
        });
        const done = produce(next, draft => {
            draft.messages = workflowStreamForHost(draft.messages, { type: 'end', category: 'stream_msg', message_id: 9, message: { unique_id: 'run', output_key: 'a', msg: 'Final' } }, 'a');
        });
        expect(messagesForPresentation(next.messages, options).map(message => message.text)).toEqual(['Q', 'haha']);
        expect(messagesForPresentation(done.messages, options)[1]).toMatchObject({ text: 'Final', sourceMessageId: '9' });
        expect(original.messages).toHaveLength(1);
        expect(() => JSON.stringify(done)).not.toThrow();
    });
    it('reconciles assistant final covers and strips UI-only snapshots from transport', () => {
        const original = { messages: startAssistantForHost([], { type: 'start', category: 'processing' }, 'a') };
        const streamed = produce(original, draft => {
            draft.messages = assistantStreamForHost(draft.messages, { type: 'stream', message: 'Streamed' }, 'a');
        });
        const ended = produce(streamed, draft => {
            draft.messages = startAssistantForHost(draft.messages, { type: 'start', category: 'answer' }, 'a');
            draft.messages = assistantStreamForHost(draft.messages, { type: 'end_cover', category: 'answer', message_id: 8, message: 'Final' }, 'a');
        });
        expect(ended.messages).toHaveLength(1);
        expect(messagesForPresentation(ended.messages, { mode: 'assistant', sessionKey: 'a' })[0]).toMatchObject({ text: 'Final', sourceMessageId: '8' });
        const outgoing = messagesForTransport(ended.messages);
        expect(JSON.stringify(outgoing)).not.toContain('__bisheng_chat_snapshot');
        expect(outgoing[0]).not.toHaveProperty('chat_ui_key');
        expect(outgoing[0]).toMatchObject({ message: 'Final', id: 8 });
    });
});
