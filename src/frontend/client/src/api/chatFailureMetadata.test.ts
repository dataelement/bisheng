/** @jest-environment jsdom */
import { applyRecoveryMetadata, getAgentMessages } from './chatApi';
import type { ChatMessage } from './chatApi';
import http from '~/api/request';

jest.mock('~/api/request', () => ({ __esModule: true, default: { get: jest.fn() } }));

const failure = { version: 1, failure_id: 'failure-one', category: 'object_storage', occurred_at: '2026-11-05T08:00:00Z' };
const message = (): ChatMessage => ({ messageId: 'answer', parentMessageId: '', conversationId: 'chat', sender: 'assistant', text: 'Partial answer' });

describe('daily failure history', () => {
    it('links each restored answer to its own question for retry, retaining attachments', async () => {
        const files = [{ file_id: 'file-1', filename: 'notes.txt', filepath: 'notes.txt' }];
        jest.mocked(http.get).mockResolvedValueOnce({ data: [
            { message_id: 1, chat_id: 'chat', category: 'question', is_bot: false, message: { query: 'First question', files } },
            { message_id: 2, chat_id: 'chat', category: 'agent_answer', is_bot: true, message: { msg: 'First answer' } },
            { message_id: 3, chat_id: 'chat', category: 'question', is_bot: false, message: { query: 'Second question' } },
            { message_id: 4, chat_id: 'chat', category: 'agent_answer', is_bot: true, message: { msg: '' }, extra: { error: true } },
        ] });
        const messages = await getAgentMessages('chat');
        expect(messages.map(({ messageId, parentMessageId }) => ({ messageId, parentMessageId }))).toEqual([
            { messageId: '1', parentMessageId: '' },
            { messageId: '2', parentMessageId: '1' },
            { messageId: '3', parentMessageId: '2' },
            { messageId: '4', parentMessageId: '3' },
        ]);
        expect(messages[0].files?.[0]).toMatchObject({ filepath: 'notes.txt' });
    });
    it('restores failure classification and preserves partial content and recovery identity', () => {
        const row = message();
        applyRecoveryMetadata(row, JSON.stringify({ error: true, error_type: 'network_timeout', failure_info: failure, execution_id: 'run', attempt_id: 'attempt' }));
        expect(row).toMatchObject({ error: true, failureInfo: failure, text: 'Partial answer', errorType: 'network_timeout', executionId: 'run', attemptId: 'attempt' });
    });
    it('ignores invalid new metadata while retaining the existing failure state', () => {
        const row = message();
        applyRecoveryMetadata(row, { error: true, failure_info: { ...failure, category: 'invalid' } });
        expect(row.error).toBe(true);
        expect(row.failureInfo).toBeUndefined();
    });
});
