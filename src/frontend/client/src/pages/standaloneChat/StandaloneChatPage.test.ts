/** @jest-environment node */

import { loadStandaloneAutoRerunOnOpen } from './standaloneAutoRerunConfig';

describe('StandaloneChatPage auto rerun configuration', () => {
  it.each([true, false])('uses an explicit workflow switch value: %s', async (value) => {
    const enabled = await loadStandaloneAutoRerunOnOpen('workflow', async () => ({
      data: { workflow: { auto_rerun_on_open: value } },
    }));

    expect(enabled).toBe(value);
  });

  it.each([
    {},
    { data: {} },
    { data: { workflow: {} } },
    { data: { workflow: { auto_rerun_on_open: 'true' } } },
  ])('fails closed for a missing or invalid switch', async (response) => {
    await expect(loadStandaloneAutoRerunOnOpen('workflow', async () => response)).resolves.toBe(false);
  });

  it('fails closed when loading configuration fails', async () => {
    await expect(loadStandaloneAutoRerunOnOpen('workflow', async () => {
      throw new Error('unavailable');
    })).resolves.toBe(false);
  });

  it('does not load configuration for standalone assistants', async () => {
    const loadConfig = jest.fn();

    await expect(loadStandaloneAutoRerunOnOpen('assistant', loadConfig)).resolves.toBe(false);
    expect(loadConfig).not.toHaveBeenCalled();
  });
});
