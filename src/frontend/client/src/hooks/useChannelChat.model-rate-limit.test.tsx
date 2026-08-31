/** @jest-environment node */

import { buildModelRecoveryRequest } from '~/api/modelRecovery';

describe('channel article model recovery', () => {
  it('does not resend article text or create a new user request', () => {
    const request = buildModelRecoveryRequest({ entry: 'channel' }, {
      executionId: 'execution-channel',
      attemptId: 'attempt-next',
      subjectId: 'question-9',
      action: 'manual_retry',
    });
    expect(request.url).toBe('/api/v1/channel/chat/executions/execution-channel/recover');
    expect(request.body).toEqual({
      attempt_id: 'attempt-next',
      subject_id: 'question-9',
      action: 'manual_retry',
    });
    expect(JSON.stringify(request.body)).not.toMatch(/article|text|query/);
  });
});
