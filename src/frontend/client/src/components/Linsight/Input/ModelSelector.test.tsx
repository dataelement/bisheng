/** @jest-environment node */

import type { WorkbenchModelOption } from '~/components/Chat/ModelAvailabilityOption';
import { getTaskDefaultModelId, getUniqueWorkbenchModels } from './modelSelectorHelpers';

function model(id: string, rateLimitState: 'normal' | 'busy' = 'normal'): WorkbenchModelOption {
  return {
    key: 'model',
    id,
    name: `model-${id}`,
    displayName: `Model ${id}`,
    rateLimitState,
  };
}

describe('task model selector availability', () => {
  it('keeps busy models selectable and deduplicates only by id', () => {
    const options = getUniqueWorkbenchModels([
      model('1', 'busy'),
      model('1'),
      model('2'),
    ]);
    expect(options.map((item) => item.id)).toEqual(['1', '2']);
    expect(options[0].rateLimitState).toBe('busy');
  });

  it('does not replace an administrator default merely because it is busy', () => {
    expect(getTaskDefaultModelId([model('1'), model('2', 'busy')], '2')).toBe('2');
  });
});
