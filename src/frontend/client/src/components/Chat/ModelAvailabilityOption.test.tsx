/** @jest-environment node */

import { renderToStaticMarkup } from 'react-dom/server';
import { ModelAvailabilityOption, WorkbenchModelOption } from './ModelAvailabilityOption';

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) =>
    ({
      'com_message.model_busy_suffix': ' · Service busy',
    })[key] ?? key,
}));

function model(values: Partial<WorkbenchModelOption>): WorkbenchModelOption {
  return {
    key: 'model',
    id: '17',
    name: 'Qwen',
    displayName: 'Qwen',
    ...values,
  };
}

describe('ModelAvailabilityOption', () => {
  it('shows a selectable busy decoration', () => {
    const markup = renderToStaticMarkup(
      <ModelAvailabilityOption model={model({ rateLimitState: 'busy' })} />,
    );
    expect(markup).toContain('aria-label="Qwen · Service busy"');
  });
});
