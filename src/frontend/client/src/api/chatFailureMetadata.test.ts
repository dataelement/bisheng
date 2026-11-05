/** @jest-environment jsdom */
import { applyRecoveryMetadata } from './chatApi';
import type { ChatMessage } from './chatApi';

jest.mock('~/api/request', () => ({ __esModule: true, default: {} }));

const failure = { version: 1, failure_id: 'failure-one', category: 'object_storage', occurred_at: '2026-11-05T08:00:00Z' };
const message = (): ChatMessage => ({ messageId: 'answer', parentMessageId: '', conversationId: 'chat', sender: 'assistant', text: 'Partial answer' });

describe('daily failure history', () => {
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
