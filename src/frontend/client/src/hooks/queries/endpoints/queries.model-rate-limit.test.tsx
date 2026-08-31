/** @jest-environment node */

import type { BsConfig } from '~/types/chat';
import { QueryClient } from '@tanstack/react-query';
import { QueryKeys } from '~/types/chat';
import {
  getModelRateLimitRefetchInterval,
  observeModelRateLimitEvent,
  resolveDisplayedModelRateLimitState,
} from './modelRateLimitPolling';

function config(rateLimitState: 'normal' | 'recovering' | 'busy'): BsConfig {
  return {
    models: [{ key: 'model', id: '17', name: 'Qwen', displayName: 'Qwen', rateLimitState }],
  } as BsConfig;
}

describe('model rate-limit config polling', () => {
  it('polls only while a model is busy or recovering', () => {
    expect(getModelRateLimitRefetchInterval(config('busy'))).toBe(5000);
    expect(getModelRateLimitRefetchInterval(config('recovering'))).toBe(5000);
    expect(getModelRateLimitRefetchInterval(config('normal'))).toBe(false);
    expect(getModelRateLimitRefetchInterval(undefined)).toBe(false);
  });

  it('starts from the live 429 state before the config refetch completes', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData([QueryKeys.bishengConfig], config('normal'));

    observeModelRateLimitEvent(queryClient, {
      errorType: 'rate_limit',
      modelId: 17,
      rateLimitState: 'recovering',
    });

    const projected = queryClient.getQueryData<BsConfig>([QueryKeys.bishengConfig]);
    expect(projected?.models[0].rateLimitState).toBe('recovering');
    expect(getModelRateLimitRefetchInterval(projected)).toBe(5000);
  });

  it('does not alter model projection for ordinary model errors', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData([QueryKeys.bishengConfig], config('normal'));

    observeModelRateLimitEvent(queryClient, {
      errorType: 'service_unavailable',
      modelId: 17,
      rateLimitState: 'busy',
    });

    const projected = queryClient.getQueryData<BsConfig>([QueryKeys.bishengConfig]);
    expect(projected?.models[0].rateLimitState).toBe('normal');
  });

  it('replaces the event state when a later config projection reports recovery', () => {
    expect(resolveDisplayedModelRateLimitState(config('normal').models, 17, 'recovering')).toBe('normal');
    expect(resolveDisplayedModelRateLimitState(undefined, 17, 'recovering')).toBe('recovering');
  });
});
