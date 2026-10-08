import { beforeEach, describe, expect, it } from 'vitest';

import { getWorkspaceClientUrl, getWorkspaceRedirectUrl } from '@/utils/workspaceUrl';

describe('workspace URLs', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, '__APP_ENV__', {
      configurable: true,
      value: { BASE_URL: '', WORKSPACE_ORIGIN: '' },
    });
  });

  it('keeps the legacy root deployment paths', () => {
    expect(getWorkspaceClientUrl('/')).toBe('/workspace/');
    expect(getWorkspaceRedirectUrl('/chat/assistant/1/', '?x=1'))
      .toBe('/workspace/chat/assistant/1/?x=1');
  });

  it('places workspace routes under the configured deployment prefix', () => {
    Object.defineProperty(globalThis, '__APP_ENV__', {
      configurable: true,
      value: { BASE_URL: '/ai/agent', WORKSPACE_ORIGIN: '' },
    });

    expect(getWorkspaceClientUrl('/')).toBe('/ai/agent/workspace/');
    expect(getWorkspaceRedirectUrl('/ai/agent/chat/assistant/1/', '?x=1'))
      .toBe('/ai/agent/workspace/chat/assistant/1/?x=1');
  });

  it('keeps a separately hosted workspace origin', () => {
    Object.defineProperty(globalThis, '__APP_ENV__', {
      configurable: true,
      value: {
        BASE_URL: '/ai/agent',
        WORKSPACE_ORIGIN: 'https://workspace.example.com',
      },
    });

    expect(getWorkspaceRedirectUrl('/ai/agent/chat/assistant/1/'))
      .toBe('https://workspace.example.com/workspace/chat/assistant/1/');
  });
});
