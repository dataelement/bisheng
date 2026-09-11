/** @jest-environment node */

import { loadStandaloneAutoRerunOnOpen } from './standaloneAutoRerunConfig';
import { resolveStandaloneApiVersion } from './StandaloneChatContext';
import { genTitle } from '../../api/chat/api-endpoints';

describe('StandaloneChatPage API channel', () => {
  it('uses v3 for every guest URL and keeps authenticated pages on v1', () => {
    expect(resolveStandaloneApiVersion('guest')).toBe('v3');
    expect(resolveStandaloneApiVersion('auth')).toBe('v1');
    expect(genTitle('v3')).toBe('/api/v3/chat/gen_title');
    expect(genTitle('v2')).toBe('/api/v2/chat/gen_title');
    expect(genTitle('v1')).toBe('/api/v1/workstation/gen_title');
  });
});

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
