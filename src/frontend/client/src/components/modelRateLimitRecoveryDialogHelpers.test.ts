/** @jest-environment node */

import {
  buildRecoveryChatModelSelection,
  getRecoveryModelCandidates,
} from './modelRateLimitRecoveryDialogHelpers';

describe('model rate-limit recovery helpers', () => {
  it('updates the shared input model while preserving the current chat mode', () => {
    expect(
      buildRecoveryChatModelSelection(
        { id: 1, name: 'old-model', manual: false, mode: 'task' },
        '2',
        'new-model',
      ),
    ).toEqual({ id: 2, name: 'new-model', manual: true, mode: 'task' });
  });

  it('keeps only distinct available alternatives in the switch list', () => {
    const models = [
      { key: 'current', id: '1', name: 'current', displayName: 'Current' },
      { key: 'available', id: '2', name: 'available', displayName: 'Available' },
      { key: 'duplicate', id: '2', name: 'duplicate', displayName: 'Duplicate' },
      {
        key: 'busy',
        id: '3',
        name: 'busy',
        displayName: 'Busy',
        rateLimitState: 'busy' as const,
      },
      {
        key: 'recovering',
        id: '4',
        name: 'recovering',
        displayName: 'Recovering',
        rateLimitState: 'recovering' as const,
      },
    ];

    expect(getRecoveryModelCandidates(models, 1)).toEqual([models[1]]);
  });
});
