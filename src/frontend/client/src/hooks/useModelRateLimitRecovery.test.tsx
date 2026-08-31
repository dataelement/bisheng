/** @jest-environment node */

import {
  buildModelRecoveryRequest,
  type ModelRecoveryTarget,
} from '~/api/modelRecovery';
import {
  buildManualRetryOptions,
  closeSupersededRateLimitRecoveries,
  createRecoveryAttemptController,
  nextManualRetryCount,
  shouldOpenModelSwitchRecommendation,
  shouldRecommendModelSwitch,
} from './useModelRateLimitRecovery';

describe('model rate-limit recovery', () => {
  const command = {
    executionId: 'execution-1',
    attemptId: 'attempt-1',
    subjectId: 'question-9',
    action: 'manual_retry' as const,
  };

  it.each<[ModelRecoveryTarget, string]>([
    [{ entry: 'daily' }, '/api/v1/workstation/chat/executions/execution-1/recover'],
    [
      { entry: 'knowledge', spaceId: '42' },
      '/api/v1/knowledge/space/42/chat/executions/execution-1/recover',
    ],
    [{ entry: 'channel' }, '/api/v1/channel/chat/executions/execution-1/recover'],
  ])('builds the %s recovery request', (target, expectedUrl) => {
    expect(buildModelRecoveryRequest(target, command)).toEqual({
      url: expectedUrl,
      body: {
        attempt_id: 'attempt-1',
        subject_id: 'question-9',
        action: 'manual_retry',
      },
      streaming: true,
    });
  });

  it('keeps one attempt id stable while an action is pending and blocks double submit', async () => {
    let release: () => void = () => undefined;
    const request = jest.fn(
      () => new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    const ids = ['attempt-a', 'attempt-b'];
    const controller = createRecoveryAttemptController(() => ids.shift() || 'unexpected');

    const first = controller.run(request);
    const duplicate = controller.run(request);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith('attempt-a');
    expect(await duplicate).toEqual({ accepted: false, attemptId: 'attempt-a' });

    release();
    await first;
    request.mockImplementationOnce(async () => undefined);
    await controller.run(request);
    expect(request).toHaveBeenLastCalledWith('attempt-b');
  });

  it('accepts events only for the active attempt', () => {
    const controller = createRecoveryAttemptController(() => 'attempt-a');
    controller.setActiveAttempt('attempt-a');
    expect(controller.isActiveAttempt('attempt-a')).toBe(true);
    expect(controller.isActiveAttempt('attempt-old')).toBe(false);
  });

  it('derives the recommendation from page-local manual clicks only', () => {
    let count = 0;
    count = nextManualRetryCount(count, 'manual_retry', 'rate_limit');
    count = nextManualRetryCount(count, 'manual_retry', 'rate_limit');
    expect(shouldRecommendModelSwitch(count)).toBe(false);

    count = nextManualRetryCount(count, 'manual_retry', 'rate_limit');
    expect(shouldRecommendModelSwitch(count)).toBe(true);
    expect(nextManualRetryCount(count, 'switch_model')).toBe(0);
  });

  it('counts only retries that finish with another rate-limit event', () => {
    expect(nextManualRetryCount(2, 'manual_retry', 'rate_limit')).toBe(3);
    expect(nextManualRetryCount(2, 'manual_retry', undefined)).toBe(0);
    expect(nextManualRetryCount(2, 'manual_retry', 'recovery_rejected')).toBe(0);
  });

  it('retries with the model currently selected on the page', () => {
    expect(buildManualRetryOptions('23')).toEqual({
      action: 'manual_retry',
      targetModelId: '23',
    });
    expect(buildManualRetryOptions()).toEqual({
      action: 'manual_retry',
      targetModelId: undefined,
    });
  });

  it('waits for the matching retry result before opening the recommendation', () => {
    const state = {
      errorType: 'rate_limit',
      pending: false,
      recommended: true,
      eventAttemptId: 'attempt-3',
      activeAttemptId: 'attempt-3',
    };
    expect(shouldOpenModelSwitchRecommendation(state)).toBe(true);
    expect(shouldOpenModelSwitchRecommendation({ ...state, pending: true })).toBe(false);
    expect(shouldOpenModelSwitchRecommendation({
      ...state,
      eventAttemptId: 'attempt-old',
    })).toBe(false);
    expect(shouldOpenModelSwitchRecommendation({
      ...state,
      errorType: 'timeout',
    })).toBe(false);
  });

  it('closes old recovery actions when a later user request starts', () => {
    const messages = [
      { errorType: 'rate_limit', unfinished: true, executionId: 'old' },
      { errorType: 'network_timeout', unfinished: true, executionId: 'other' },
    ];

    expect(closeSupersededRateLimitRecoveries(messages)).toEqual([
      { errorType: 'rate_limit', unfinished: false, executionId: 'old' },
      messages[1],
    ]);
  });
});
