/** @jest-environment node */

import { buildModelRecoveryRequest } from '~/api/modelRecovery';

describe('knowledge model recovery', () => {
  it.each(['file', 'folder'])('reuses the same execution for %s recovery', () => {
    const request = buildModelRecoveryRequest({ entry: 'knowledge', spaceId: '42' }, {
      executionId: 'execution-knowledge',
      attemptId: 'attempt-next',
      subjectId: 'question-9',
      action: 'switch_model',
      targetModelId: '9',
    });
    expect(request).toEqual({
      url: '/api/v1/knowledge/space/42/chat/executions/execution-knowledge/recover',
      body: {
        attempt_id: 'attempt-next',
        subject_id: 'question-9',
        action: 'switch_model',
        target_model_id: 9,
      },
      streaming: true,
    });
    expect(JSON.stringify(request.body)).not.toContain('query');
  });
});
