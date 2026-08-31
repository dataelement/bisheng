/** @jest-environment node */

import { applyRecoveryMetadata, type ChatMessage } from '~/api/chatApi';
import { buildModelRecoveryRequest } from '~/api/modelRecovery';
import { createRecoveryAttemptController } from './useModelRateLimitRecovery';

function answer(): ChatMessage {
  return {
    messageId: 'answer-1',
    parentMessageId: 'question-1',
    conversationId: 'chat-1',
    sender: 'assistant',
    text: 'partial answer',
  };
}

describe('daily chat model recovery', () => {
  it('restores one logical answer from persisted recovery metadata', () => {
    const message = answer();
    applyRecoveryMetadata(message, JSON.stringify({
      execution_id: 'execution-1',
      attempt_id: 'attempt-2',
      unfinished: true,
      error_type: 'rate_limit',
      rate_limit_state: 'recovering',
      recovery_subject_id: 'question-9',
      model_id: 7,
    }));
    expect(message).toMatchObject({
      text: 'partial answer',
      executionId: 'execution-1',
      attemptId: 'attempt-2',
      recoverySubjectId: 'question-9',
      unfinished: true,
      error: true,
      errorType: 'rate_limit',
      rateLimitState: 'recovering',
      modelId: 7,
    });
  });

  it('uses the original execution and rejects stale attempt events', () => {
    const request = buildModelRecoveryRequest({ entry: 'daily' }, {
      executionId: 'execution-1',
      attemptId: 'attempt-new',
      subjectId: 'question-9',
      action: 'manual_retry',
    });
    expect(request.streaming).toBe(true);
    expect(request.url).toContain('/execution-1/recover');

    const controller = createRecoveryAttemptController(() => 'attempt-new');
    controller.setActiveAttempt('attempt-new');
    expect(controller.isActiveAttempt('attempt-old')).toBe(false);
  });
});
